"""
Despacho de llamadas a herramientas pedidas por un LLM.

Dos motores necesitan traducir una *function call* del modelo en la ejecución
real de una `BaseTool`: el agente autónomo (`agentic`) y la capa de
refinamiento del motor híbrido (`hybrid`). Antes esa traducción vivía como
método privado del agente; al necesitarla también el híbrido se extrae aquí,
de modo que ambos compartan el mismo esquema de funciones, el mismo mapa de
alias heredados y la misma construcción de `TargetContext`.

Se unifica el **dato** (cómo se ejecuta una herramienta y cómo se etiqueta su
procedencia), no el **control**: cada motor conserva su propio bucle de
decisión, que es justo lo que los hace comparables como condiciones
experimentales independientes en el artículo.
"""

from typing import Any, Dict, List, Optional

from app.models.target import Target
from app.tools.base import TargetContext, ToolFinding
from app.tools.registry import tool_registry

# Nombres que emitía la lista estática de 7 entradas anterior a P0#4. Un modelo
# que haya visto aquellos prompts todavía puede pedirlos.
LEGACY_ALIASES: Dict[str, str] = {
    "check_username": "username_finder",
    "check_email": "email_checker",
    "check_breaches": "breach_checker",
    "lookup_phone": "phone_lookup",
    "search_academic": "academic_finder",
    "deep_scan_github": "github_deep_scanner",
    "verify_profile": "social_verifier",
}


def build_tool_schemas() -> List[Dict[str, Any]]:
    """
    Construye el esquema de function calling de LiteLLM desde el `ToolRegistry` vivo.

    Antes era una lista fija de 7 entradas que cubría la mitad de las
    herramientas registradas, lo que hacía el modo agéntico objetivamente más
    débil que el heurístico. Al generarlo desde `tool_registry.get_all()`, toda
    herramienta registrada -- incluidas las futuras -- es automáticamente
    visible para el LLM sin ningún paso de sincronización manual.
    """
    schemas: List[Dict[str, Any]] = []
    for tool in tool_registry.get_all():
        properties: Dict[str, Any] = {
            field: {
                "type": "string",
                "description": field.replace("_", " ").capitalize(),
            }
            for field in tool.required_inputs
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


def resolve_tool_name(name: str) -> str:
    """Nombre real en el registry para lo que haya pedido el modelo."""
    return LEGACY_ALIASES.get(name, name)


def build_call_context(
    args: Dict[str, Any],
    target: Target,
    base_context: Optional[TargetContext] = None,
) -> TargetContext:
    """
    Contexto de una llamada concreta: lo que pide el LLM manda, y por debajo
    quedan los identificadores conocidos.

    `base_context` permite al motor híbrido arrastrar lo que ya descubrió la
    pasada heurística (correos, alias y URLs candidatas obtenidos al pivotar).
    Sin él, la capa de refinamiento arrancaría ciega sobre los datos iniciales y
    repetiría trabajo ya hecho en lugar de continuarlo.
    """
    candidate_urls: List[str] = []
    if base_context:
        candidate_urls.extend(
            str(u) for u in base_context.extra.get("candidate_urls", [])
        )
    if args.get("url"):
        candidate_urls.append(str(args["url"]))

    base = base_context or TargetContext()
    return TargetContext(
        full_name=args.get("full_name") or base.full_name or target.full_name,
        email=args.get("email") or base.email or target.email,
        username=args.get("username") or base.username or target.username,
        phone=args.get("phone") or base.phone or target.phone,
        dni=args.get("dni") or base.dni or target.dni,
        university=args.get("university") or base.university or target.university,
        description=target.description,
        discovered_emails=list(base.discovered_emails),
        discovered_usernames=list(base.discovered_usernames),
        discovered_names=list(base.discovered_names),
        extra={**dict(base.extra), "candidate_urls": candidate_urls},
    )


async def dispatch_tool_call(
    name: str,
    args: Dict[str, Any],
    target: Target,
    *,
    base_context: Optional[TargetContext] = None,
    source_prefix: Optional[str] = None,
    engine_layer: Optional[str] = None,
) -> List[ToolFinding]:
    """
    Ejecuta la herramienta que pidió el modelo y etiqueta la procedencia.

    `source_prefix` antepone un prefijo a `source_tool` (el agente usa `agent:`
    por compatibilidad con los expedientes ya guardados). `engine_layer` marca
    en qué capa del motor nació el hallazgo, que es lo que permite a la interfaz
    distinguir la cosecha heurística del refinamiento por IA.
    """
    tool = tool_registry.get_tool(resolve_tool_name(name))
    if not tool:
        return []

    ctx = build_call_context(args, target, base_context)
    findings = await tool.execute(ctx)

    for f in findings:
        f.metadata_info["source_tool"] = (
            f"{source_prefix}:{tool.name}" if source_prefix else tool.name
        )
        if engine_layer:
            f.metadata_info["engine_layer"] = engine_layer
    return findings
