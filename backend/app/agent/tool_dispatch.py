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
        if "candidate_urls" in properties:
            properties["candidate_urls"] = {
                "type": "array", "items": {"type": "string"},
                "description": "URLs públicas candidatas de perfiles",
            }
        if "identifiers" in properties:
            from app.schemas.identifiers import TypedIdentifier
            properties["identifiers"] = {"type": "array", "items": TypedIdentifier.model_json_schema(),
                                         "maxItems": 30, "description": "Identificadores públicos con tipo explícito"}
        if tool.name in {"username_finder", "maigret_enricher"}:
            from app.schemas.workspace import MaigretOptions
            properties["maigret_options"] = MaigretOptions.model_json_schema()
        if tool.name == "username_finder":
            properties["scan_mode"] = {"type": "string", "enum": ["fast", "deep", "all"]}

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
    for schema in schemas:
        if schema["function"]["name"] in {"maigret_enricher", "ghunt", "academic_finder"}:
            parameters = schema["function"]["parameters"]
            parameters["required"] = []
            fields = (("email", "candidate_urls", "identifiers") if schema["function"]["name"] == "ghunt"
                else ("full_name", "candidate_urls", "identifiers") if schema["function"]["name"] == "academic_finder"
                else ("candidate_urls", "identifiers"))
            parameters["anyOf"] = [{"required": [field]} for field in fields]
            if schema["function"]["name"] == "academic_finder":
                parameters["properties"]["university"] = {"type": "string", "description": "Afiliación para contrastar en el autor correspondiente; no confirma identidad"}
        if schema["function"]["name"] == "search_dorker":
            from app.schemas.workspace import SearchQuery
            parameters = schema["function"]["parameters"]
            query_schema = SearchQuery.model_json_schema()
            parameters["properties"]["queries"] = {
                "type": "array", "minItems": 1, "maxItems": 5, "items": query_schema,
                "description": "Consultas propias: ancla literal entre comillas, justificación e include_domains; cada ancla independiente se exige en la evidencia. Alternativas en consultas separadas.",
            }
            parameters["properties"]["university"] = {"type": "string", "description": "Afiliación para contextualizar búsquedas"}
            parameters["required"] = []
            parameters["anyOf"] = [{"required": [field]} for field in ("full_name", "username", "email", "dni", "phone", "queries")]
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
    supplied_urls = args.get("candidate_urls", [])
    if isinstance(supplied_urls, str):
        supplied_urls = [supplied_urls]  # Compatibility with older calls.
    if isinstance(supplied_urls, list):
        candidate_urls.extend(u for u in supplied_urls if isinstance(u, str) and u.strip())
    candidate_urls = list(dict.fromkeys(candidate_urls))

    base = base_context or TargetContext.from_target(target)
    extra = dict(base.extra)
    if not base_context:
        from app.tools.maigret_ids import identifier_values
        extra["maigret_identifiers"] = identifier_values((target.extra_data or {}).get("identifiers", []))
    # A query applies to this call only; budgets and caches remain investigation-wide.
    extra.pop("search_queries", None)
    extra.pop("ghunt_selection", None)
    extra.pop("academic_selection", None)
    extra.pop("maigret_options", None)
    extra.pop("username_scan_mode", None)
    if (target.extra_data or {}).get("maigret_plan"):
        from app.schemas.workspace import MaigretPlan
        plan = MaigretPlan.model_validate(target.extra_data["maigret_plan"])
        extra["maigret_options"] = plan.options.model_dump(exclude_none=True)
        extra["username_scan_mode"] = plan.scan_mode
    if args.get("maigret_options") is not None or args.get("identifiers") or args.get("scan_mode"):
        from app.schemas.workspace import ToolInputs
        validated = ToolInputs(**{key: args[key] for key in ("maigret_options", "identifiers", "scan_mode") if key in args})
        if validated.maigret_options is not None:
            extra["maigret_options"] = {**extra.get("maigret_options", {}),
                **validated.maigret_options.model_dump(exclude_none=True, exclude_unset=True)}
        if validated.scan_mode:
            extra["username_scan_mode"] = validated.scan_mode
        ids = list(extra.get("maigret_identifiers", []))
        for item in validated.identifiers:
            if item.model_dump() not in ids:
                ids.append(item.model_dump())
        extra["maigret_identifiers"] = ids
    if args.get("queries"):
        from app.schemas.workspace import ToolInputs
        validated = ToolInputs(queries=args["queries"])
        extra["search_queries"] = [query.model_dump() for query in validated.queries]
    return TargetContext(
        full_name=args.get("full_name") or base.full_name or target.full_name,
        email=args.get("email") or base.email or target.email,
        username=args.get("username") or base.username or target.username,
        phone=args.get("phone") or base.phone or target.phone,
        dni=args.get("dni") or base.dni or target.dni,
        university=args.get("university") or base.university or target.university,
        description=target.description,
        declared_seeds=list(base.declared_seeds),
        discovered_phones=list(base.discovered_phones),
        discovered_emails=list(base.discovered_emails),
        discovered_usernames=list(base.discovered_usernames),
        discovered_names=list(base.discovered_names),
        extra={
            **extra,
            "candidate_urls": candidate_urls,
            # Sin esto, el agente autónomo nunca podría ejecutar las fuentes que
            # exigen consentimiento, ni siquiera habiéndolo dado: construye su
            # contexto desde cero en cada llamada.
            "self_consent": bool(
                base.extra.get("self_consent")
                or (target.extra_data or {}).get("self_consent")
            ),
        },
    )


async def dispatch_tool_call(
    name: str,
    args: Dict[str, Any],
    target: Target,
    *,
    base_context: Optional[TargetContext] = None,
    source_prefix: Optional[str] = None,
    engine_layer: Optional[str] = None,
    investigation_id: Optional[str] = None,
) -> List[ToolFinding]:
    """
    Ejecuta la herramienta que pidió el modelo y etiqueta la procedencia.

    `source_prefix` antepone un prefijo a `source_tool` (el agente usa `agent:`
    por compatibilidad con los expedientes ya guardados). `engine_layer` marca
    en qué capa del motor nació el hallazgo, que es lo que permite a la interfaz
    distinguir la cosecha heurística del refinamiento por IA.

    `investigation_id` es lo que permite a las herramientas largas publicar su
    progreso. El agente autónomo construye el contexto desde cero y no lo
    pasaba, así que `username_finder` barría miles de sitios sin emitir un solo
    evento y la interfaz no tenía con qué dibujar la barra.
    """
    tool = tool_registry.get_tool(resolve_tool_name(name))
    if not tool:
        return []

    ctx = build_call_context(args, target, base_context)
    if tool.name == "ghunt":
        from app.tools.ghunt_runtime import select_call_inputs
        select_call_inputs(ctx, args)
    if tool.name == "academic_finder":
        from app.tools.academic_finder import select_call_inputs
        select_call_inputs(ctx, args)
    if tool.name == "domain_finder":
        ctx.extra["personal_domain_urls"] = list(dict.fromkeys([
            *ctx.extra.get("personal_domain_urls", []),
            *([args["url"]] if args.get("url") else []),
            *(args.get("candidate_urls") or []),
        ]))
    if investigation_id:
        ctx.extra["investigation_id"] = investigation_id
    try:
        findings = await tool.execute(ctx)
    finally:
        if base_context is not None:
            # Keep per-investigation caches and budgets even when call inputs differ.
            base_context.extra.update(ctx.extra)
            base_context.extra.pop("search_queries", None)
            base_context.extra.pop("ghunt_selection", None)
            base_context.extra.pop("academic_selection", None)

    for f in findings:
        f.metadata_info["source_tool"] = (
            f"{source_prefix}:{tool.name}" if source_prefix else tool.name
        )
        if engine_layer:
            f.metadata_info["engine_layer"] = engine_layer
    return findings
