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

                    await event_bus.publish(investigation_id, {
                        "type": "log",
                        "phase": "agent_tool_dispatch",
                        "message": f"IA invocó [{fn_name}] con argumentos: {args}",
                        "timestamp": time.time(),
                    })

                    tool_findings = await self._execute_agent_tool(
                        investigation_id, fn_name, args, target
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
            all_findings.extend(
                await self._heuristic_fallback(investigation_id, target, tools_executed, llm_error)
            )

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
    ) -> List[ToolFinding]:
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
        sweep = await rule_engine.collect_findings(investigation_id, target)
        return sweep.findings

    async def _execute_agent_tool(
        self,
        investigation_id: str,
        name: str,
        args: Dict[str, Any],
        target: Target,
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
        try:
            findings = await dispatch_tool_call(
                name,
                args,
                target,
                source_prefix="agent",
                investigation_id=investigation_id,
            )
        except Exception as err:
            await event_bus.publish(investigation_id, {
                "type": "tool_error",
                "tool": tool_name,
                "error": str(err),
                "message": f"[{tool_name}] error: {err}",
                "timestamp": time.time(),
            })
            return []

        await event_bus.publish(investigation_id, {
            "type": "tool_complete",
            "tool": tool_name,
            "findings_count": len(findings),
            "message": f"[{tool_name}] completado: {len(findings)} hallazgos.",
            "timestamp": time.time(),
        })
        return findings


autonomous_agent = AutonomousOSINTAgent()
