import asyncio
import time
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.agent.agent import osint_agent
from app.core.config import settings
from app.core.database import async_session_maker
from app.core.events import event_bus
from app.engine.rule_engine import rule_engine
from app.identity import enrichment as identity_enrichment
from app.identity.resolver import identity_resolver
from app.identity.scorer import SCORER_VERSION
from app.identity.risk import calculate_risk_score
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
                # 2. Execute OSINT extraction: Autonomous Agent vs Rule-Based
                use_agent = (
                    investigation.strategy == "agentic"
                    or (investigation.strategy == "auto" and settings.ai_enabled)
                )

                if use_agent and settings.ai_enabled:
                    from app.agent.autonomous_agent import autonomous_agent
                    entities = await autonomous_agent.run(str_id, target, db)
                else:
                    entities = await rule_engine.execute_investigation(str_id, target, db)

                # 3. Segunda pasada de puntuación: señales que necesitan red
                #    (hashing de avatares y embeddings semánticos), calculadas en
                #    lote y aplicadas solo a las entidades que afectan.
                enrichment = await identity_enrichment.enrich_and_rescore(entities, target)
                await db.flush()

                # 4. Resolver clusters de identidad.
                #    Se le pasan las relaciones para que pueda agrupar por
                #    union-find sobre la evidencia directa (correo compartido,
                #    enlace explícito, avatar idéntico) en lugar de limitarse a
                #    clasificar cada entidad por su puntuación aislada.
                rel_stmt = select(Relationship).where(
                    Relationship.investigation_id == investigation.id
                )
                relationships = list((await db.execute(rel_stmt)).scalars().all())

                clusters = await identity_resolver.resolve_clusters(
                    investigation.id, entities, target, relationships
                )
                for cluster in clusters:
                    db.add(cluster)
                await db.flush()

                # 5. Calculate Risk & Exposure Score
                risk_score, risk_level, recommendations = calculate_risk_score(entities, target)
                investigation.risk_score = risk_score

                # 6. Generate Intelligence Narrative (AI or Template)
                narrative = await osint_agent.generate_intelligence_narrative(
                    target=target,
                    entities=entities,
                    risk_score=risk_score,
                    risk_level=risk_level,
                )
                investigation.summary = narrative

                # 7. Record Metrics for Academic Research
                elapsed = round(time.time() - start_time, 2)
                investigation.metrics = {
                    "execution_time_seconds": elapsed,
                    "entities_discovered": len(entities),
                    "clusters_formed": len(clusters),
                    "risk_level": risk_level,
                    "recommendations": recommendations,
                    "ai_enhanced": bool(settings.ai_enabled),
                    "strategy_used": investigation.strategy,
                    # Trazabilidad del modelo de identidad: sin la versión del
                    # scorer, las investigaciones anteriores y posteriores a un
                    # recalibrado no son comparables en un análisis agregado.
                    "scorer_version": SCORER_VERSION,
                    "semantic_matching": bool(settings.semantic_matching_enabled),
                    **{f"enrichment_{k}": v for k, v in enrichment.items()},
                }
                investigation.status = "completed"
                investigation.completed_at = datetime.now(timezone.utc)

                await db.commit()

                # 8. Broadcast completion event via SSE
                await event_bus.publish(str_id, {
                    "type": "investigation_complete",
                    "status": "completed",
                    "risk_score": risk_score,
                    "risk_level": risk_level,
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
