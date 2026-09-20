"""
Motor híbrido: barrido heurístico determinista + refinamiento por IA.

`ANALISIS_OSINT_MUNDIAL.md` (§5.3) recomienda un orquestador donde el motor de
reglas corra siempre primero y el LLM actúe como capa de refinamiento. La
tentación es implementarlo sustituyendo el `if/else` del orquestador, pero eso
**destruiría el diseño experimental del artículo**: si el motor de reglas corre
siempre, `rules` y `agentic` dejan de ser condiciones independientes y la tabla
de resultados pierde su contraste más limpio.

Por eso el híbrido se añade como **tercera estrategia**, no como reemplazo. El
coste marginal es cero (reutiliza las dos mitades que ya existían) y la tabla
del artículo pasa de dos filas a tres.

Las dos capas:

1. **Heurística** (`rule_engine.collect_findings`) — determinista, reproducible,
   sin coste de tokens. Barre el catálogo completo y pivotea por reglas.
2. **Refinamiento IA** — recibe un resumen de lo que encontró la capa 1 y de lo
   que quedó sin explorar, y pide únicamente las llamadas que añadan algo nuevo.
   No repite ninguna combinación herramienta/identificador ya ejecutada.

La persistencia ocurre **una sola vez**, al final, con los hallazgos de ambas
capas juntos: así la deduplicación de `persist_findings` colapsa un perfil que
hayan encontrado las dos en una única entidad, en vez de duplicarlo.

Si no hay LLM configurado la capa 2 no se ejecuta y el motor reporta
`hybrid_degraded=True`. El orquestador registra entonces `engine_used = "rules"`,
para que la comparativa del artículo no atribuya al híbrido un resultado que
produjo el motor de reglas solo.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm_client import complete_with_retries, describe_llm_error
from app.agent.tool_dispatch import (
    build_tool_schemas,
    dispatch_tool_call,
    resolve_tool_name,
)
from app.core.config import settings
from app.core.events import event_bus
from app.engine.persistence import build_relationships, persist_findings
from app.engine.rule_engine import SweepResult, rule_engine
from app.engine.trace import PendingObservation, trace_recorder
from app.models.entity import Entity
from app.models.target import Target
from app.tools.base import TargetContext, ToolFinding
from app.tools.registry import tool_registry

HEURISTIC_LAYER = "heuristic"
REFINEMENT_LAYER = "refinement"

REFINEMENT_SYSTEM_PROMPT = (
    "Eres la capa de refinamiento de un sistema OSINT de concientización. Un motor "
    "heurístico determinista YA ha barrido las fuentes evidentes y ha pivotado sobre "
    "los identificadores que encontró. Tu trabajo NO es repetir ese barrido, sino "
    "cerrar los huecos que dejó.\n\n"
    "Criterios:\n"
    "- Pide solo llamadas que aporten información que el barrido no pudo obtener: "
    "identificadores descubiertos que quedaron sin explotar, herramientas que no se "
    "pudieron ejecutar por falta de datos y que ahora sí son viables, o variantes de "
    "alias plausibles a partir del nombre real.\n"
    "- No pidas una herramienta con los mismos argumentos con los que ya se ejecutó.\n"
    "- Si el barrido ya es suficiente, dilo y no pidas nada. Quedarte corto es "
    "preferible a añadir ruido al expediente de una persona concreta.\n"
    "- Solo fuentes públicas. Nunca inventes hallazgos: únicamente pides herramientas."
)


@dataclass
class HybridRun:
    """Resultado de una ejecución híbrida, con la contabilidad de cada capa."""

    entities: List[Entity] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


class HybridEngine:
    """Motor de dos capas: reglas primero, IA como refinamiento acotado."""

    async def execute_investigation(
        self,
        investigation_id: str,
        target: Target,
        db: AsyncSession,
    ) -> HybridRun:
        start_time = time.time()

        await event_bus.publish(investigation_id, {
            "type": "log",
            "phase": "hybrid_start",
            "layer": HEURISTIC_LAYER,
            "message": (
                "Motor HÍBRIDO activado. Capa 1/2: barrido heurístico determinista; "
                "Capa 2/2: refinamiento por IA sobre lo que quede sin cubrir."
            ),
            "timestamp": time.time(),
        })

        # --- Capa 1: barrido heurístico ------------------------------------
        sweep = await rule_engine.collect_findings(
            investigation_id,
            target,
            db,
            trace_engine="hybrid",
            trace_layer=HEURISTIC_LAYER,
        )
        for f in sweep.findings:
            f.metadata_info["engine_layer"] = HEURISTIC_LAYER

        heuristic_count = len(sweep.findings)
        await event_bus.publish(investigation_id, {
            "type": "log",
            "phase": "hybrid_layer1_complete",
            "layer": HEURISTIC_LAYER,
            "message": (
                f"Capa 1/2 completada: {heuristic_count} hallazgos en bruto tras "
                f"{sweep.rounds} ronda(s) heurística(s)."
            ),
            "timestamp": time.time(),
        })

        # --- Capa 2: refinamiento por IA -----------------------------------
        refinement_findings: List[ToolFinding] = []
        refinement_observations: List[PendingObservation] = []
        turns_used = 0
        calls_requested = 0
        calls_skipped = 0
        degraded = not settings.ai_enabled

        if degraded:
            await event_bus.publish(investigation_id, {
                "type": "log",
                "phase": "hybrid_degraded",
                # Sin `layer` a propósito: es un aviso del motor, no un evento de
                # la capa 2. Etiquetarlo como refinamiento haría que la consola
                # encendiera el distintivo de dos capas en una corrida que solo
                # tuvo una, y la leyenda diría lo contrario del mensaje.
                "message": (
                    "Capa 2/2 omitida: no hay LLM configurado (LLM_MODEL/LLM_API_KEY). "
                    "La investigación se completa solo con el motor de reglas y así "
                    "queda registrada en las métricas, sin atribuirla al híbrido."
                ),
                "timestamp": time.time(),
            })
        else:
            (
                refinement_findings,
                turns_used,
                calls_requested,
                calls_skipped,
            ) = await self._refine_with_llm(
                investigation_id,
                target,
                sweep,
                db=db,
                observations=refinement_observations,
            )

        # --- Persistencia única de ambas capas -----------------------------
        all_findings = list(sweep.findings) + refinement_findings
        entities = await persist_findings(
            investigation_id=investigation_id,
            findings=all_findings,
            target=target,
            db=db,
            default_source_tool="hybrid_engine",
        )
        await trace_recorder.link_observations(
            db,
            investigation_id=investigation_id,
            pending=[*sweep.observations, *refinement_observations],
            entities=entities,
        )
        await build_relationships(investigation_id, entities, db)

        # Cuántas entidades finales existen únicamente gracias a la capa 2. Es la
        # cifra que responde "¿aporta algo el refinamiento?", que es la pregunta
        # que el artículo le hace a esta estrategia.
        exclusive = sum(
            1
            for e in entities
            if (e.metadata_info or {}).get("engine_layers") == [REFINEMENT_LAYER]
        )

        elapsed = round(time.time() - start_time, 2)
        await event_bus.publish(investigation_id, {
            "type": "log",
            "phase": "complete",
            "layer": HEURISTIC_LAYER if degraded else REFINEMENT_LAYER,
            "message": (
                f"Motor híbrido finalizado en {elapsed}s: {len(entities)} entidades "
                f"({heuristic_count} hallazgos heurísticos + {len(refinement_findings)} "
                f"de refinamiento IA; {exclusive} entidad(es) aportada(s) en exclusiva por la IA)."
            ),
            "timestamp": time.time(),
        })

        return HybridRun(
            entities=entities,
            stats={
                "hybrid_degraded": degraded,
                "hybrid_heuristic_rounds": sweep.rounds,
                "hybrid_heuristic_findings": heuristic_count,
                "hybrid_refinement_findings": len(refinement_findings),
                "hybrid_refinement_turns": turns_used,
                "hybrid_refinement_calls": calls_requested,
                "hybrid_refinement_calls_skipped": calls_skipped,
                "hybrid_entities_only_from_llm": exclusive,
            },
        )

    # -- Interno -----------------------------------------------------------

    async def _refine_with_llm(
        self,
        investigation_id: str,
        target: Target,
        sweep: SweepResult,
        *,
        db: AsyncSession | None = None,
        observations: List[PendingObservation] | None = None,
    ) -> Tuple[List[ToolFinding], int, int, int]:
        """
        Pide al LLM llamadas que cubran los huecos del barrido heurístico.

        Devuelve `(hallazgos, turnos usados, llamadas pedidas, llamadas descartadas)`.
        """
        findings: List[ToolFinding] = []
        executed: Set[str] = set(sweep.executed_runs)
        turns_used = 0
        requested = 0
        skipped = 0
        trace_observations = observations if observations is not None else []

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": REFINEMENT_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_digest(target, sweep)},
        ]

        await event_bus.publish(investigation_id, {
            "type": "log",
            "phase": "hybrid_refine_start",
            "layer": REFINEMENT_LAYER,
            "message": (
                f"Capa 2/2: entregando al modelo [{settings.llm_model}] el resumen del "
                f"barrido para que proponga solo lo que falta."
            ),
            "timestamp": time.time(),
        })
        if db:
            await trace_recorder.record_event(
                db,
                investigation_id=investigation_id,
                event_type="refinement_start",
                engine="hybrid",
                engine_layer=REFINEMENT_LAYER,
            )

        for _ in range(max(1, settings.hybrid_max_refinement_turns)):
            turns_used += 1
            if db:
                await trace_recorder.record_event(
                    db,
                    investigation_id=investigation_id,
                    event_type="turn_start",
                    engine="hybrid",
                    engine_layer=REFINEMENT_LAYER,
                    turn_index=turns_used,
                )
            try:
                response = await complete_with_retries(
                    model=settings.llm_model,
                    api_key=settings.llm_api_key,
                    messages=messages,
                    tools=build_tool_schemas(),
                    temperature=0.2,
                    on_retry=lambda attempt, delay, err: event_bus.publish(investigation_id, {
                        "type": "log",
                        "phase": "hybrid_refine_retry",
                        "layer": REFINEMENT_LAYER,
                        "message": (
                            f"Capa 2/2 en espera: {describe_llm_error(err)}. "
                            f"Reintento {attempt} en {delay:.0f} s..."
                        ),
                        "timestamp": time.time(),
                    }),
                )
            except Exception as err:
                # El refinamiento es opcional por diseño: si el proveedor falla,
                # la investigación conserva íntegro el resultado de la capa 1.
                await event_bus.publish(investigation_id, {
                    "type": "log",
                    "phase": "hybrid_refine_error",
                    "layer": REFINEMENT_LAYER,
                    "message": (
                        f"Capa 2/2 interrumpida ({describe_llm_error(err)}). Se conserva "
                        f"el resultado completo del barrido heurístico."
                    ),
                    "timestamp": time.time(),
                })
                break

            msg = response.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)

            assistant_msg: Dict[str, Any] = {"role": "assistant"}
            if getattr(msg, "content", None):
                assistant_msg["content"] = msg.content
                await event_bus.publish(investigation_id, {
                    "type": "log",
                    "phase": "hybrid_refine_reasoning",
                    "layer": REFINEMENT_LAYER,
                    "message": f"Refinamiento IA: {str(msg.content)[:180]}",
                    "timestamp": time.time(),
                })
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if not tool_calls:
                await event_bus.publish(investigation_id, {
                    "type": "log",
                    "phase": "hybrid_refine_concluded",
                    "layer": REFINEMENT_LAYER,
                    "message": "El refinamiento IA no encontró huecos que cubrir. Cerrando capa 2/2.",
                    "timestamp": time.time(),
                })
                break

            for tc in tool_calls:
                requested += 1
                fn_name = tc.function.name
                try:
                    args = (
                        json.loads(tc.function.arguments)
                        if isinstance(tc.function.arguments, str)
                        else dict(tc.function.arguments or {})
                    )
                except (json.JSONDecodeError, TypeError, ValueError):
                    args = {}

                run_key = self._run_key(fn_name, args, sweep.context)
                if run_key in executed:
                    # Esto es lo que separa al híbrido del agente autónomo: la
                    # capa 2 no puede volver a gastar red en una combinación que
                    # la capa 1 ya cubrió.
                    skipped += 1
                    await event_bus.publish(investigation_id, {
                        "type": "log",
                        "phase": "hybrid_refine_skipped",
                        "layer": REFINEMENT_LAYER,
                        "message": (
                            f"Descartada la llamada [{fn_name}] {args}: el barrido "
                            f"heurístico ya ejecutó esa combinación."
                        ),
                        "timestamp": time.time(),
                    })
                    if db:
                        await trace_recorder.record_event(
                            db,
                            investigation_id=investigation_id,
                            event_type="skipped_call",
                            engine="hybrid",
                            engine_layer=REFINEMENT_LAYER,
                            turn_index=turns_used,
                            data={"tool_name": resolve_tool_name(fn_name), "reason": "already_executed"},
                        )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({
                            "skipped": True,
                            "reason": "already_executed_by_heuristic_sweep",
                        }),
                    })
                    continue

                executed.add(run_key)
                trace_execution = None
                if db:
                    tool = tool_registry.get_tool(resolve_tool_name(fn_name))
                    if tool:
                        trace_execution = await trace_recorder.start_tool(
                            db,
                            investigation_id=investigation_id,
                            tool=tool,
                            engine="hybrid",
                            engine_layer=REFINEMENT_LAYER,
                            turn_index=turns_used,
                            context=sweep.context,
                        )

                started_at = time.perf_counter()
                await event_bus.publish(investigation_id, {
                    "type": "tool_start",
                    "phase": "hybrid_refine_dispatch",
                    "layer": REFINEMENT_LAYER,
                    "tool": resolve_tool_name(fn_name),
                    "tool_execution_id": str(trace_execution.id) if trace_execution else None,
                    "message": f"Refinamiento IA invocó [{fn_name}].",
                    "timestamp": time.time(),
                })

                try:
                    new_findings = await dispatch_tool_call(
                        fn_name,
                        args,
                        target,
                        base_context=sweep.context,
                        engine_layer=REFINEMENT_LAYER,
                    )
                except Exception as err:
                    new_findings = []
                    duration_seconds = round(time.perf_counter() - started_at, 3)
                    await event_bus.publish(investigation_id, {
                        "type": "tool_error",
                        "tool": resolve_tool_name(fn_name),
                        "layer": REFINEMENT_LAYER,
                        "tool_execution_id": str(trace_execution.id) if trace_execution else None,
                        "error": str(err),
                        "duration_seconds": duration_seconds,
                        "message": f"[{fn_name}] error en refinamiento: {err}",
                        "timestamp": time.time(),
                    })
                    if trace_execution:
                        await trace_recorder.complete_tool(trace_execution, findings_count=0, error=err)
                else:
                    duration_seconds = round(time.perf_counter() - started_at, 3)
                    await event_bus.publish(investigation_id, {
                        "type": "tool_complete",
                        "tool": resolve_tool_name(fn_name),
                        "layer": REFINEMENT_LAYER,
                        "tool_execution_id": str(trace_execution.id) if trace_execution else None,
                        "findings_count": len(new_findings),
                        "duration_seconds": duration_seconds,
                        "message": f"[{fn_name}] refinamiento: {len(new_findings)} hallazgos · {duration_seconds:.1f} s.",
                        "timestamp": time.time(),
                    })
                    if trace_execution:
                        await trace_recorder.complete_tool(
                            trace_execution,
                            findings_count=len(new_findings),
                        )
                        observed_at = trace_execution.completed_at
                        if observed_at:
                            trace_observations.extend(
                                PendingObservation(
                                    finding=finding,
                                    tool_execution_id=trace_execution.id,
                                    observed_at=observed_at,
                                )
                                for finding in new_findings
                            )

                findings.extend(new_findings)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({
                        "findings_count": len(new_findings),
                        "sample": [
                            {"platform": f.platform, "value": f.value, "confidence": f.confidence}
                            for f in new_findings[:10]
                        ],
                    }),
                })

            if db:
                await trace_recorder.record_event(
                    db,
                    investigation_id=investigation_id,
                    event_type="turn_complete",
                    engine="hybrid",
                    engine_layer=REFINEMENT_LAYER,
                    turn_index=turns_used,
                )

        return findings, turns_used, requested, skipped

    def _run_key(self, fn_name: str, args: Dict[str, Any], context: TargetContext) -> str:
        """
        Clave de ejecución comparable con las que registró el barrido heurístico.

        Reutiliza `RuleEngine._get_tool_run_key` sobre un contexto construido con
        los argumentos que pide el modelo, de modo que "username_finder sobre
        jperez" produzca la misma clave la pida quien la pida.
        """
        tool = tool_registry.get_tool(resolve_tool_name(fn_name))
        if not tool:
            return f"unknown:{fn_name}"

        merged = TargetContext(
            full_name=args.get("full_name") or context.full_name,
            email=args.get("email") or context.email,
            username=args.get("username") or context.username,
            phone=args.get("phone") or context.phone,
            dni=args.get("dni") or context.dni,
            university=args.get("university") or context.university,
            discovered_emails=list(context.discovered_emails),
            discovered_usernames=list(context.discovered_usernames),
            extra=dict(context.extra),
        )
        return rule_engine._get_tool_run_key(tool, merged)

    def _build_digest(self, target: Target, sweep: SweepResult) -> str:
        """
        Resumen compacto de la capa 1 para el modelo.

        Se envían agregados (cuántos hallazgos por tipo, qué identificadores se
        descubrieron, qué herramientas ya corrieron y cuáles no) en lugar del
        volcado de hallazgos: el objetivo es que el LLM decida dónde falta mirar,
        y un volcado de cientos de perfiles gastaría el contexto sin mejorar esa
        decisión.
        """
        by_type: Dict[str, int] = {}
        platforms: Set[str] = set()
        for f in sweep.findings:
            by_type[f.entity_type] = by_type.get(f.entity_type, 0) + 1
            if f.platform:
                platforms.add(f.platform)

        ctx = sweep.context or TargetContext()
        executed_tools = sorted({key.split("|", 1)[0] for key in sweep.executed_runs})
        not_run = sorted(
            t.name for t in tool_registry.get_all() if t.name not in executed_tools
        )
        top_platforms = sorted(platforms)[:40]

        return (
            f"OBJETIVO\n"
            f"- Nombre: {target.full_name or 'N/A'}\n"
            f"- Correo: {target.email or 'N/A'}\n"
            f"- Alias: {target.username or 'N/A'}\n"
            f"- Teléfono: {target.phone or 'N/A'}\n"
            f"- Universidad: {target.university or 'N/A'}\n"
            f"- Contexto: {target.description or 'Ninguno'}\n\n"
            f"RESULTADO DEL BARRIDO HEURÍSTICO ({sweep.rounds} ronda(s))\n"
            f"- Hallazgos por tipo: {json.dumps(by_type, ensure_ascii=False)}\n"
            f"- Plataformas con presencia detectada: {', '.join(top_platforms) or 'ninguna'}\n"
            f"- Correos conocidos tras pivotar: {', '.join(ctx.all_emails()) or 'ninguno'}\n"
            f"- Alias conocidos tras pivotar: {', '.join(ctx.all_usernames()) or 'ninguno'}\n"
            f"- Nombres descubiertos: {', '.join(ctx.discovered_names) or 'ninguno'}\n"
            f"- URLs candidatas recogidas: {len(ctx.extra.get('candidate_urls', []))}\n\n"
            f"HERRAMIENTAS YA EJECUTADAS (no las repitas con los mismos datos)\n"
            f"{', '.join(executed_tools) or 'ninguna'}\n\n"
            f"HERRAMIENTAS QUE NO LLEGARON A EJECUTARSE\n"
            f"{', '.join(not_run) or 'ninguna'}\n\n"
            f"Propón únicamente las llamadas que cubran huecos reales. Si no hay "
            f"ninguna que merezca la pena, respóndelo en texto y no pidas herramientas."
        )


hybrid_engine = HybridEngine()
