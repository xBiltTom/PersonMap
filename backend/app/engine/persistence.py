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
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity
from app.models.relationship import Relationship
from app.models.target import Target
from app.tools.base import ToolFinding
from app.tools.social_profiles import parse_social_profile
from app.schemas.identifiers import CASE_SENSITIVE_TYPES

# Tope de aristas adicionales por nodo. Los árboles de evidencia conservan
# conectividad aunque un ancla tenga más conexiones. Los índices de señales
# evitan comparar todos los pares; los árboles conservan los vecindarios sin
# construir una camarilla entre todos los perfiles que comparten un dato.
#
# El límite conserva un mapa navegable. Se priorizan las relaciones que forman
# grupos porque tienen una prueba explícita, no una puntuación de identidad.
MAX_EDGES_PER_ENTITY = 6


def _dedupe_value(entity_type, value, metadata):
    if entity_type == "academic":
        from app.tools.academic_metadata import doi_url
        doi = doi_url(value)
        if doi:
            return doi
    profile = parse_social_profile(value) if entity_type in {"social_account", "sensitive_account"} else None
    value = (profile.url if profile else value).strip().rstrip("/")
    query = metadata.get("queried_identifier")
    kind = metadata.get("id_type") or (query.get("id_type") if isinstance(query, dict) else None)
    preserve_case = kind in CASE_SENSITIVE_TYPES
    if kind is None and value.startswith(("http://", "https://")):
        from app.tools.maigret_ids import identifiers_from_url
        preserve_case = any(item["id_type"] in CASE_SENSITIVE_TYPES for item in identifiers_from_url(value))
    preserve_case = preserve_case or bool(profile and profile.resource_kind == 'channel_id')
    if preserve_case:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, parsed.fragment))
    return value.lower()


def finding_dedupe_key(f: ToolFinding) -> Tuple[str, str, str]:
    value = _dedupe_value(f.entity_type, f.value, f.metadata_info or {})
    if value.startswith(("http://", "https://")):
        # Una URL identifica el perfil por sí sola, así que la plataforma no
        # entra en la clave: cada herramienta la bautiza a su manera ("github"
        # frente a "GitHub (User)") y el mismo perfil salía dos veces, uno al
        # 65 % y otro al 10 %, cada uno con la procedencia de una sola tool.
        address = value.split("://", 1)[1].removeprefix("www.")
        return (f.entity_type, "url", address)
    return (f.entity_type, (f.platform or "").lower(), value)


def entity_dedupe_key(entity: Entity) -> Tuple[str, str, str]:
    """La misma clave de deduplicación aplicada a una entidad ya persistida."""
    value = _dedupe_value(entity.entity_type, entity.value, entity.metadata_info or {})
    if value.startswith(("http://", "https://")):
        address = value.split("://", 1)[1].removeprefix("www.")
        return (entity.entity_type, "url", address)
    return (entity.entity_type, (entity.platform or "").lower(), value)


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
    observations: Dict[Tuple[str, str, str], List[ToolFinding]] = {}

    for f in findings:
        key = finding_dedupe_key(f)
        observations.setdefault(key, []).append(f)

        tools = provenance.setdefault(key, [])
        prior_tools = (f.metadata_info or {}).get("source_tools", [])
        prior_tools = prior_tools if isinstance(prior_tools, list) else []
        for raw_tool in [(f.metadata_info or {}).get("source_tool"), *prior_tools]:
            tool = normalize_source_tool(raw_tool) if isinstance(raw_tool, str) else ""
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
        # Enumeration often has a higher priority than enrichment. Preserve
        # metadata from both, or the verified bio/emails disappear on save.
        merged = {}
        for observation in sorted(observations[key], key=lambda item: item.confidence):
            for field, value in observation.metadata_info.items():
                if value is None or value == "" or value == [] or value == {}:
                    continue
                if isinstance(value, list) and isinstance(merged.get(field), list):
                    merged[field] = merged[field] + [item for item in value if item not in merged[field]]
                elif field == "citation_counts" and isinstance(value, dict) and isinstance(merged.get(field), dict):
                    # Provider counts describe different indexes; never add them.
                    merged[field] = {**merged[field], **value}
                else:
                    merged[field] = value
        if any(item.metadata_info.get("verification_status") == "verified" for item in observations[key]):
            merged["verification_status"] = "verified"
        merged["source_tool"] = winner.metadata_info.get("source_tool")
        merged["source_tools"] = provenance[key]
        from types import SimpleNamespace
        from app.identity.evidence import POLICY_VERSION, signals
        correlation_observations = []
        for observation in observations[key]:
            source = SimpleNamespace(entity_type=observation.entity_type, platform=observation.platform,
                value=observation.value, source_tool=observation.metadata_info.get('source_tool'),
                metadata_info=observation.metadata_info)
            for item in signals(source):
                if item not in correlation_observations:
                    correlation_observations.append(item)
        merged['correlation_observations'] = correlation_observations[:200]
        merged['correlation_observations_version'] = POLICY_VERSION
        if winner.entity_type == "academic" and merged.get("academic_records"):
            from app.tools.academic_metadata import preserve_author_association
            preserve_author_association(merged)
        winner.evidence_urls = list(dict.fromkeys(url for item in observations[key] for url in item.evidence_urls))
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
    existing_entities: Optional[List[Entity]] = None,
) -> List[Entity]:
    """
    Deduplica y persiste observaciones como entidades.

    Deja las entidades en la sesión con `flush` (no `commit`): el commit es
    responsabilidad del orquestador, que necesita la transacción abierta para
    escribir después los clusters y las métricas.
    """
    entities: List[Entity] = []
    existing = {entity_dedupe_key(entity): entity for entity in (existing_entities or [])}

    for f in dedupe_findings(findings):
        current = existing.get(finding_dedupe_key(f))
        current_metadata = dict(current.metadata_info or {}) if current is not None else {}
        current_provenance = current_metadata.get("provenance") or {}
        current_ownership = current_metadata.get("ownership") or {}
        has_human_account_decision = (
            current_provenance.get("origin") == "automatic"
            and current_provenance.get("status") in {"confirmed", "rejected", "uncertain"}
            and current_ownership.get("status") in {"subject_confirmed", "subject_rejected", "uncertain"}
        )
        if current is not None:
            previous = ToolFinding(
                entity_type=current.entity_type, platform=current.platform, value=current.value,
                display_name=current.display_name, metadata_info=dict(current.metadata_info or {}),
                evidence_urls=(current.metadata_info or {}).get("evidence_urls", []), confidence=0,
            )
            old_tools = (current.metadata_info or {}).get("source_tools", [current.source_tool])
            f = dedupe_findings([previous, f])[0]
            f.metadata_info["source_tools"] = list(dict.fromkeys([*old_tools, *f.metadata_info.get("source_tools", [])]))
        metadata = dict(f.metadata_info or {})
        from app.schemas.footprint import discovered_provenance, is_declared_identifier
        # Tools (including agents) cannot manufacture a subject's decision.
        metadata["provenance"] = ((current.metadata_info or {}).get("provenance") if current else None) or discovered_provenance(
            f.evidence_urls, matches_declared_identifier=is_declared_identifier(target, f.entity_type, f.value, f.platform))
        if f.entity_type == "social_account":
            from app.schemas.footprint import account_ownership, footprint_input
            from app.tools.social_profiles import parse_social_profile
            declared = footprint_input(target)
            profile = parse_social_profile(f.value)
            ownership = account_ownership(declared.declared_seeds if declared else [],
                profile.platform if profile else f.platform, profile.username if profile else "")
            # Only the explicit Verification Gate operation writes these states.
            # A later tool refresh may enrich evidence, but cannot undo or replace
            # the subject's active decision.
            if has_human_account_decision:
                metadata.update(ownership=current_ownership,
                    ownership_status=current_ownership["status"], ownership_review_required=False)
            else:
                metadata.update(ownership=ownership, ownership_status=ownership["status"],
                                ownership_review_required=ownership["needs_review"])
        # Las herramientas ya recogen URLs de evidencia, pero Entity no tenía
        # una columna específica para ellas. Persistirlas dentro del metadata
        # evita una migración y permite que el inspector separe la fuente del
        # recurso observado. Solo se añaden cuando la herramienta las entregó.
        if f.evidence_urls:
            metadata["evidence_urls"] = list(dict.fromkeys([*metadata.get("evidence_urls", []), *f.evidence_urls]))

        if current is not None:
            current.metadata_info = metadata
            current.display_name = (f.display_name or current.display_name or f.value)[:255]
            entities.append(current)
            continue

        entity = Entity(
            investigation_id=investigation_id,
            entity_type=f.entity_type,
            platform=f.platform,
            value=f.value,
            display_name=(f.display_name or f.value)[:255],
            metadata_info=metadata,
            source_tool=metadata.get("source_tool", default_source_tool),
        )
        db.add(entity)
        entities.append(entity)
        existing[finding_dedupe_key(f)] = entity

    await db.flush()
    return entities


def detect_relationships(a: Entity, b: Entity) -> List[Tuple[str, bool, dict]]:
    from app.identity.evidence import pair_evidence
    return pair_evidence(a, b)


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


def infer_relationships(entities, priorities=None):
    """A strong evidence forest preserves connectivity; extra edges stay bounded."""
    from app.identity.evidence import signals, pair_evidence
    from app.identity.resolver import UnionFind
    priorities = priorities or {}
    observed = {str(entity.id): signals(entity) for entity in entities}
    from collections import defaultdict
    from app.identity.evidence import resource_key, strong_values, strings
    by_id = {str(entity.id): entity for entity in entities}
    indexes, resources = defaultdict(list), defaultdict(list)
    for entity in entities:
        key = str(entity.id)
        for item in observed[key]:
            if item['kind'] == 'email' and item['value'] not in strong_values(observed[key], 'email'):
                continue
            indexes[(item['kind'], item['value'])].append(key)
        resource = resource_key(entity.value)
        if resource:
            resources[resource].append(key)
        for value in strong_values(observed[key], 'orcid'):
            resources[resource_key('https://orcid.org/' + value)].append(key)
    pairs = set()
    def connect(left, right):
        if left != right:
            pairs.add(tuple(sorted((left, right))))
    for members in indexes.values():
        members = sorted(set(members), key=lambda member: (-priorities.get(member, 0), member))
        # A hub and local neighbors retain connectivity without a quadratic clique.
        for index, member in enumerate(members):
            connect(members[0], member)
            for neighbor in members[index + 1:index + 4]:
                connect(member, neighbor)
    for entity in entities:
        metadata = entity.metadata_info or {}
        links = [*strings(metadata.get('linked_profiles')), *strings(metadata.get('matched_author_ids'))]
        for record in metadata.get('academic_records', []) if isinstance(metadata.get('academic_records'), list) else []:
            for author in record.get('matched_authors', []) if isinstance(record, dict) and isinstance(record.get('matched_authors'), list) else []:
                if isinstance(author, dict) and isinstance(author.get('orcid'), str):
                    links.append(author['orcid'])
        for link in links:
            for other in resources.get(resource_key(link), []):
                connect(str(entity.id), other)
    candidates = []
    for source, destination in sorted(pairs):
        a, b = by_id[source], by_id[destination]
        for relation_type, grouping, evidence in pair_evidence(a, b, observed[source], observed[destination]):
            candidates.append((grouping, a, b, relation_type, evidence))
    candidates.sort(key=lambda item: (not item[0], -item[4].get('visual_weight', 0),
        -max(priorities.get(str(item[1].id), 0), priorities.get(str(item[2].id), 0)),
        str(item[1].id), str(item[2].id), item[3]))
    forest = UnionFind([str(entity.id) for entity in entities])
    visual_forest = UnionFind([str(entity.id) for entity in entities])
    degree, selected = {}, []
    for grouping, a, b, kind, evidence in candidates:
        source, destination = str(a.id), str(b.id)
        needed = grouping and forest.find(source) != forest.find(destination)
        needed = needed or (kind in {'same_name', 'name_and_affiliation', 'authored_work'}
            and visual_forest.find(source) != visual_forest.find(destination))
        if not needed and (degree.get(source, 0) >= MAX_EDGES_PER_ENTITY or degree.get(destination, 0) >= MAX_EDGES_PER_ENTITY):
            continue
        if grouping:
            forest.union(source, destination)
        if kind != 'same_username':
            visual_forest.union(source, destination)
        selected.append((a, b, kind, grouping, evidence))
        degree[source] = degree.get(source, 0) + 1
        degree[destination] = degree.get(destination, 0) + 1
    return selected


async def build_relationships(investigation_id: str, entities: List[Entity], db: AsyncSession) -> List[Relationship]:
    created = []
    for a, b, kind, grouping, evidence in infer_relationships(entities):
        rel = Relationship(investigation_id=investigation_id, source_entity_id=a.id,
            target_entity_id=b.id, relation_type=kind, supports_group=grouping, evidence=evidence)
        db.add(rel)
        created.append(rel)
    await db.flush()
    return created
