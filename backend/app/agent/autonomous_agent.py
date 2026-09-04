import json
import time
from typing import Any, Dict, List, Optional
import litellm
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.events import event_bus
from app.identity.scorer import compute_identity_score
from app.models.entity import Entity
from app.models.relationship import Relationship
from app.models.target import Target
from app.tools.base import TargetContext, ToolFinding
from app.tools.registry import tool_registry


def _build_agent_tools() -> List[Dict[str, Any]]:
    """
    Builds the LiteLLM function-calling schema dynamically from the live ToolRegistry.

    Previously this was a hardcoded list of 7 entries that covered only half of the
    registered tools, making the agentic mode objectively weaker than the heuristic
    mode. By generating the schema from tool_registry.get_all() every tool that is
    registered — including future tools — is automatically visible to the LLM without
    any manual synchronization step. This fixes P0#4 from ANALISIS_OSINT_MUNDIAL.md.
    """
    schemas: List[Dict[str, Any]] = []
    for tool in tool_registry.get_all():
        # Map required_inputs (TargetContext field names) to LLM-friendly parameter
        # descriptions. We keep it simple: each required field becomes a string param.
        properties: Dict[str, Any] = {}
        for field in tool.required_inputs:
            properties[field] = {
                "type": "string",
                "description": field.replace("_", " ").capitalize(),
            }

        schemas.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": [tool.required_inputs[0]] if tool.required_inputs else [],
                },
            },
        })
    return schemas


# Built once at import time; reflects ALL registered tools including reverse_image_search,
# email_enumerator, gravatar_deep, keybase_resolver, wikipedia_edits, dni_lookup,
# social_url_extractor, google_account_osint — all of which were previously invisible to
# the LLM when AGENT_TOOLS was a static list of 7 entries.
AGENT_TOOLS = _build_agent_tools()


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

        # Persist all discovered entities into PostgreSQL
        entities: List[Entity] = []
        for f in all_findings:
            score, breakdown = compute_identity_score(
                display_name=f.display_name,
                value=f.value,
                metadata=f.metadata_info,
                target=target,
            )
            final_conf = round(max(f.confidence, score), 2)

            entity = Entity(
                investigation_id=investigation_id,
                entity_type=f.entity_type,
                platform=f.platform,
                value=f.value,
                display_name=f.display_name or f.value,
                metadata_info=f.metadata_info,
                confidence=final_conf,
                verified=False,
                source_tool=f.metadata_info.get("source_tool", "agent_autonomous"),
            )
            db.add(entity)
            entities.append(entity)

        await db.flush()

        # Build relationships between entities (graph edges)
        for i, ent_a in enumerate(entities):
            for ent_b in entities[i + 1 :]:
                if ent_a.platform == ent_b.platform:
                    rel = Relationship(
                        investigation_id=investigation_id,
                        source_entity_id=ent_a.id,
                        target_entity_id=ent_b.id,
                        relation_type="same_platform",
                        strength=0.5,
                    )
                    db.add(rel)
                elif ent_a.entity_type == "email" and ent_b.metadata_info.get("emails"):
                    if ent_a.value.lower() in [e.lower() for e in ent_b.metadata_info["emails"]]:
                        rel = Relationship(
                            investigation_id=investigation_id,
                            source_entity_id=ent_a.id,
                            target_entity_id=ent_b.id,
                            relation_type="uses_email",
                            strength=0.95,
                        )
                        db.add(rel)

        await db.flush()
        return entities

    async def _execute_agent_tool(
        self,
        name: str,
        args: Dict[str, Any],
        target: Target,
    ) -> List[ToolFinding]:
        # Since AGENT_TOOLS now uses real tool names from the registry (not aliases
        # like "check_username" → "username_finder"), we resolve directly.
        # We keep a small backwards-compat alias map only for the old hardcoded names
        # in case a model trained on previous prompts still emits them.
        _legacy_alias: Dict[str, str] = {
            "check_username": "username_finder",
            "check_email": "email_checker",
            "check_breaches": "breach_checker",
            "lookup_phone": "phone_lookup",
            "search_academic": "academic_finder",
            "deep_scan_github": "github_deep_scanner",
            "verify_profile": "social_verifier",
        }
        tool_id = _legacy_alias.get(name, name)
        tool = tool_registry.get_tool(tool_id)
        if not tool:
            return []

        # Build TargetContext from whatever the LLM passed in args, with the
        # investigation target's known fields as fallback.
        candidate_urls: List[str] = []
        if "url" in args:
            candidate_urls.append(args["url"])

        ctx = TargetContext(
            full_name=args.get("full_name") or target.full_name,
            email=args.get("email") or target.email,
            username=args.get("username") or target.username,
            phone=args.get("phone") or target.phone,
            dni=args.get("dni") or target.dni,
            university=args.get("university") or target.university,
            description=target.description,
            extra={"candidate_urls": candidate_urls},
        )

        findings = await tool.execute(ctx)
        for f in findings:
            f.metadata_info["source_tool"] = f"agent:{tool_id}"
        return findings


autonomous_agent = AutonomousOSINTAgent()
