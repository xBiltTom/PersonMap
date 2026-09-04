import json
import time
from typing import Any, Dict, List
import litellm
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.events import event_bus
from app.agent.tool_dispatch import build_tool_schemas, dispatch_tool_call
from app.engine.persistence import build_relationships, persist_findings
from app.models.entity import Entity
from app.models.target import Target
from app.tools.base import ToolFinding


# Construido una vez al importar; refleja TODAS las herramientas registradas.
# La construcción vive ahora en app.agent.tool_dispatch, compartida con la capa
# de refinamiento del motor híbrido.
AGENT_TOOLS = build_tool_schemas()


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
    ) -> List[Entity]:
        if not settings.ai_enabled:
            # Fall back to rule engine if no LLM configured
            from app.engine.rule_engine import rule_engine
            return await rule_engine.execute_investigation(investigation_id, target, db)

        all_findings: List[ToolFinding] = []
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

        for turn in range(1, self.MAX_TURNS + 1):
            try:
                response = await litellm.acompletion(
                    model=settings.llm_model,
                    api_key=settings.llm_api_key,
                    messages=messages,
                    tools=AGENT_TOOLS,
                    temperature=0.2,
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

                    tool_findings = await self._execute_agent_tool(fn_name, args, target)
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
                await event_bus.publish(investigation_id, {
                    "type": "log",
                    "phase": "agent_error",
                    "message": f"Aviso: Fallo en turno del agente ({err}). Aplicando motor heurístico complementario...",
                    "timestamp": time.time(),
                })
                break

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

        return entities

    async def _execute_agent_tool(
        self,
        name: str,
        args: Dict[str, Any],
        target: Target,
    ) -> List[ToolFinding]:
        """
        Delega en el despachador compartido, conservando el prefijo `agent:` de
        `source_tool` para no romper la trazabilidad de los expedientes ya
        guardados.
        """
        return await dispatch_tool_call(
            name,
            args,
            target,
            source_prefix="agent",
            engine_layer="agentic",
        )


autonomous_agent = AutonomousOSINTAgent()
