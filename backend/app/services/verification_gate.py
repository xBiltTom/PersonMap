"""Human review projection for Fair findings; tool output never supplies a decision."""

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entity import Entity
from app.models.entity_observation import EntityObservation
from app.models.investigation import Investigation
from app.models.relationship import Relationship
from app.models.review_decision import ReviewDecision
from app.models.target import Target
from app.schemas.footprint import DataProvenance, account_ownership, footprint_input
from app.schemas.review import (
    BreachExposure, InfostealerExposure, FairReviewState, FairSourceState, InvestigationReviewResponse,
    ReviewCandidate, ReviewCounts, ReviewSource, ReviewedDecisionRecord,
    ReviewedDeclaredSeed, ReviewedEntity, ReviewedFootprintDataset,
)
from app.social.capabilities import canonical_platform
from app.tools.social_profiles import parse_social_profile

DECISIONS = {"confirmed", "rejected", "uncertain"}
PROFILE_ENTITY_TYPES = {"social_account", "sensitive_account", "google_account", "academic_profile"}
IDENTITY_ENTITY_TYPES = PROFILE_ENTITY_TYPES | {"email", "phone", "email_registration"}
SENSITIVE_QUERY_KEYS = {"token", "access_token", "api_key", "apikey", "key", "auth", "authorization", "session", "password", "secret"}


def _metadata(entity: Entity) -> dict:
    value = entity.metadata_info or {}
    return value if isinstance(value, dict) else {}


def _seed_id(seed) -> str:
    reference = {"kind": seed.kind, "value": seed.value, "platform": seed.platform}
    return hashlib.sha256(json.dumps(reference, sort_keys=True).encode()).hexdigest()


def _provenance(entity: Entity) -> DataProvenance:
    try:
        return DataProvenance.model_validate(_metadata(entity).get("provenance") or {
            "origin": "legacy", "status": "discovered", "evidence_urls": _metadata(entity).get("evidence_urls", [])
        })
    except Exception:
        return DataProvenance(origin="legacy", status="discovered")


def safe_public_url(value) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        query = [(key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True)
                 if key.casefold() not in SENSITIVE_QUERY_KEYS and not any(word in key.casefold() for word in ("token", "secret", "password"))]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    except (ValueError, TypeError):
        return None


def _urls(values) -> list[str]:
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        url = safe_public_url(value)
        if url and url not in result:
            result.append(url)
    return result[:30]


def is_declared_account(entity: Entity, target: Target) -> bool:
    if entity.entity_type not in {"social_account", "sensitive_account"}:
        return False
    profile = parse_social_profile(entity.value)
    username = profile.username if profile else _metadata(entity).get("username")
    if not isinstance(username, str) or not username:
        return False
    platform = profile.platform if profile else entity.platform
    declared = footprint_input(target)
    return account_ownership(declared.declared_seeds if declared else [], platform, username)["status"] == "subject_declared"


def _reviewable_kind(entity: Entity, target: Target) -> str | None:
    meta = _metadata(entity)
    provenance = _provenance(entity)
    entity_type = entity.entity_type

    if entity_type in {"social_account", "sensitive_account"}:
        if is_declared_account(entity, target):
            return None
        if provenance.origin == "automatic" and provenance.status in {"discovered", "confirmed", "rejected", "uncertain"}:
            return "account"
        return None
    if entity_type == "academic" and entity.platform == "openalex_author":
        return "academic_profile" if provenance.needs_review else None
    if entity_type not in IDENTITY_ENTITY_TYPES:
        return None
    if entity_type in {"email", "phone"}:
        if provenance.matches_declared_identifier:
            return None
    if provenance.needs_review:
        return {
            "email": "email", "phone": "phone", "email_registration": "account",
            "google_account": "account", "academic_profile": "academic_profile",
        }.get(entity_type)
    return None


def _has_review_work(entity: Entity, target: Target, decision: ReviewDecision | None) -> bool:
    return bool(decision and decision.decision in DECISIONS) or _reviewable_kind(entity, target) is not None


def _source_label(tool: str) -> str:
    labels = {
        "apify_social": "Apify Social", "social_verifier": "Social Verifier",
        "search_dorker": "SearchDorker", "username_finder": "Username Finder",
        "maigret_enricher": "Maigret", "ghunt": "GHunt", "google_account_osint": "Google OSINT",
        "academic_finder": "OpenAlex / Crossref", "email_checker": "Email Checker",
        "email_enumerator": "Email Enumerator", "phone_lookup": "Phone Lookup",
        "github_deep_scanner": "GitHub Scanner", "social_url_extractor": "URL pública",
    }
    clean = tool.rsplit(":", 1)[-1]
    return labels.get(clean, clean.replace("_", " ").strip().title() or "Fuente automática")


def _candidate_reason(entity: Entity, target: Target, sources: list[ReviewSource]) -> str:
    meta = _metadata(entity)
    if entity.entity_type == "academic" or entity.entity_type == "academic_profile":
        if meta.get("affiliation_match") is True and meta.get("query_name"):
            return "Perfil académico encontrado con coincidencia de nombre y afiliación."
        return "Perfil académico público relacionado por el motor académico; la autoría aún requiere tu revisión."
    if entity.entity_type in {"social_account", "sensitive_account"}:
        profile = parse_social_profile(entity.value)
        declared = footprint_input(target)
        matching_alias = next((seed.value for seed in (declared.declared_seeds if declared else [])
                               if seed.kind == "username" and profile and seed.value.casefold() == profile.username.casefold()), None)
        tools = {source.name for source in sources}
        if "SearchDorker" in tools and meta.get("literal_match") is True:
            return "Resultado exacto en SearchDorker; la coincidencia de alias no demuestra pertenencia."
        if matching_alias:
            return f"Encontrado al buscar el alias declarado «{matching_alias}»; cada plataforma requiere su propia decisión."
        return "Perfil público detectado automáticamente; la existencia del perfil no demuestra pertenencia."
    if entity.entity_type == "email":
        return "Correo nuevo observado en una fuente pública; todavía no está asociado a ti."
    if entity.entity_type == "phone":
        return "Teléfono nuevo observado en una fuente pública; todavía no está asociado a ti."
    if entity.entity_type == "email_registration":
        return "Una fuente detectó un registro asociado a un correo; esto no confirma quién usa la cuenta."
    return f"Identidad pública relacionada por {sources[0].name if sources else 'una fuente automática'}."


def _candidate(entity: Entity, target: Target, decision: ReviewDecision | None,
               observations: list[EntityObservation]) -> ReviewCandidate | None:
    category = _reviewable_kind(entity, target)
    if not category and not decision:
        return None
    # A declared account is never reviewable, even if malformed legacy data has a decision row.
    if entity.entity_type in {"social_account", "sensitive_account"} and is_declared_account(entity, target):
        return None

    meta = _metadata(entity)
    profile = parse_social_profile(entity.value) if entity.entity_type in {"social_account", "sensitive_account"} else None
    username = (profile.username if profile else meta.get("username") or meta.get("preferred_username"))
    public_url = safe_public_url(meta.get("profile_url") or meta.get("url") or (profile.url if profile else None))
    evidence_urls = _urls(meta.get("evidence_urls", []))
    source_urls: dict[str, list[str]] = defaultdict(list)
    source_names = []
    for source in [meta.get("source_tool"), *(meta.get("source_tools") if isinstance(meta.get("source_tools"), list) else []), entity.source_tool]:
        if isinstance(source, str) and source:
            name = _source_label(source)
            if name not in source_names:
                source_names.append(name)
    for observation in observations:
        execution = observation.tool_execution
        name = _source_label(execution.tool_name if execution else entity.source_tool)
        if name not in source_names:
            source_names.append(name)
        urls = _urls([observation.source_url, *(observation.evidence_urls or [])])
        for url in urls:
            if url not in source_urls[name]:
                source_urls[name].append(url)
                if url not in evidence_urls:
                    evidence_urls.append(url)
    for url in _urls([public_url, *meta.get("evidence_urls", [])] if isinstance(meta.get("evidence_urls", []), list) else [public_url]):
        if url not in evidence_urls:
            evidence_urls.append(url)
    if source_names and evidence_urls and not source_urls.get(source_names[0]):
        source_urls[source_names[0]].extend(evidence_urls[:10])
    sources = [ReviewSource(name=name, evidence_urls=source_urls.get(name, [])[:10]) for name in source_names]
    if not sources:
        sources = [ReviewSource(name=_source_label(entity.source_tool), evidence_urls=evidence_urls[:10])]
    provenance = _provenance(entity)
    return ReviewCandidate(
        id=entity.id,
        entity_type=entity.entity_type,
        category=category or {"email": "email", "phone": "phone", "academic": "academic_profile",
                              "academic_profile": "academic_profile"}.get(entity.entity_type, "account"),
        platform=entity.platform,
        value=entity.value,
        username=username if isinstance(username, str) else None,
        display_name=entity.display_name,
        avatar_url=safe_public_url(meta.get("avatar_url")),
        public_url=public_url,
        bio=meta.get("bio") or meta.get("biography") if isinstance(meta.get("bio") or meta.get("biography"), str) else None,
        institutions=[item for item in meta.get("institutions", []) if isinstance(item, str)][:10] if isinstance(meta.get("institutions"), list) else [],
        reason=_candidate_reason(entity, target, sources),
        sources=sources,
        evidence_urls=evidence_urls[:30],
        provenance=provenance,
        decision=decision.decision if decision else None,
        decided_at=decision.decided_at if decision else None,
    )


async def _load_entities(db: AsyncSession, investigation_id: UUID) -> list[Entity]:
    return list((await db.scalars(select(Entity).where(Entity.investigation_id == investigation_id)
        .order_by(Entity.discovered_at, Entity.id))).all())


async def _load_decisions(db: AsyncSession, investigation_id: UUID) -> dict[UUID, ReviewDecision]:
    rows = (await db.scalars(select(ReviewDecision).where(ReviewDecision.investigation_id == investigation_id))).all()
    return {row.entity_id: row for row in rows}


async def _load_observations(db: AsyncSession, investigation_id: UUID) -> dict[UUID, list[EntityObservation]]:
    rows = (await db.scalars(select(EntityObservation).where(EntityObservation.investigation_id == investigation_id)
        .options(selectinload(EntityObservation.tool_execution)))).all()
    result: dict[UUID, list[EntityObservation]] = defaultdict(list)
    for row in rows:
        result[row.entity_id].append(row)
    return result


def _counts(candidates: list[ReviewCandidate]) -> ReviewCounts:
    return ReviewCounts(
        pending=sum(item.decision is None for item in candidates),
        confirmed=sum(item.decision == "confirmed" for item in candidates),
        rejected=sum(item.decision == "rejected" for item in candidates),
        uncertain=sum(item.decision == "uncertain" for item in candidates),
    )


def fair_state(investigation: Investigation) -> FairReviewState:
    metrics = investigation.metrics or {}
    snapshot = metrics.get("fair_snapshot") if isinstance(metrics.get("fair_snapshot"), dict) else {}
    progress = metrics.get("fair_progress") if isinstance(metrics.get("fair_progress"), dict) else {}
    partial = bool((snapshot.get("execution") or {}).get("partial"))
    sources = snapshot.get("sources") or progress.get("sources") or {}
    social_sources = progress.get("social_sources") or {}
    def compact(rows):
        return {name: FairSourceState(status=str(value.get("status", "unknown")),
                    reason=value.get("reason") if isinstance(value.get("reason"), str) else None,
                    findings_count=int(value.get("findings_count", 0) or 0))
                for name, value in rows.items() if isinstance(value, dict)}
    return FairReviewState(
        acquisition_finished=investigation.status == "completed" and investigation.completed_at is not None,
        partial=partial,
        warning="La búsqueda terminó con algunas fuentes incompletas. Puedes revisar los resultados disponibles." if partial else None,
        sources=compact(sources) if isinstance(sources, dict) else {},
        social_sources=compact(social_sources) if isinstance(social_sources, dict) else {},
    )


def review_status(investigation: Investigation, candidate_ids: set[UUID], decisions: dict[UUID, ReviewDecision]) -> tuple[str, datetime | None]:
    gate = (investigation.metrics or {}).get("verification_gate") or {}
    finalized = gate.get("finalized_at")
    if finalized and not isinstance(finalized, datetime):
        try:
            finalized = datetime.fromisoformat(str(finalized).replace("Z", "+00:00"))
        except ValueError:
            finalized = None
    finalized_ids = set()
    for value in gate.get("reviewed_candidate_ids", []):
        try:
            finalized_ids.add(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    if finalized and candidate_ids.issubset(finalized_ids):
        return "complete", finalized
    started = gate.get("started_at") or decisions
    return ("in_progress" if started or finalized else "not_started"), None


async def get_review_response(db: AsyncSession, investigation: Investigation, target: Target) -> InvestigationReviewResponse:
    entities = await _load_entities(db, investigation.id)
    decisions = await _load_decisions(db, investigation.id)
    observations = await _load_observations(db, investigation.id)
    candidates = []
    for entity in entities:
        decision = decisions.get(entity.id)
        if not _has_review_work(entity, target, decision):
            continue
        item = _candidate(entity, target, decision, observations.get(entity.id, []))
        if item:
            candidates.append(item)
    status, finalized = review_status(investigation, {item.id for item in candidates}, decisions)
    declared = footprint_input(target)
    return InvestigationReviewResponse(
        investigation_id=investigation.id,
        review_status=status,
        finalized_at=finalized,
        counts=_counts(candidates),
        declared_seeds=declared.declared_seeds if declared else [],
        candidates=candidates,
        fair=fair_state(investigation),
    )


def _safe_collection_sources(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    allowed = {"provider", "actor", "actor_id", "run_id", "dataset_id", "build_id", "build_number",
               "source_platform", "source_url", "retrieved_at", "query"}
    result = []
    for source in value[:10]:
        if not isinstance(source, dict):
            continue
        clean = {key: source[key] for key in allowed if key in source}
        if isinstance(clean.get("source_url"), str):
            clean["source_url"] = safe_public_url(clean["source_url"])
        if isinstance(clean.get("query"), dict):
            clean["query"] = {key: source["query"][key] for key in ("platform", "username", "profile_url")
                              if key in source["query"] and isinstance(source["query"][key], str)}
            if isinstance(clean["query"].get("profile_url"), str):
                clean["query"]["profile_url"] = safe_public_url(clean["query"]["profile_url"])
        result.append(clean)
    return result


def _safe_content(value, account: Entity) -> list[dict]:
    if not isinstance(value, list):
        return []
    allowed = {"id", "url", "text", "caption", "title", "description", "posted_at", "published_at",
               "timestamp", "media_type", "content_type", "likes", "comments", "views", "platform",
               "origin", "author_username", "authorship_role", "collection_source"}
    result = []
    for item in value[:100]:
        if not isinstance(item, dict):
            continue
        clean = {}
        for key in allowed.intersection(item):
            raw = item[key]
            if key == "url":
                clean[key] = safe_public_url(raw) if isinstance(raw, str) else None
            elif key in {"likes", "comments", "views"}:
                if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
                    clean[key] = raw
            elif key == "collection_source" and isinstance(raw, dict):
                clean[key] = raw
            elif isinstance(raw, str):
                limits = {"text": 4000, "caption": 4000, "description": 2000,
                          "title": 1000, "id": 256, "author_username": 100}
                clean[key] = raw[:limits.get(key, 128)]
        if isinstance(clean.get("collection_source"), dict):
            clean["collection_source"] = _safe_collection_sources([clean["collection_source"]])[0]
        account_profile = parse_social_profile(account.value) if account.entity_type in {"social_account", "sensitive_account"} else None
        account_username = _metadata(account).get("username") or (account_profile.username if account_profile else None)
        clean.update(account_entity_id=str(account.id), account_platform=account.platform,
                     account_username=account_username, origin="automatic")
        result.append(clean)
    return result


def _record(entity: Entity | None, *, entity_type: str, value: str, platform: str | None = None,
            ownership: dict | None = None, content_source: Entity | None = None,
            associated_profile: UUID | None = None, authorship: dict | None = None,
            seed_id: str | None = None, username: str | None = None) -> ReviewedEntity:
    meta = _metadata(entity) if entity else {}
    provenance = _provenance(entity) if entity else DataProvenance(origin="subject", status="declared", subject_asserted=True)
    profile = parse_social_profile(entity.value) if entity and entity.entity_type in {"social_account", "sensitive_account"} else None
    profile_url = safe_public_url(meta.get("profile_url") or meta.get("url") or (profile.url if profile else None))
    sources = _safe_collection_sources(meta.get("collection_sources"))
    tools = meta.get("source_tools") if isinstance(meta.get("source_tools"), list) else []
    source_tools = list(dict.fromkeys([_source_label(item) for item in [entity.source_tool if entity else None, *tools] if isinstance(item, str)]))
    content = _safe_content(meta.get("public_content"), content_source) if content_source else []
    return ReviewedEntity(
        entity_id=entity.id if entity else None,
        seed_id=seed_id,
        entity_type=entity_type,
        platform=platform if platform is not None else (entity.platform if entity else None),
        username=username if username is not None else (profile.username if profile else (meta.get("username") if isinstance(meta.get("username"), str) else None)),
        value=value,
        display_name=entity.display_name if entity else value,
        profile_url=profile_url,
        avatar_url=safe_public_url(meta.get("avatar_url")),
        bio=meta.get("bio") if isinstance(meta.get("bio"), str) else None,
        provenance=provenance,
        ownership=ownership or {"status": "subject_confirmed" if provenance.status == "confirmed" else "subject_declared"},
        source_tool=entity.source_tool if entity else None,
        source_tools=source_tools,
        collection_sources=sources,
        public_content=content,
        evidence_urls=_urls(meta.get("evidence_urls", [])),
        associated_profile_entity_id=associated_profile,
        authorship_evidence=authorship or {},
    )


def _decision_records(candidates: list[Entity], decisions: dict[UUID, ReviewDecision]) -> dict[str, list[ReviewedDecisionRecord]]:
    result = {name: [] for name in DECISIONS}
    for entity in candidates:
        row = decisions.get(entity.id)
        if not row or row.decision not in DECISIONS:
            continue
        result[row.decision].append(ReviewedDecisionRecord(entity_id=entity.id, entity_type=entity.entity_type,
            platform=entity.platform, value=entity.value, display_name=entity.display_name, decision=row.decision,
            decided_at=row.decided_at))
    return result


async def build_dataset(db: AsyncSession, investigation: Investigation, target: Target,
                        candidates: list[ReviewCandidate] | None = None) -> ReviewedFootprintDataset:
    entities = await _load_entities(db, investigation.id)
    decisions = await _load_decisions(db, investigation.id)
    entity_by_id = {entity.id: entity for entity in entities}
    declared = footprint_input(target)
    seeds = declared.declared_seeds if declared else []
    confirmed = {entity_id for entity_id, row in decisions.items() if row.decision == "confirmed"}

    accounts: list[ReviewedEntity] = []
    included_account_ids: set[UUID] = set()
    for seed in seeds:
        if seed.kind != "username":
            continue
        identifier = _seed_id(seed)
        matching = None
        for entity in entities:
            if entity.entity_type != "social_account":
                continue
            profile = parse_social_profile(entity.value)
            if profile and profile.username.casefold() == seed.value.casefold() and canonical_platform(profile.platform) == canonical_platform(seed.platform):
                matching = entity
                break
        record = _record(matching, entity_type="social_account", value=matching.value if matching else seed.value,
            platform=seed.platform, ownership={"status": "subject_declared", "subject_asserted": True,
                "seed_id": identifier}, content_source=matching, seed_id=identifier, username=seed.value)
        accounts.append(record)
        if matching:
            included_account_ids.add(matching.id)
    for entity in entities:
        if entity.entity_type in {"social_account", "sensitive_account", "google_account", "email_registration"} \
                and entity.id in confirmed and entity.id not in included_account_ids:
            meta = _metadata(entity)
            accounts.append(_record(entity, entity_type=entity.entity_type, value=entity.value,
                ownership={"status": "subject_confirmed", "subject_asserted": True}, content_source=entity))
            included_account_ids.add(entity.id)

    declared_emails = {seed.value.lower(): seed for seed in seeds if seed.kind == "email"}
    declared_phones = {seed.value: seed for seed in seeds if seed.kind == "phone"}
    emails = [_record(None, entity_type="email", value=value, ownership={"status": "subject_declared",
              "subject_asserted": True, "seed_id": _seed_id(seed)}, seed_id=_seed_id(seed))
              for value, seed in declared_emails.items()]
    email_entity_ids: dict[str, UUID] = {}
    for entity in entities:
        if entity.entity_type == "email" and entity.id in confirmed and entity.value.lower() not in declared_emails:
            emails.append(_record(entity, entity_type="email", value=entity.value,
                ownership={"status": "subject_confirmed", "subject_asserted": True}))
            email_entity_ids[entity.value.lower()] = entity.id
    phones = [_record(None, entity_type="phone", value=value, ownership={"status": "subject_declared",
              "subject_asserted": True, "seed_id": _seed_id(seed)}, seed_id=_seed_id(seed))
              for value, seed in declared_phones.items()]
    for entity in entities:
        if entity.entity_type == "phone" and entity.id in confirmed and entity.value not in declared_phones:
            phones.append(_record(entity, entity_type="phone", value=entity.value,
                ownership={"status": "subject_confirmed", "subject_asserted": True}))

    academic_profiles = []
    confirmed_profile_ids = set()
    for entity in entities:
        if entity.id not in confirmed:
            continue
        if entity.entity_type == "academic_profile" or (entity.entity_type == "academic" and entity.platform == "openalex_author"):
            academic_profiles.append(_record(entity, entity_type="academic_profile", value=entity.value,
                ownership={"status": "subject_confirmed", "subject_asserted": True}))
            confirmed_profile_ids.add(entity.id)

    documents: list[ReviewedEntity] = []
    if confirmed_profile_ids:
        rels = (await db.scalars(select(Relationship).where(Relationship.investigation_id == investigation.id,
            Relationship.relation_type == "authored_work").order_by(Relationship.id))).all()
        for relationship in rels:
            profile_id = relationship.source_entity_id if relationship.source_entity_id in confirmed_profile_ids else relationship.target_entity_id if relationship.target_entity_id in confirmed_profile_ids else None
            if not profile_id:
                continue
            work_id = relationship.target_entity_id if profile_id == relationship.source_entity_id else relationship.source_entity_id
            work = entity_by_id.get(work_id)
            if work and work.entity_type == "academic" and work.platform == "research_paper":
                documents.append(_record(work, entity_type="academic_publication", value=work.value,
                    associated_profile=profile_id, authorship={"verified_by": "academic_engine", "relation": relationship.relation_type,
                        "evidence": relationship.evidence or {}}))

    attributed_emails = set(declared_emails) | set(email_entity_ids)
    breaches = []
    for entity in entities:
        if entity.entity_type != "breach":
            continue
        email = str(_metadata(entity).get("email") or entity.value).strip().lower()
        if email not in attributed_emails:
            continue
        breaches.append(BreachExposure(entity_id=entity.id, email=email,
            associated_email_entity_id=email_entity_ids.get(email), associated_declared_email=email in declared_emails,
            breaches=[item for item in _metadata(entity).get("breaches", []) if isinstance(item, str)][:100]
                if isinstance(_metadata(entity).get("breaches"), list) else [],
            provenance=_provenance(entity), evidence_urls=_urls(_metadata(entity).get("evidence_urls", []))))

    # Query association only: expose neither machine metadata nor credentials.
    attributed_aliases = {a.username.casefold() for a in accounts if a.username}
    attributed_aliases.update(seed.value.casefold() for seed in seeds if seed.kind == "username")
    infostealers = []
    for entity in entities:
        if entity.entity_type != "infostealer" or _provenance(entity).status in {"rejected", "uncertain"}:
            continue
        meta = _metadata(entity)
        kind = meta.get("queried_by")
        value = str(meta.get(kind) or "").strip().casefold() if kind in {"email", "username"} else ""
        allowed = attributed_emails if kind == "email" else attributed_aliases
        if value and value in allowed:
            infostealers.append(InfostealerExposure(entity_id=entity.id, identifier_kind=kind, identifier=value,
                provenance=_provenance(entity), evidence_urls=["https://www.hudsonrock.com/free-tools"]))

    social_content = []
    for account in entities:
        if account.id not in included_account_ids:
            continue
        for post in _safe_content(_metadata(account).get("public_content"), account):
            social_content.append(post)

    candidate_entities = [entity for entity in entities
                          if _reviewable_kind(entity, target) is not None or entity.id in decisions]
    decision_projection = _decision_records(candidate_entities, decisions)
    evidence = []
    for record in [*accounts, *emails, *phones, *academic_profiles, *documents]:
        if record.entity_id or record.evidence_urls:
            evidence.append({"entity_id": str(record.entity_id) if record.entity_id else None,
                "evidence_urls": record.evidence_urls, "source_tools": record.source_tools})
    for breach in breaches:
        evidence.append({"entity_id": str(breach.entity_id), "evidence_urls": breach.evidence_urls,
            "source_tools": [_source_label(_metadata(entity_by_id[breach.entity_id]).get("source_tool") or entity_by_id[breach.entity_id].source_tool)]})

    snapshot = (investigation.metrics or {}).get("fair_snapshot") or {}
    return ReviewedFootprintDataset(
        subject={"declared": [ReviewedDeclaredSeed(seed_id=_seed_id(seed), kind=seed.kind, value=seed.value,
            platform=seed.platform, provenance=seed.provenance) for seed in seeds]},
        accounts=accounts, emails=emails, phones=phones,
        academic_profiles=academic_profiles, documents=documents, breaches=breaches, infostealers=infostealers,
        social_content=social_content, review=decision_projection, evidence=evidence,
        execution={"source_investigation_id": str(investigation.id), "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "source_mode": "fair", "acquisition_partial": bool((snapshot.get("execution") or {}).get("partial")),
            "reviewed_candidate_ids": sorted(str(item.id) for item in (candidates or [])),
            "attribution_policy": "declared_and_human_confirmed_only"},
    )


async def reviewable_candidates(db: AsyncSession, investigation: Investigation, target: Target):
    response = await get_review_response(db, investigation, target)
    return response.candidates
