import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.events import event_bus
from app.agent.llm_client import complete_with_retries, describe_llm_error
from app.agent.tool_dispatch import build_tool_schemas, dispatch_tool_call, resolve_tool_name
from app.engine.persistence import build_relationships, persist_findings
from app.engine.trace import PendingObservation, trace_recorder
from app.models.entity import Entity
from app.models.target import Target
from app.tools.base import ToolFinding


# Construido una vez al importar; refleja TODAS las herramientas registradas.
# La construcción vive ahora en app.agent.tool_dispatch, compartida con la capa
# de refinamiento del motor híbrido.
AGENT_TOOLS = build_tool_schemas()


@dataclass
class AgentRun:
    """Entidades persistidas y lo que pasó con el LLM, para las métricas."""

    entities: List[Entity]
    stats: Dict[str, Any] = field(default_factory=dict)


class AutonomousOSINTAgent:
    """
    Autonomous multi-turn agent that plans, dispatches tools via function calling,
    evaluates findings, pivots, and reconstructs identity.
    """

    MAX_TURNS = 5

    async def run(
        self,
        investigation_id: str,
        target: Target,
        db: AsyncSession,
    ) -> AgentRun:
        if not settings.ai_enabled:
            # Fall back to rule engine if no LLM configured
            from app.engine.rule_engine import rule_engine
            entities = await rule_engine.execute_investigation(investigation_id, target, db)
            return AgentRun(entities, {"agent_fallback_to_rules": True, "agent_tools_executed": 0})

        all_findings: List[ToolFinding] = []
        trace_observations: List[PendingObservation] = []
        turns = 0
        tools_executed = 0
        llm_error: Optional[str] = None
        messages: List[Dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Eres un Agente Investigador OSINT Autónomo. Tu misión es reconstruir la huella digital "
                    "pública del objetivo y evaluar su exposición para concientización en ciberseguridad. "
                    "Tienes acceso a herramientas especializadas. Analiza los identificadores iniciales y la descripción. "
                    "Llama a las herramientas más prometedoras, analiza las respuestas, pivotea si encuentras nuevos correos "
                    "o alias, y cuando tengas suficiente información o no haya más pistas, concluye."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Objetivo a investigar:\n"
                    f"- Nombre: {target.full_name or 'N/A'}\n"
                    f"- Correo: {target.email or 'N/A'}\n"
                    f"- Alias: {target.username or 'N/A'}\n"
                    f"- Teléfono: {target.phone or 'N/A'}\n"
                    f"- DNI: {target.dni or 'N/A'}\n"
                    f"- Universidad: {target.university or 'N/A'}\n"
                    f"- Descripción de contexto: {target.description or 'Ninguna'}\n\n"
                    "Inicia la planificación y ejecuta las primeras herramientas."
                ),
            },
        ]

        await event_bus.publish(investigation_id, {
            "type": "log",
            "phase": "agent_start",
            "message": f"Agente Autónomo IA iniciado con modelo [{settings.llm_model}]. Formulando plan de ataque...",
            "timestamp": time.time(),
        })
        if db:
            await trace_recorder.record_event(
                db,
                investigation_id=investigation_id,
                event_type="engine_start",
                engine="agentic",
                engine_layer="agentic",
            )

        async def announce_retry(attempt: int, delay: float, err: BaseException) -> None:
            await event_bus.publish(investigation_id, {
                "type": "log",
                "phase": "agent_retry",
                "message": (
                    f"IA no disponible: {describe_llm_error(err)}. "
                    f"Reintento {attempt} en {delay:.0f} s..."
                ),
                "timestamp": time.time(),
            })

        for turn in range(1, self.MAX_TURNS + 1):
            turns = turn
            if db:
                await trace_recorder.record_event(
                    db,
                    investigation_id=investigation_id,
                    event_type="turn_start",
                    engine="agentic",
                    engine_layer="agentic",
                    turn_index=turn,
                )
            try:
                response = await complete_with_retries(
                    model=settings.llm_model,
                    api_key=settings.llm_api_key,
                    messages=messages,
                    tools=AGENT_TOOLS,
                    temperature=0.2,
                    on_retry=announce_retry,
                )
                msg = response.choices[0].message
                tool_calls = getattr(msg, "tool_calls", None)

                # Append assistant message
                assistant_msg = {"role": "assistant"}
                if msg.content:
                    assistant_msg["content"] = msg.content
                    await event_bus.publish(investigation_id, {
                        "type": "log",
                        "phase": "agent_reasoning",
                        "message": f"Razonamiento IA: {msg.content[:140]}...",
                        "timestamp": time.time(),
                    })
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls

                messages.append(assistant_msg)

                if not tool_calls:
                    # Agent completed its investigation plan
                    await event_bus.publish(investigation_id, {
                        "type": "log",
                        "phase": "agent_concluded",
                        "message": "El Agente IA ha determinado que dispone de suficiente inteligencia. Finalizando...",
                        "timestamp": time.time(),
                    })
                    break

                # Execute requested tools
                for tc in tool_calls:
                    fn_name = tc.function.name
                    args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments

                    tool_findings = await self._execute_agent_tool(
                        investigation_id,
                        fn_name,
                        args,
                        target,
                        db=db,
                        turn_index=turn,
                        observations=trace_observations,
                    )
                    tools_executed += 1
                    all_findings.extend(tool_findings)

                    # Return result to LLM
                    summary_result = [
                        {"platform": f.platform, "value": f.value, "confidence": f.confidence}
                        for f in tool_findings[:10]
                    ]
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({"findings_count": len(tool_findings), "sample": summary_result}),
                    })

                if db:
                    await trace_recorder.record_event(
                        db,
                        investigation_id=investigation_id,
                        event_type="turn_complete",
                        engine="agentic",
                        engine_layer="agentic",
                        turn_index=turn,
                    )

            except Exception as err:
                llm_error = describe_llm_error(err)
                await event_bus.publish(investigation_id, {
                    "type": "log",
                    "phase": "agent_error",
                    "message": f"El agente IA no puede continuar: {llm_error}.",
                    "timestamp": time.time(),
                })
                break

        if llm_error is not None:
            fallback = await self._heuristic_fallback(
                investigation_id,
                target,
                tools_executed,
                llm_error,
                db=db,
            )
            all_findings.extend(fallback.findings)
            trace_observations.extend(fallback.observations)

        # Deduplicación, scoring y persistencia compartidos con el motor de reglas.
        # Antes esto estaba duplicado aquí en una versión degradada: sin
        # deduplicación (el agente puede invocar la misma tool en varios turnos y
        # generaba entidades repetidas) y con una detección de relaciones reducida
        # a same_platform/uses_email. Al delegar en app.engine.persistence el modo
        # agéntico hereda exactamente el mismo comportamiento que el heurístico.
        entities = await persist_findings(
            investigation_id=investigation_id,
            findings=all_findings,
            target=target,
            db=db,
            default_source_tool="agent_autonomous",
        )
        if db:
            await trace_recorder.link_observations(
                db,
                investigation_id=investigation_id,
                pending=trace_observations,
                entities=entities,
            )
        await build_relationships(investigation_id, entities, db)

        return AgentRun(
            entities=entities,
            stats={
                "agent_turns": turns,
                "agent_tools_executed": tools_executed,
                "agent_llm_error": llm_error,
                "agent_fallback_to_rules": llm_error is not None,
            },
        )

    async def _heuristic_fallback(
        self,
        investigation_id: str,
        target: Target,
        tools_executed: int,
        reason: str,
        db: AsyncSession | None = None,
    ):
        """
        Barrido heurístico completo cuando el LLM deja de responder.

        Antes el aviso decía "Aplicando motor heurístico complementario..." pero
        no aplicaba nada. Con un 503 de Gemini en el primer turno (investigación
        c79b9d92, 2026-09-10) la búsqueda terminó sin ejecutar una sola
        herramienta: 0 hallazgos, riesgo BAJO y la recomendación "Huella Digital
        Controlada". Un informe que le dice a alguien que casi no tiene huella
        solo porque el proveedor de IA estaba saturado.

        Devuelve los hallazgos sin persistir, para que la deduplicación los vea
        junto a los que el agente llegara a reunir antes del fallo.
        """
        from app.engine.rule_engine import rule_engine

        await event_bus.publish(investigation_id, {
            "type": "log",
            "phase": "agent_fallback",
            "message": (
                f"IA no disponible ({reason}) tras {tools_executed} herramienta(s) del agente. "
                "Se ejecuta el barrido heurístico completo para que la investigación no quede incompleta."
            ),
            "timestamp": time.time(),
        })
        if db:
            return await rule_engine.collect_findings(
                investigation_id,
                target,
                db,
                trace_engine="agentic",
                trace_layer="heuristic",
            )
        return await rule_engine.collect_findings(investigation_id, target)

    async def _execute_agent_tool(
        self,
        investigation_id: str,
        name: str,
        args: Dict[str, Any],
        target: Target,
        *,
        db: AsyncSession | None = None,
        turn_index: int | None = None,
        observations: List[PendingObservation] | None = None,
    ) -> List[ToolFinding]:
        """
        Delega en el despachador compartido, conservando el prefijo `agent:` de
        `source_tool` para no romper la trazabilidad de los expedientes ya
        guardados.

        No se etiqueta `engine_layer`: este motor tiene una sola capa, y "capa"
        significa exactamente "cuál de las dos mitades del motor híbrido". Su
        procedencia ya la lleva el prefijo `agent:` del `source_tool`, que la
        interfaz muestra.

        Publica el cierre de cada herramienta como hacen los otros dos motores:
        sin `tool_complete` la interfaz no puede contar cuántas terminaron. Y un
        fallo de UNA herramienta ya no tumba el turno entero del agente.
        """
        tool_name = resolve_tool_name(name)
        trace_execution = None
        if db:
            from app.tools.registry import tool_registry

            tool = tool_registry.get_tool(tool_name)
            if tool:
                trace_execution = await trace_recorder.start_tool(
                    db,
                    investigation_id=investigation_id,
                    tool=tool,
                    engine="agentic",
                    engine_layer="agentic",
                    turn_index=turn_index,
                )
        started_at = time.perf_counter()
        await event_bus.publish(investigation_id, {
            "type": "tool_start",
            "phase": "agent_tool_dispatch",
            "tool": tool_name,
            "layer": "agentic",
            "tool_execution_id": str(trace_execution.id) if trace_execution else None,
            "message": f"IA invocó [{tool_name}].",
            "timestamp": time.time(),
        })
        try:
            findings = await dispatch_tool_call(
                name,
                args,
                target,
                source_prefix="agent",
                investigation_id=investigation_id,
            )
        except Exception as err:
            duration_seconds = round(time.perf_counter() - started_at, 3)
            if trace_execution:
                await trace_recorder.complete_tool(trace_execution, findings_count=0, error=err)
            await event_bus.publish(investigation_id, {
                "type": "tool_error",
                "tool": tool_name,
                "layer": "agentic",
                "tool_execution_id": str(trace_execution.id) if trace_execution else None,
                "error": str(err),
                "duration_seconds": duration_seconds,
                "message": f"[{tool_name}] error: {err}",
                "timestamp": time.time(),
            })
            return []

        duration_seconds = round(time.perf_counter() - started_at, 3)
        await event_bus.publish(investigation_id, {
            "type": "tool_complete",
            "tool": tool_name,
            "layer": "agentic",
            "tool_execution_id": str(trace_execution.id) if trace_execution else None,
            "findings_count": len(findings),
            "duration_seconds": duration_seconds,
            "message": f"[{tool_name}] completado: {len(findings)} hallazgos · {duration_seconds:.1f} s.",
            "timestamp": time.time(),
        })
        if trace_execution:
            await trace_recorder.complete_tool(trace_execution, findings_count=len(findings))
            if observations is not None and trace_execution.completed_at:
                observations.extend(
                    PendingObservation(
                        finding=finding,
                        tool_execution_id=trace_execution.id,
                        observed_at=trace_execution.completed_at,
                    )
                    for finding in findings
                )
        return findings


autonomous_agent = AutonomousOSINTAgent()
