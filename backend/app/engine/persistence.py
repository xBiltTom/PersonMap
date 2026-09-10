"""
Persistencia compartida de hallazgos OSINT.

Antes, `rule_engine.execute_investigation` y `autonomous_agent.run` implementaban
cada uno su propia versión de "convertir ToolFinding en Entity y construir el
grafo". La del agente era una copia degradada: sin deduplicación y con una
detección de relaciones reducida a `same_platform` / `uses_email`. El resultado
era que una investigación en modo agéntico producía entidades duplicadas y un
grafo más pobre, y que toda mejora del pipeline había que escribirla dos veces.

Este módulo es la única fuente de verdad para esa etapa. Ambos motores lo
llaman, de modo que el agente hereda gratis la deduplicación y la detección de
relaciones completa.
"""

from typing import Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.scorer import compute_identity_score
from app.models.entity import Entity
from app.models.relationship import Relationship
from app.models.target import Target
from app.tools.base import ToolFinding

# Tope de aristas por nodo. El emparejamiento es O(n^2) sobre las entidades de la
# investigación: con ~30 entidades son ~450 pares, pero al ampliar el catálogo de
# plataformas una sola investigación puede pasar de 500 entidades (125.000 pares).
# Sin tope, el mapa digital se vuelve una maraña ilegible y el flush de
# relaciones domina el tiempo total.
#
# El límite se aplica por nodo, tras ordenar las aristas candidatas de mayor a
# menor fuerza, de modo que las relaciones con evidencia real (`uses_email` 0.95,
# `linked_to` 0.90) sobreviven al recorte antes que las débiles (`same_username`
# 0.85). Medido sobre una investigación real de 94 entidades: sin tope el grafo
# tenía 3.835 aristas; con este valor baja a ~280 y sigue siendo navegable.
MAX_EDGES_PER_ENTITY = 6


def _dedupe_key(f: ToolFinding) -> Tuple[str, str, str]:
    value = f.value.strip().rstrip("/").lower()
    if value.startswith(("http://", "https://")):
        # Una URL identifica el perfil por sí sola, así que la plataforma no
        # entra en la clave: cada herramienta la bautiza a su manera ("github"
        # frente a "GitHub (User)") y el mismo perfil salía dos veces, uno al
        # 65 % y otro al 10 %, cada uno con la procedencia de una sola tool.
        address = value.split("://", 1)[1].removeprefix("www.")
        return (f.entity_type, "url", address)
    return (f.entity_type, (f.platform or "").lower(), value)


def dedupe_findings(findings: List[ToolFinding]) -> List[ToolFinding]:
    """
    Colapsa hallazgos equivalentes conservando el de mayor confianza.

    La clave normaliza plataforma y valor (minúsculas, sin barra final) porque
    distintas tools descubren el mismo perfil con URLs cosméticamente distintas
    (`https://github.com/u` vs `https://github.com/u/`).

    Conserva la procedencia COMPLETA en `source_tools`. Es imprescindible para
    el modelo de identidad: un perfil hallado al enumerar el alias del objetivo
    y luego reverificado por `social_verifier` conservaba solo el segundo, y el
    scorer perdía de vista que la coincidencia del alias estaba garantizada por
    el método de búsqueda. Resultado: cuentas cualesquiera de la cola larga
    puntuaban 0.99 por una coincidencia tautológica.
    """
    deduped: Dict[Tuple[str, str, str], ToolFinding] = {}
    provenance: Dict[Tuple[str, str, str], List[str]] = {}
    layers: Dict[Tuple[str, str, str], List[str]] = {}

    for f in findings:
        key = _dedupe_key(f)

        tool = normalize_source_tool((f.metadata_info or {}).get("source_tool"))
        tools = provenance.setdefault(key, [])
        if tool and tool not in tools:
            tools.append(tool)

        # Igual que con la procedencia por herramienta, la capa que produjo el
        # hallazgo se acumula en lugar de sobrescribirse: el motor híbrido
        # necesita saber si un perfil lo aportó solo la IA, solo el barrido
        # heurístico, o los dos. Es la cifra con la que se defiende (o se
        # descarta) el valor del refinamiento en la comparativa del artículo.
        layer = str((f.metadata_info or {}).get("engine_layer") or "")
        seen_layers = layers.setdefault(key, [])
        if layer and layer not in seen_layers:
            seen_layers.append(layer)

        current = deduped.get(key)
        if current is None or f.confidence > current.confidence:
            deduped[key] = f

    for key, winner in deduped.items():
        merged = {**(winner.metadata_info or {}), "source_tools": provenance[key]}
        if layers[key]:
            merged["engine_layers"] = layers[key]
        winner.metadata_info = merged

    return list(deduped.values())


async def persist_findings(
    investigation_id: str,
    findings: List[ToolFinding],
    target: Target,
    db: AsyncSession,
    default_source_tool: str = "osint_engine",
) -> List[Entity]:
    """
    Deduplica, puntúa y persiste los hallazgos como entidades.

    Deja las entidades en la sesión con `flush` (no `commit`): el commit es
    responsabilidad del orquestador, que necesita la transacción abierta para
    escribir después los clusters y las métricas.
    """
    entities: List[Entity] = []

    for f in dedupe_findings(findings):
        identity_score, breakdown = compute_identity_score(
            display_name=f.display_name,
            value=f.value,
            metadata=f.metadata_info,
            target=target,
        )

        # El breakdown es el dato más rico del modelo y ambos motores lo
        # descartaban. Se guarda en metadata_info para que la interfaz pueda
        # explicar señal a señal por qué se atribuye el hallazgo al objetivo.
        metadata = dict(f.metadata_info or {})
        metadata["identity_breakdown"] = breakdown
        metadata["identity_score"] = identity_score

        # Dos preguntas distintas, dos columnas. `f.confidence` es la certeza de
        # DETECCIÓN que reporta la herramienta ("esta cuenta existe");
        # `identity_score` es la de ATRIBUCIÓN ("es del objetivo"). `confidence`
        # se mantiene como el valor mostrado y ordenable, pero ya no oculta el
        # modelo: antes el `max()` lo tapaba siempre, porque las herramientas
        # emiten constantes de 0.85-1.0 y el modelo saturaba en 0.05 o 0.45.
        existence_confidence = round(f.confidence, 3)

        entity = Entity(
            investigation_id=investigation_id,
            entity_type=f.entity_type,
            platform=f.platform,
            value=f.value,
            display_name=(f.display_name or f.value)[:255],
            metadata_info=metadata,
            existence_confidence=existence_confidence,
            identity_score=identity_score,
            scorer_version=breakdown.get("scorer_version"),
            confidence=round(max(existence_confidence, identity_score), 3),
            verified=False,
            source_tool=metadata.get("source_tool", default_source_tool),
        )
        db.add(entity)
        entities.append(entity)

    await db.flush()
    return entities


# Tools que enumeran un mismo identificador semilla a través de muchas
# plataformas. Dos hallazgos suyos comparten alias/correo por construcción, no
# por evidencia descubierta.
ENUMERATION_TOOLS = {
    "username_finder",
    "email_enumerator",
    "phone_enumerator",
    # Consulta por el correo y el alias del objetivo, así que dos registros
    # suyos comparten identificador por construcción, no por evidencia.
    "infostealer_checker",
}


def detect_relationship(a: Entity, b: Entity) -> Tuple[Optional[str], float]:
    """
    Deduce el tipo de relación entre dos entidades. Primer criterio que casa gana.

    A diferencia de la versión anterior, ya no existe el caso de reserva
    `a.platform == b.platform -> ("same_platform", 0.50)`. Aquel criterio no
    aportaba evidencia (dos cuentas en la misma red no son la misma persona) y
    además casaba `None == None`, enlazando entre sí a todas las entidades sin
    plataforma. Al crecer el número de entidades generaba decenas de miles de
    aristas sin significado que hacían ilegible el mapa digital.
    """
    meta_a = a.metadata_info or {}
    meta_b = b.metadata_info or {}

    # 1. Mismo alias en ambos perfiles: la señal de correlación más directa...
    #    salvo entre hermanos de enumeración. Si `username_finder` busca "jperez"
    #    en 500 plataformas y lo encuentra en 90, esas 90 comparten el alias por
    #    definición: la arista sería tautológica y generaría 90*89/2 = 4005
    #    conexiones que no dicen nada. La pertenencia común ya la expresa la
    #    arista de cada nodo con la raíz del objetivo.
    user_a = (meta_a.get("username") or "").lower()
    user_b = (meta_b.get("username") or "").lower()
    if user_a and user_b and user_a == user_b and not _are_enumeration_siblings(a, b):
        return "same_username", 0.85

    # 2. Un perfil declara el correo que la otra entidad representa. Se comprueba
    #    en ambos sentidos porque el emparejamiento solo visita cada par una vez
    #    y el orden de las entidades en la lista es arbitrario.
    if _declares_email(a, meta_b) or _declares_email(b, meta_a):
        return "uses_email", 0.95

    # 3. Un perfil enlaza explícitamente al otro.
    if _links_to(meta_a, b) or _links_to(meta_b, a):
        return "linked_to", 0.90

    return None, 0.0


def normalize_source_tool(source_tool: Optional[str]) -> str:
    """
    Nombre de herramienta sin el prefijo del motor que la despachó.

    El `source_tool` puede venir etiquetado por el motor que hizo la llamada
    (`agent:username_finder`). La comparación tiene que hacerse sobre el nombre
    desnudo: si un prefijo nuevo se colara sin normalizar, dos hermanos de
    enumeración dejarían de reconocerse como tales y volverían las aristas
    tautológicas `same_username` que en su día inflaron el grafo a 3.835 aristas.
    """
    return (source_tool or "").rsplit(":", 1)[-1]


def _are_enumeration_siblings(a: Entity, b: Entity) -> bool:
    """True si ambas entidades salieron de la misma tool de enumeración."""
    tool_a = normalize_source_tool(a.source_tool)
    tool_b = normalize_source_tool(b.source_tool)
    return tool_a == tool_b and tool_a in ENUMERATION_TOOLS


def _declares_email(email_entity: Entity, other_meta: dict) -> bool:
    """True si `other_meta` lista el correo que representa `email_entity`."""
    if email_entity.entity_type != "email":
        return False
    emails = other_meta.get("emails") or []
    if not isinstance(emails, list):
        return False
    return email_entity.value.lower() in [str(e).lower() for e in emails]


def _links_to(meta: dict, other: Entity) -> bool:
    """True si algún perfil enlazado en `meta` apunta al valor de `other`."""
    links = meta.get("linked_profiles") or []
    if not isinstance(links, list):
        return False
    return any(other.value in str(link) for link in links)


async def build_relationships(
    investigation_id: str,
    entities: List[Entity],
    db: AsyncSession,
) -> List[Relationship]:
    """
    Construye las aristas del grafo entre las entidades ya persistidas.

    Requiere que `entities` venga de `persist_findings` (o de un flush previo),
    porque necesita los UUID asignados.
    """
    degree: Dict[str, int] = {}
    candidates: List[Tuple[float, Entity, Entity, str]] = []

    for i, ent_a in enumerate(entities):
        for ent_b in entities[i + 1:]:
            rel_type, strength = detect_relationship(ent_a, ent_b)
            if rel_type:
                candidates.append((strength, ent_a, ent_b, rel_type))

    # Las aristas más fuertes se colocan primero, de modo que si un nodo alcanza
    # su tope conserve sus vínculos más significativos.
    candidates.sort(key=lambda c: c[0], reverse=True)

    created: List[Relationship] = []
    for strength, ent_a, ent_b, rel_type in candidates:
        key_a, key_b = str(ent_a.id), str(ent_b.id)
        if degree.get(key_a, 0) >= MAX_EDGES_PER_ENTITY:
            continue
        if degree.get(key_b, 0) >= MAX_EDGES_PER_ENTITY:
            continue

        rel = Relationship(
            investigation_id=investigation_id,
            source_entity_id=ent_a.id,
            target_entity_id=ent_b.id,
            relation_type=rel_type,
            strength=strength,
        )
        db.add(rel)
        created.append(rel)
        degree[key_a] = degree.get(key_a, 0) + 1
        degree[key_b] = degree.get(key_b, 0) + 1

    await db.flush()
    return created
