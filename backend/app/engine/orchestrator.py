import asyncio
import time
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.core.config import settings
from app.core.database import async_session_maker
from app.core.fingerprint import run_fingerprint
from app.core.events import event_bus
from app.engine.hybrid_engine import hybrid_engine
from app.engine.rule_engine import rule_engine
from app.identity import enrichment as identity_enrichment
from app.identity.resolver import correlation_resolver
from app.models.investigation import Investigation
from app.models.relationship import Relationship


class Orchestrator:
    """Master Investigation Orchestrator."""

    async def run_investigation(self, investigation_id: UUID) -> None:
        """Background task entry point for running an investigation."""
        start_time = time.time()

        async with async_session_maker() as db:
            # 1. Load investigation and target
            stmt = (
                select(Investigation)
                .where(Investigation.id == investigation_id)
                .options(selectinload(Investigation.target))
            )
            result = await db.execute(stmt)
            investigation = result.scalar_one_or_none()
            if not investigation:
                return

            investigation.status = "running"
            await db.commit()

            str_id = str(investigation_id)
            target = investigation.target

            try:
                # 2. Extracción OSINT: tres estrategias seleccionables.
                #
                #    `rules` y `agentic` son las dos condiciones experimentales
                #    originales y se conservan intactas. `hybrid` se AÑADE como
                #    tercera: ejecuta el barrido heurístico completo y deja al LLM
                #    refinar lo que quedó sin cubrir. Implementarla como reemplazo
                #    del if/else habría hecho que el motor de reglas corriese
                #    siempre, y entonces `rules` y `agentic` dejarían de ser
                #    condiciones independientes: se perdería el contraste más
                #    limpio que tiene el proyecto para el artículo.
                #
                #    `engine_used` registra el motor que REALMENTE corrió, que no
                #    siempre es la estrategia pedida: sin LLM configurado, tanto
                #    `auto` como `agentic` como `hybrid` acaban ejecutando el
                #    motor de reglas. Antes eso no se anotaba y la comparativa
                #    contaba como "agéntica" una investigación hecha por reglas.
                strategy = investigation.strategy
                engine_stats: dict = {}

                if strategy == "hybrid" and settings.ai_enabled:
                    engine_used = "hybrid"
                    run = await hybrid_engine.execute_investigation(str_id, target, db)
                    entities, engine_stats = run.entities, run.stats
                elif strategy == "hybrid":
                    # Sin LLM el híbrido degrada a su capa 1. Se ejecuta igual
                    # (el usuario obtiene su investigación), pero se contabiliza
                    # como lo que fue: una corrida del motor de reglas.
                    engine_used = "rules"
                    run = await hybrid_engine.execute_investigation(str_id, target, db)
                    entities, engine_stats = run.entities, run.stats
                elif strategy in ("agentic", "auto") and settings.ai_enabled:
                    from app.agent.autonomous_agent import autonomous_agent
                    run = await autonomous_agent.run(str_id, target, db)
                    entities, engine_stats = run.entities, run.stats
                    # Si el LLM cayó antes de que el agente ejecutara ninguna
                    # herramienta, todo lo hizo el barrido heurístico de respaldo:
                    # fue una corrida del motor de reglas y así se contabiliza. Si
                    # llegó a ejecutar alguna, la corrida es mixta y queda marcada
                    # con `agent_fallback_to_rules`.
                    only_rules = run.stats.get("agent_fallback_to_rules") and not run.stats.get(
                        "agent_tools_executed"
                    )
                    engine_used = "rules" if only_rules else "agentic"
                else:
                    engine_used = "rules"
                    entities = await rule_engine.execute_investigation(str_id, target, db)

                # 3. Enriquecimiento: convierte coincidencias visuales en
                #    evidencia visible, sin inferir la identidad de nadie.
                enrichment = await identity_enrichment.enrich_correlations(entities, db)

                await db.flush()

                # 4. Materializar grupos de observaciones conectadas por
                #    evidencia explícita. Ningún grupo se atribuye al objetivo.
                rel_stmt = select(Relationship).where(
                    Relationship.investigation_id == investigation.id
                )
                relationships = list((await db.execute(rel_stmt)).scalars().all())

                groups = await correlation_resolver.resolve_groups(
                    investigation.id, entities, relationships
                )
                for group in groups:
                    db.add(group)
                await db.flush()

                # 5. El expediente ya no convierte cuentas correlacionadas en un
                #    riesgo atribuido al objetivo. Solo resume observaciones.
                investigation.summary = (
                    f"Se registraron {len(entities)} observaciones y {len(groups)} grupos visuales. "
                    "Las conexiones representan evidencia técnica, no pertenencia a una persona."
                )

                # 7. Record Metrics for Academic Research
                elapsed = round(time.time() - start_time, 2)
                investigation.metrics = {
                    "execution_time_seconds": elapsed,
                    "entities_discovered": len(entities),
                    "correlation_groups": len(groups),
                    "ai_enhanced": bool(settings.ai_enabled),
                    "strategy_used": investigation.strategy,
                    # El motor que realmente ejecutó la investigación. Puede
                    # diferir de la estrategia pedida cuando no hay LLM; sin este
                    # campo, la comparativa del artículo atribuiría al agente
                    # resultados producidos por el motor de reglas.
                    "engine_used": engine_used,
                    **engine_stats,
                    # Huella de la configuración: sin ella, las investigaciones
                    # medidas antes y después de ampliar el catálogo de sitios
                    # quedan mezcladas en la misma tabla sin que nada permita
                    # distinguirlas.
                    **{f"config_{k}": v for k, v in run_fingerprint().items()},
                    **{f"enrichment_{k}": v for k, v in enrichment.items()},
                }
                investigation.status = "completed"
                investigation.completed_at = datetime.now(timezone.utc)

                await db.commit()

                # 8. Broadcast completion event via SSE
                await event_bus.publish(str_id, {
                    "type": "investigation_complete",
                    "status": "completed",
                    "entities_count": len(entities),
                    "elapsed_seconds": elapsed,
                    "message": "Investigación y mapa digital finalizados con éxito.",
                    "timestamp": time.time(),
                })

            except Exception as err:
                investigation.status = "failed"
                investigation.metrics = {"error": str(err), "time": time.time() - start_time}
                await db.commit()

                await event_bus.publish(str_id, {
                    "type": "investigation_error",
                    "status": "failed",
                    "error": str(err),
                    "message": f"Error durante la investigación: {err}",
                    "timestamp": time.time(),
                })


orchestrator = Orchestrator()
