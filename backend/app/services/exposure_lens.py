"""Explainable privacy exposure analysis for a finalized reviewed footprint."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.exposure import ai as exposure_ai
from app.exposure.detectors import (
    BIO_ROLE_RE,
    CONTACT_URL_RE,
    EDU_WORK_RE,
    EMAIL_RE,
    FAMILY_REFERENCE_RE,
    SENSITIVE_SUBJECT_RE,
    TIME_RE,
    URL_RE,
    domain_from_url,
    exact_emails,
    exact_phones,
    explicit_context_signal,
    has_general_location,
    has_operational_routine,
    has_precise_address,
    has_temporal_disclosure,
    normalize_text,
    public_urls,
    safe_excerpt,
    safe_category_evidence,
)
from app.models.exposure_run import ExposureContentCache, ExposureRun
from app.models.investigation import Investigation
from app.models.target import Target
from app.schemas.exposure import (
    ExposureEvidence,
    ExposureFinding,
    ExposurePartialReason,
    ExposureReport,
    ExposureSeverity,
    ExposureSummary,
    ExposureTopItem,
)
from app.schemas.review import ReviewedEntity, ReviewedFootprintDataset
from app.services import verification_gate
from app.tools.social_profiles import parse_social_profile


ANALYSIS_VERSION = "exposure-v1"
SEVERITY_ORDER = {"informational": 0, "low": 1, "medium": 2, "high": 3}
CATEGORY_LABELS = {
    "contact_exposure": "contacto",
    "alias_reuse": "alias reutilizado",
    "cross_platform_correlation": "cuentas correlacionables",
    "location_disclosure": "ubicación general",
    "temporal_exposure": "referencias temporales",
    "education_work_context": "estudio o trabajo",
    "biographical_identifiers": "identificadores biográficos",
    "public_documents": "documentos públicos",
    "breach_exposure": "exposición en brechas",
    "infostealer_exposure": "registros de infostealer",
    "content_disclosure": "contenido público",
}
RECOMMENDATIONS = {
    "contact_exposure": [
        "Evita publicar tu correo principal en perfiles que no lo necesiten.",
        "Usa un canal de contacto separado para publicaciones abiertas.",
    ],
    "alias_reuse": ["Usa aliases distintos entre contextos que quieras mantener separados."],
    "cross_platform_correlation": [
        "Revisa enlaces y datos repetidos en perfiles que quieras mantener separados.",
        "Retira enlaces cruzados que ya no sean necesarios.",
    ],
    "location_disclosure": [
        "Reduce la precisión de ubicaciones y evita publicarlas en tiempo real.",
        "Revisa fotos y textos antes de publicarlos para quitar ubicaciones específicas.",
    ],
    "temporal_exposure": [
        "Publica eventos o viajes después de que hayan terminado.",
        "Evita compartir patrones temporales repetidos.",
    ],
    "education_work_context": [
        "Comparte solo la institución o cargo que sea necesario para ese perfil.",
    ],
    "biographical_identifiers": [
        "Revisa qué datos de tu biografía son necesarios en cada contexto.",
    ],
    "public_documents": [
        "Revisa documentos públicos antes de subirlos y elimina metadatos o datos innecesarios.",
    ],
    "breach_exposure": [
        "Usa contraseñas únicas.",
        "Cambia credenciales reutilizadas y activa MFA.",
        "Revisa los métodos de recuperación de tus cuentas.",
    ],
    "infostealer_exposure": [
        "Revisa tus equipos con herramientas de seguridad actualizadas.",
        "Desde un equipo seguro, revoca sesiones y cambia credenciales comprometidas.",
        "Activa MFA; un registro histórico no demuestra una infección actual.",
    ],
    "content_disclosure": [
        "Revisa el texto y los metadatos de publicaciones públicas antes de compartirlos.",
    ],
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _drop_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_volatile(item)
            for key, item in value.items()
            if key not in {"reviewed_at", "decided_at", "generated_at", "retrieved_at"}
        }
    if isinstance(value, list):
        normalized = [_drop_volatile(item) for item in value]
        return sorted(normalized, key=_canonical_json)
    return value


def dataset_hash(dataset: ReviewedFootprintDataset | dict[str, Any]) -> str:
    """Hash the normalized attributed data; decision timestamps are not content."""
    value = dataset.model_dump(mode="json") if isinstance(dataset, ReviewedFootprintDataset) else dataset
    return hashlib.sha256(_canonical_json(_drop_volatile(value)).encode("utf-8")).hexdigest()


def _analysis_config() -> tuple[dict[str, Any], str | None, str]:
    ai_enabled = bool(settings.exposure_ai_enabled)
    model = (settings.exposure_ai_model or settings.llm_model) if ai_enabled else None
    config = {
        "ai_enabled": ai_enabled,
        "model": model,
        "max_content_items": settings.exposure_max_content_items,
        "batch_size": settings.exposure_batch_size,
        "max_text_chars": settings.exposure_max_text_chars,
        "max_findings": settings.exposure_max_findings,
        "max_text_excerpt": settings.exposure_max_text_excerpt,
        "evidence_policy": "category-minimization-v2",
        "address_policy": "redact-specific-generalize-v1",
        "routine_policy": "do-not-synthesize-or-quote-v1",
        "sensitive_policy": "no-sensitive-traits-v1",
    }
    digest = hashlib.sha256(_canonical_json({"analysis_version": ANALYSIS_VERSION, **config}).encode()).hexdigest()
    return config, model, digest


async def _current_dataset(
    db: AsyncSession, investigation_id: UUID, *, lock: bool = False
) -> tuple[Investigation, ReviewedFootprintDataset, str]:
    statement = (
        select(Investigation)
        .where(Investigation.id == investigation_id)
        .options(selectinload(Investigation.target))
    )
    if lock:
        statement = statement.with_for_update()
    investigation = (await db.execute(statement)).scalar_one_or_none()
    if investigation is None:
        raise HTTPException(404, "Investigación no encontrada")
    metrics = investigation.metrics or {}
    if metrics.get("acquisition_mode") != "fair":
        raise HTTPException(404, "Exposure Lens solo está disponible para investigaciones Fair")
    if investigation.status != "completed" or investigation.completed_at is None:
        raise HTTPException(409, detail={
            "code": "review_not_finalized",
            "message": "La adquisición Fair debe terminar y la revisión debe finalizar antes de analizar exposición.",
        })

    gate = metrics.get("verification_gate") or {}
    raw_dataset = metrics.get("reviewed_footprint_dataset")
    if gate.get("status") != "complete" or not isinstance(raw_dataset, dict):
        raise HTTPException(409, detail={
            "code": "review_not_finalized",
            "message": "Finaliza Verification Gate para analizar únicamente la huella atribuida.",
        })
    response = await verification_gate.get_review_response(db, investigation, investigation.target)
    reviewed_ids = {str(item) for item in gate.get("reviewed_candidate_ids", [])}
    if response.review_status != "complete" or any(str(item.id) not in reviewed_ids for item in response.candidates):
        raise HTTPException(409, detail={
            "code": "review_not_finalized",
            "message": "Hay decisiones o descubrimientos nuevos; finaliza de nuevo Verification Gate.",
        })
    dataset = ReviewedFootprintDataset.model_validate(raw_dataset)
    return investigation, dataset, dataset_hash(dataset)


def _is_attributed(record: ReviewedEntity) -> bool:
    ownership = record.ownership if isinstance(record.ownership, dict) else {}
    ownership_status = ownership.get("status")
    status = record.provenance.status
    return ownership_status in {"subject_declared", "subject_confirmed"} and status not in {"rejected", "uncertain"}


def _id(record: ReviewedEntity) -> str | None:
    return str(record.entity_id) if record.entity_id else None


def _date_only(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    # Publication timestamps are retained only at day precision in the UI.
    return value[:10] if len(value) >= 10 else value[:32]


def _safe_report_text(value: Any, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    clean = normalize_text(value)
    if has_precise_address(clean):
        return "La fuente contiene una referencia de ubicación específica [redactada]."
    if has_operational_routine(clean):
        return "La fuente contiene referencias temporales repetidas [generalizadas]."
    clean = FAMILY_REFERENCE_RE.sub("[referencia familiar omitida]", clean)
    clean = SENSITIVE_SUBJECT_RE.sub("[tema sensible omitido]", clean)
    clean = TIME_RE.sub("[hora omitida]", clean)
    return clean[:limit]


def _safe_label(value: Any, limit: int = 120) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _safe_report_text(value, limit)


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        decoded = value
        # Decode nested encodings as well as separators used in URL paths.
        for _ in range(8):
            expanded = unquote(decoded)
            if expanded == decoded:
                break
            decoded = expanded
        else:
            return None
        decoded = re.sub(r"[+/_-]+", " ", decoded)
        if (has_precise_address(decoded) or has_operational_routine(decoded)
                or SENSITIVE_SUBJECT_RE.search(decoded) or FAMILY_REFERENCE_RE.search(decoded)):
            return None
        return parts._replace(query="", fragment="").geturl()
    except (ValueError, TypeError):
        return None


def _stable_content_id(item: dict[str, Any]) -> str:
    provided = item.get("id")
    if isinstance(provided, str) and provided.strip():
        return provided.strip()[:100]
    value = _canonical_json({"url": item.get("url"), "text": item.get("text") or item.get("caption") or item.get("title")})
    return "content-" + hashlib.sha256(value.encode()).hexdigest()[:24]


def _unit(
    *,
    content_id: str,
    source_id: str | None,
    source_content_id: str | None,
    source_type: str,
    content_type: str,
    platform: str | None,
    account: str | None,
    url: str | None,
    occurred_at: str | None,
    text: str,
) -> dict[str, Any] | None:
    value = normalize_text(text)
    if not value:
        return None
    return {
        "content_id": content_id[:100],
        "source_id": source_id,
        "source_content_id": source_content_id,
        "source_type": source_type,
        "content_type": content_type,
        "platform": _safe_label(platform, 100),
        "account": _safe_label(account, 100),
        "url": _safe_url(url),
        "occurred_at": _date_only(occurred_at),
        "text": value,
    }


def _units(dataset: ReviewedFootprintDataset, accounts: list[ReviewedEntity]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    allowed_ids = {_id(account) for account in accounts if _id(account)}
    account_by_id = {_id(account): account for account in accounts if _id(account)}

    for account in accounts:
        entity_id = _id(account)
        text = account.bio or ""
        if account.display_name:
            text = f"{account.display_name}. {text}"
        profile_unit = _unit(
            content_id=f"profile:{entity_id or account.seed_id or account.value}",
            source_id=entity_id or account.seed_id,
            source_content_id=None,
            source_type="entity",
            content_type="profile_bio",
            platform=account.platform,
            account=account.username,
            url=account.profile_url,
            occurred_at=None,
            text=text,
        )
        if profile_unit:
            result.append(profile_unit)

    for item in dataset.social_content:
        if not isinstance(item, dict):
            continue
        account_id = str(item.get("account_entity_id") or "")
        if account_id not in allowed_ids:
            continue
        account = account_by_id[account_id]
        body = " ".join(
            str(item.get(key) or "")
            for key in ("text", "caption", "title", "description")
            if isinstance(item.get(key), str)
        )
        stable_id = _stable_content_id(item)
        unit = _unit(
            content_id=f"post:{hashlib.sha256(stable_id.encode()).hexdigest()[:32]}",
            source_id=account_id,
            source_content_id=stable_id,
            source_type="content",
            content_type="social_post",
            platform=str(item.get("account_platform") or account.platform or ""),
            account=str(item.get("account_username") or account.username or ""),
            url=item.get("url"),
            occurred_at=item.get("posted_at") or item.get("published_at") or item.get("timestamp"),
            text=body,
        )
        if unit:
            result.append(unit)

    for profile in dataset.academic_profiles:
        if profile.provenance.status not in {"declared", "confirmed"}:
            continue
        value = " ".join(part for part in (profile.display_name, profile.value, profile.bio) if part)
        unit = _unit(
            content_id=f"academic:{_id(profile) or profile.seed_id or profile.value}",
            source_id=_id(profile),
            source_content_id=None,
            source_type="entity",
            content_type="academic_profile",
            platform=profile.platform,
            account=profile.username or profile.display_name,
            url=profile.profile_url,
            occurred_at=None,
            text=value,
        )
        if unit:
            result.append(unit)

    for document in dataset.documents:
        value = " ".join(part for part in (document.display_name, document.value, document.bio) if part)
        unit = _unit(
            content_id=f"document:{_id(document) or document.value}",
            source_id=_id(document),
            source_content_id=None,
            source_type="document",
            content_type="public_document",
            platform=document.platform,
            account=document.display_name,
            url=document.profile_url or (document.evidence_urls[0] if document.evidence_urls else None),
            occurred_at=None,
            text=value,
        )
        if unit:
            result.append(unit)
    return result


def _priority(unit: dict[str, Any]) -> int:
    text = str(unit["text"])
    score = 0
    if EMAIL_RE.search(text):
        score += 10
    if exact_phones(text):
        score += 10
    if URL_RE.search(text) or CONTACT_URL_RE.search(text):
        score += 4
    if has_precise_address(text) or has_general_location(text):
        score += 6
    if has_temporal_disclosure(text):
        score += 4
    if EDU_WORK_RE.search(text) or BIO_ROLE_RE.search(text):
        score += 4
    return score


def _select_units(units: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    prioritized = sorted(units, key=lambda item: (-_priority(item), item["content_id"]))
    max_items = settings.exposure_max_content_items
    remaining = settings.exposure_max_text_chars
    selected: list[dict[str, Any]] = []
    skipped = 0
    for unit in prioritized:
        if len(selected) >= max_items or remaining <= 0:
            skipped += 1
            continue
        text = str(unit["text"])
        if len(text) > remaining:
            clipped = dict(unit)
            clipped["text"] = text[:remaining]
            selected.append(clipped)
            remaining = 0
            skipped += 1
        else:
            selected.append(unit)
            remaining -= len(text)
    return selected, skipped


def _signal(category: str, severity: ExposureSeverity, excerpt: str, method: str = "deterministic") -> dict[str, str]:
    return {
        "category": category,
        "severity": severity,
        "basis": "observed",
        "excerpt": excerpt[: settings.exposure_max_text_excerpt],
        "method": method,
    }


def _local_signals(unit: dict[str, Any]) -> list[dict[str, str]]:
    text = str(unit["text"])
    signals: list[dict[str, str]] = []
    if has_precise_address(text):
        signals.append(_signal("location_disclosure", "high",
            "La fuente contiene una referencia de ubicación específica [redactada]."))
    elif has_general_location(text):
        signals.append(_signal("location_disclosure", "medium", safe_category_evidence("location_disclosure", text, settings.exposure_max_text_excerpt)))
    if has_temporal_disclosure(text):
        severity: ExposureSeverity = "medium" if has_operational_routine(text) or re.search(
            r"\b(?:trip|travel|viaje|viajando|visitando|vacation|vacaciones|event|evento)\b", text, re.I
        ) else "low"
        excerpt = safe_category_evidence("temporal_exposure", text, settings.exposure_max_text_excerpt)
        signals.append(_signal("temporal_exposure", severity, excerpt))
    if EDU_WORK_RE.search(text):
        signals.append(_signal("education_work_context", "medium", safe_category_evidence("education_work_context", text, settings.exposure_max_text_excerpt)))
    if BIO_ROLE_RE.search(text):
        signals.append(_signal("biographical_identifiers", "low", safe_category_evidence("biographical_identifiers", text, settings.exposure_max_text_excerpt)))
    return signals


def _unit_hash(unit: dict[str, Any]) -> str:
    source = _canonical_json({
        "analysis_version": ANALYSIS_VERSION,
        "content_type": unit["content_type"],
        "text": _drop_volatile(unit["text"]),
    })
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


async def _cached_content_signals(
    db: AsyncSession,
    units: list[dict[str, Any]],
    config_hash: str,
    model: str | None,
) -> tuple[dict[str, list[dict[str, str]]], int, bool]:
    hashes_by_unit = {unit["content_id"]: _unit_hash(unit) for unit in units}
    unique_hashes = list(dict.fromkeys(hashes_by_unit.values()))
    cached_rows = (await db.scalars(select(ExposureContentCache).where(
        ExposureContentCache.analysis_version == ANALYSIS_VERSION,
        ExposureContentCache.config_hash == config_hash,
        ExposureContentCache.content_hash.in_(unique_hashes),
    ))).all() if unique_hashes else []
    cached = {row.content_hash: row.result for row in cached_rows}
    result: dict[str, list[dict[str, str]]] = {}
    misses_by_hash: dict[str, dict[str, Any]] = {}
    for unit in units:
        digest = hashes_by_unit[unit["content_id"]]
        if digest in cached:
            result[unit["content_id"]] = cached[digest]
        else:
            misses_by_hash.setdefault(digest, unit)
    misses = list(misses_by_hash.values())

    ai_failed = False
    ai_results: dict[str, list[dict[str, Any]]] = {}
    if settings.exposure_ai_enabled and misses:
        if not model:
            ai_failed = True
        else:
            for start in range(0, len(misses), settings.exposure_batch_size):
                batch = misses[start : start + settings.exposure_batch_size]
                try:
                    ai_results.update(await exposure_ai.classify_batch(
                        model,
                        batch,
                        max_chars_per_item=min(6000, settings.exposure_max_text_chars),
                    ))
                except Exception:
                    ai_failed = True

    cache_rows: list[dict[str, Any]] = []
    failed_unit_ids: set[str] = set()
    # A batch failure means its units must remain uncached so a later run can retry AI.
    if ai_failed:
        failed_unit_ids = {unit["content_id"] for unit in misses}
    for unit in misses:
        signals = _local_signals(unit)
        for raw in ai_results.get(unit["content_id"], []):
            category = raw.get("category")
            if category not in {
                "location_disclosure", "temporal_exposure", "education_work_context",
                "biographical_identifiers", "content_disclosure",
            }:
                continue
            # Severity is constrained by documented local impact criteria.
            ai_severity: ExposureSeverity = {
                "location_disclosure": "medium",
                "temporal_exposure": "low",
                "education_work_context": "medium",
                "biographical_identifiers": "low",
                "content_disclosure": "low",
            }[category]
            if any(item["category"] == category for item in signals):
                continue
            signals.append(_signal(category, ai_severity, safe_category_evidence(
                category, str(unit["text"]), settings.exposure_max_text_excerpt), "ai"))
        # Content cache stores only safe classifications and bounded excerpts.
        encoded = _canonical_json(signals)
        decoded = json.loads(encoded)
        result[unit["content_id"]] = decoded
        if unit["content_id"] not in failed_unit_ids:
            cache_rows.append({
                "id": UUID(bytes=hashlib.md5(
                    f"{hashes_by_unit[unit['content_id']]}:{config_hash}".encode(), usedforsecurity=False
                ).digest()),
                "content_hash": hashes_by_unit[unit["content_id"]],
                "analysis_version": ANALYSIS_VERSION,
                "config_hash": config_hash,
                "model": model,
                "result": decoded,
            })
    for unit in units:
        digest = hashes_by_unit[unit["content_id"]]
        if unit["content_id"] not in result:
            representative = misses_by_hash.get(digest)
            result[unit["content_id"]] = (
                result.get(representative["content_id"], []) if representative else cached.get(digest, [])
            )
    if cache_rows:
        statement = pg_insert(ExposureContentCache).values(cache_rows).on_conflict_do_nothing(
            constraint="uq_exposure_content_cache_key"
        )
        await db.execute(statement)
    return result, len(cached), ai_failed


def _evidence(
    unit: dict[str, Any],
    excerpt: str | None = None,
    *,
    source_type: str | None = None,
    source_id: str | None = None,
    url: str | None = None,
) -> dict[str, Any]:
    return {
        "source_type": source_type or unit.get("source_type") or "content",
        "source_id": source_id or unit.get("source_content_id") or unit.get("source_id"),
        "platform": unit.get("platform"),
        "account": unit.get("account"),
        "url": _safe_url(url if url is not None else unit.get("url")),
        "occurred_at": unit.get("occurred_at"),
        "excerpt": (excerpt if excerpt is not None else safe_excerpt(
            str(unit.get("text") or ""), settings.exposure_max_text_excerpt
        ))[:280],
    }


class _Collector:
    def __init__(self):
        self.rows: dict[str, dict[str, Any]] = {}

    def add(
        self,
        category: str,
        key: str,
        severity: ExposureSeverity,
        title: str,
        summary: str,
        why: str,
        evidence: list[dict[str, Any]],
        entity_ids: list[str | None] | None = None,
        content_ids: list[str | None] | None = None,
        signals: list[str] | None = None,
        method: str = "deterministic",
        basis: str = "observed",
    ):
        stable = hashlib.sha256(f"{ANALYSIS_VERSION}:{category}:{key}".encode()).hexdigest()[:24]
        finding_id = f"exp_{stable}"
        row = self.rows.get(finding_id)
        if row is None:
            self.rows[finding_id] = {
                "id": finding_id,
                "category": category,
                "severity": severity,
                "title": _safe_report_text(title, 160),
                "summary": _safe_report_text(summary, 500),
                "why_it_matters": _safe_report_text(why, 500),
                "evidence": [],
                "source_entity_ids": [],
                "source_content_ids": [],
                "recommendations": RECOMMENDATIONS.get(category, [])[:8],
                "basis": basis,
                "analysis_method": method,
                "signals": [],
            }
            row = self.rows[finding_id]
        elif SEVERITY_ORDER[severity] > SEVERITY_ORDER[row["severity"]]:
            row["severity"] = severity
        for item in evidence:
            clean = ExposureEvidence.model_validate(item).model_dump(mode="json")
            clean["platform"] = _safe_label(clean.get("platform"), 100)
            clean["account"] = _safe_label(clean.get("account"), 120)
            clean["url"] = _safe_url(clean.get("url"))
            clean["excerpt"] = _safe_report_text(clean.get("excerpt", ""), 280)
            if clean not in row["evidence"] and len(row["evidence"]) < 20:
                row["evidence"].append(clean)
        for target, values in (
            ("source_entity_ids", entity_ids or []),
            ("source_content_ids", content_ids or []),
            ("signals", signals or []),
        ):
            for value in values:
                if value is not None and value not in row[target] and len(row[target]) < 100:
                    row[target].append(value)
        if basis == "inferred":
            row["basis"] = "inferred"
        if method == "deterministic":
            row["analysis_method"] = "deterministic"

    def ordered(self, limit: int) -> list[ExposureFinding]:
        values = sorted(
            self.rows.values(),
            key=lambda item: (-SEVERITY_ORDER[item["severity"]], item["category"], item["id"]),
        )[:limit]
        return [ExposureFinding.model_validate(value) for value in values]


def _entity_unit(record: ReviewedEntity, content_type: str) -> dict[str, Any]:
    return {
        "content_id": f"entity:{_id(record) or record.seed_id or record.value}",
        "source_id": _id(record),
        "source_content_id": None,
        "source_type": "document" if content_type == "public_document" else "entity",
        "content_type": content_type,
        "platform": record.platform,
        "account": record.username or record.display_name,
        "url": _safe_url(record.profile_url or (record.evidence_urls[0] if record.evidence_urls else None)),
        "occurred_at": None,
        "text": normalize_text(" ".join(part for part in (record.display_name, record.value, record.bio) if part)),
    }


def _alias_and_profile_findings(
    collector: _Collector,
    accounts: list[ReviewedEntity],
    units: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], set[tuple[str, str]]]:
    aliases: dict[str, list[ReviewedEntity]] = defaultdict(list)
    biographies: dict[str, list[ReviewedEntity]] = defaultdict(list)
    for account in accounts:
        if account.username:
            aliases[account.username.casefold()].append(account)
        name = normalize_text(account.display_name or "")
        if name and (not account.username or name.casefold() != account.username.casefold()):
            biographies[name.casefold()].append(account)

    for normalized, rows in aliases.items():
        platforms = sorted({(item.platform or "perfil público").strip() for item in rows})
        entity_ids = [_id(item) for item in rows]
        if len(platforms) < 2:
            continue
        evidence = [
            {
                "source_type": "entity", "source_id": _id(item), "platform": item.platform,
                "account": f"@{item.username}", "url": _safe_url(item.profile_url),
                "excerpt": f"El alias @{item.username} figura en {item.platform or 'un perfil público'}.",
            }
            for item in rows
        ]
        collector.add(
            "alias_reuse", normalized, "medium", "Alias reutilizado entre plataformas",
            f"El alias @{rows[0].username} aparece en {len(platforms)} plataformas atribuidas: {', '.join(platforms)}.",
            "Repetir un alias facilita relacionar cuentas. La coincidencia se limita a cuentas declaradas o confirmadas.",
            evidence, entity_ids=entity_ids, signals=["mismo_alias", *platforms],
        )

    for name, rows in biographies.items():
        evidence = [
            {"source_type": "entity", "source_id": _id(item), "platform": item.platform,
             "account": item.username or item.display_name, "url": _safe_url(item.profile_url),
             "excerpt": safe_excerpt(item.display_name or "", settings.exposure_max_text_excerpt)}
            for item in rows
        ]
        collector.add(
            "biographical_identifiers", name, "low", "Nombre visible en un perfil atribuido",
            f"El nombre público «{rows[0].display_name}» aparece en {len(rows)} perfil(es) atribuido(s).",
            "Un nombre visible facilita asociar una cuenta con información pública de otros contextos.",
            evidence, entity_ids=[_id(item) for item in rows], signals=["nombre_visible"],
        )

    # Account/profile links are parsed only after the Verification Gate has
    # selected these accounts. No raw candidates or unconfirmed entities enter.
    account_by_key: dict[tuple[str, str], ReviewedEntity] = {}
    for account in accounts:
        if account.username and account.platform:
            account_by_key[(account.platform.casefold(), account.username.casefold())] = account
    cross_link_pairs: set[tuple[str, str]] = set()
    for unit in units:
        source_id = unit.get("source_id")
        source = next((item for item in accounts if _id(item) == source_id), None)
        if source is None:
            continue
        for url in public_urls(str(unit.get("text") or "")):
            target_profile = parse_social_profile(url)
            if not target_profile:
                continue
            target = account_by_key.get((target_profile.platform.casefold(), target_profile.username.casefold()))
            if target is None or _id(target) == source_id:
                continue
            target_id = _id(target)
            if not source_id or not target_id:
                continue
            pair = tuple(sorted((source_id, target_id)))
            cross_link_pairs.add(pair)
            collector.add(
                "cross_platform_correlation", f"cross-link:{pair[0]}:{pair[1]}", "medium",
                "Un perfil enlaza a otra cuenta atribuida",
                f"El perfil {source.platform or 'público'} incluye un enlace directo a la cuenta {target.platform or 'pública'}.",
                "El enlace cruzado permite relacionar explícitamente ambos perfiles.",
                [_evidence(unit, "La fuente contiene un enlace directo entre perfiles atribuidos.", url=url),
                 {"source_type": "entity", "source_id": target_id, "platform": target.platform,
                  "account": f"@{target.username}" if target.username else target.display_name,
                  "url": _safe_url(target.profile_url), "excerpt": "Cuenta atribuida enlazada directamente."}],
                entity_ids=[source_id, target_id],
                content_ids=[unit.get("source_content_id")],
                signals=["enlace_explicito"],
            )
    return aliases, cross_link_pairs


def _document_findings(collector: _Collector, documents: list[ReviewedEntity]) -> None:
    for document in documents:
        if not document.entity_id:
            continue
        text = " ".join(part for part in (document.display_name, document.value, document.bio) if part)
        emails = exact_emails(text)
        phones = exact_phones(text)
        identifier_count = int(bool(document.display_name)) + len(emails) + len(phones) + int(bool(EDU_WORK_RE.search(text)))
        severity: ExposureSeverity = "medium" if identifier_count >= 3 else "low"
        evidence = [{
            "source_type": "document", "source_id": str(document.entity_id), "platform": document.platform,
            "account": document.display_name, "url": _safe_url(document.profile_url or (
                document.evidence_urls[0] if document.evidence_urls else None
            )), "excerpt": safe_excerpt(text, settings.exposure_max_text_excerpt),
        }]
        collector.add(
            "public_documents", str(document.entity_id), severity, "Documento público con identificadores visibles",
            "Una publicación académica o documento atribuido contiene metadatos públicos que permiten reconocer su contexto.",
            "El documento puede exponer nombre, afiliación o contacto a través de su título, ficha o versión pública.",
            evidence, entity_ids=[str(document.entity_id)], signals=[
                signal for signal, present in (
                    ("nombre", bool(document.display_name)),
                    ("contacto", bool(emails or phones)),
                    ("contexto institucional", bool(EDU_WORK_RE.search(text))),
                    ("enlace público", bool(document.profile_url or document.evidence_urls)),
                ) if present
            ],
        )


def _profile_contact_sources(
    units: list[dict[str, Any]],
    collector: _Collector,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    emails: dict[str, list[dict[str, Any]]] = defaultdict(list)
    phones: dict[str, list[dict[str, Any]]] = defaultdict(list)
    domains: dict[str, list[dict[str, Any]]] = defaultdict(list)
    contact_links: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in units:
        text = str(unit["text"])
        for email in exact_emails(text):
            emails[email].append(_evidence(unit, f"Correo público visible: {email}"))
        for phone in exact_phones(text):
            phones[phone].append(_evidence(unit, f"Teléfono público visible: {phone}"))
        for url in public_urls(text):
            domain = domain_from_url(url)
            if domain:
                domains[domain].append(_evidence(unit, "Enlace a dominio personal visible.", url=url))
            if CONTACT_URL_RE.search(url):
                contact_links[url].append(_evidence(unit, "La fuente incluye un enlace público de contacto.", url=url))
        # mailto/tel and platform contact links may not be valid http URLs.
        for match in CONTACT_URL_RE.finditer(text):
            fragment = text[match.start() : match.start() + 240].split()[0].rstrip(".,;:!?)]}")
            if fragment:
                contact_links[fragment].append(_evidence(unit, "La fuente incluye un enlace público de contacto."))

    for email, evidence in emails.items():
        collector.add(
            "contact_exposure", f"email:{email}", "medium", "Correo electrónico visible públicamente",
            f"El correo {email} aparece en {len(evidence)} fuente(s) públicas atribuida(s).",
            "Un correo público puede facilitar contacto no deseado y correlación entre servicios.",
            evidence[:20],
            entity_ids=[item["source_id"] for item in evidence if item.get("source_type") in {"entity", "document"}],
            content_ids=[item["source_id"] for item in evidence if item.get("source_type") == "content"],
            signals=["correo_visible"],
        )
    for phone, evidence in phones.items():
        collector.add(
            "contact_exposure", f"phone:{phone}", "high", "Teléfono visible públicamente",
            f"El teléfono {phone} aparece en {len(evidence)} fuente(s) públicas atribuida(s).",
            "Un teléfono público es un identificador de contacto directo y puede facilitar spam o intentos de suplantación.",
            evidence[:20],
            entity_ids=[item["source_id"] for item in evidence if item.get("source_type") in {"entity", "document"}],
            content_ids=[item["source_id"] for item in evidence if item.get("source_type") == "content"],
            signals=["telefono_visible"],
        )
    for link, evidence in contact_links.items():
        collector.add(
            "contact_exposure", f"link:{link}", "low", "Enlace público de contacto",
            "Una fuente atribuida ofrece un enlace directo de contacto.",
            "Los enlaces de contacto permiten llegar a un canal directo desde un perfil abierto.",
            evidence[:20],
            entity_ids=[item["source_id"] for item in evidence if item.get("source_type") in {"entity", "document"}],
            content_ids=[item["source_id"] for item in evidence if item.get("source_type") == "content"],
            signals=["enlace_contacto"],
        )
    for domain, evidence in domains.items():
        sources = {item.get("source_id") for item in evidence if item.get("source_id")}
        platforms = {item.get("platform") for item in evidence if item.get("platform")}
        if len(sources) < 2:
            continue
        collector.add(
            "cross_platform_correlation", f"domain:{domain}", "medium", "Dominio personal enlazado desde varias fuentes",
            f"El dominio {domain} aparece enlazado desde {len(sources)} fuentes atribuidas.",
            "Un dominio personal repetido facilita navegar entre perfiles y otros materiales públicos.",
            evidence[:20], entity_ids=list(sources), signals=["mismo_dominio", *sorted(platforms)],
        )
    return emails, phones, domains


def _content_and_document_signals(
    collector: _Collector,
    units: list[dict[str, Any]],
    unit_signals: dict[str, list[dict[str, str]]],
) -> list[ExposureTopItem]:
    top: list[ExposureTopItem] = []
    for unit in units:
        signals = unit_signals.get(unit["content_id"], [])
        if not signals:
            continue
        if unit["content_type"] == "social_post":
            categories = list(dict.fromkeys(item["category"] for item in signals))
            severity = max((item["severity"] for item in signals), key=lambda value: SEVERITY_ORDER[value])
            labels = [CATEGORY_LABELS.get(category, category) for category in categories]
            content_id = unit.get("source_content_id")
            excerpt = next((item["excerpt"] for item in signals if item["category"] != "content_disclosure"),
                           safe_category_evidence("content_disclosure", "", settings.exposure_max_text_excerpt))
            evidence = _evidence(unit, excerpt)
            collector.add(
                "content_disclosure", unit["content_id"], severity, "Publicación con señales de exposición",
                f"La publicación reúne señales visibles de {', '.join(labels)}.",
                "La combinación de datos publicados puede facilitar la correlación de perfiles o revelar contexto personal.",
                [evidence], entity_ids=[unit.get("source_id")], content_ids=[content_id],
                signals=categories,
                method="deterministic" if any(item["method"] == "deterministic" for item in signals) else "ai",
            )
            top.append(ExposureTopItem(
                id=f"top_{hashlib.sha256(unit['content_id'].encode()).hexdigest()[:20]}",
                platform=unit.get("platform"),
                account=unit.get("account"),
                published_at=unit.get("occurred_at"),
                excerpt=excerpt[:280],
                severity=severity,
                reveals=labels,
                why_it_matters="La publicación deja señales públicas que pueden correlacionarse con otras fuentes.",
                evidence=[ExposureEvidence.model_validate(evidence)],
                recommendations=RECOMMENDATIONS["content_disclosure"],
            ))
        for signal in signals:
            if signal["category"] == "content_disclosure":
                continue
            collector.add(
                signal["category"], f"{unit['content_id']}:{signal['category']}",
                signal["severity"], {
                    "location_disclosure": "Ubicación general visible en una fuente",
                    "temporal_exposure": "Referencia temporal visible en una fuente",
                    "education_work_context": "Contexto de estudio o trabajo visible",
                    "biographical_identifiers": "Detalle biográfico visible en una fuente",
                }.get(signal["category"], "Señal de exposición observada"),
                {
                    "location_disclosure": "Una publicación revela una ubicación específica." if has_precise_address(unit["text"]) else "Una publicación revela una ubicación a nivel general.",
                    "temporal_exposure": "Varias publicaciones o una fuente contienen referencias temporales públicas.",
                    "education_work_context": "Una publicación o perfil menciona explícitamente un contexto de estudio o trabajo.",
                    "biographical_identifiers": "Una fuente muestra explícitamente un cargo o identificador biográfico.",
                }.get(signal["category"], "La fuente contiene una señal pública observada."),
                {
                    "location_disclosure": "Una ubicación más precisa puede reducir la privacidad; aquí se generalizó la referencia.",
                    "temporal_exposure": "Las referencias temporales pueden revelar contexto; el informe no sintetiza horarios.",
                    "education_work_context": "La institución o empresa puede ayudar a relacionar perfiles públicos.",
                    "biographical_identifiers": "Los detalles biográficos pueden hacer más fácil asociar perfiles.",
                }.get(signal["category"], "La señal puede facilitar correlación con otras fuentes."),
                [_evidence(unit, signal["excerpt"])],
                entity_ids=[unit.get("source_id")],
                content_ids=[unit.get("source_content_id")],
                method=signal["method"],
            )
    return sorted(top, key=lambda item: (-SEVERITY_ORDER[item.severity], item.platform or "", item.id))[:20]


def _infostealer_findings(collector: _Collector, dataset: ReviewedFootprintDataset):
    allowed = {("email", item.value.casefold()) for item in dataset.emails if _is_attributed(item)}
    allowed.update(("username", a.username.casefold()) for a in dataset.accounts if _is_attributed(a) and a.username)
    allowed.update((seed.kind, seed.value.casefold()) for seed in dataset.subject.get("declared", [])
                   if seed.kind in {"email", "username"} and seed.provenance.origin == "subject" and seed.provenance.status == "declared")
    for item in sorted(dataset.infostealers, key=lambda item: str(item.entity_id)):
        if ((item.identifier_kind, item.identifier.casefold()) not in allowed
                or item.provenance.status in {"rejected", "uncertain"}):
            continue
        collector.add("infostealer_exposure", str(item.entity_id), "medium",
            "Identificador presente en un registro de infostealer",
            "Un identificador atribuido aparece asociado a un registro de malware que roba credenciales.",
            "Es un registro de exposición; no prueba ownership ni una infección actual del equipo.",
            [{"source_type": "infostealer", "source_id": str(item.entity_id), "platform": "hudson_rock",
              "account": None, "url": "https://www.hudsonrock.com/free-tools", "occurred_at": None,
              "excerpt": "Registro de exposición por infostealer asociado a un identificador atribuido. No prueba identidad ni infección actual."}],
            entity_ids=[str(item.entity_id)], signals=["infostealer_registry_observation", "exposure_not_identity_proof"])


def _breach_findings(
    collector: _Collector,
    dataset: ReviewedFootprintDataset,
    public_emails: dict[str, list[dict[str, Any]]],
) -> set[str]:
    attributable_emails = {
        item.value.strip().lower()
        for item in dataset.emails
        if item.ownership.get("status") in {"subject_declared", "subject_confirmed"}
        and item.provenance.status not in {"rejected", "uncertain"}
    }
    by_email: dict[str, list[Any]] = defaultdict(list)
    for breach in dataset.breaches:
        email = breach.email.strip().lower()
        if (email and email in attributable_emails
                and breach.semantics == "exposure_observed_not_identity_proof"):
            by_email[email].append(breach)
    emails_with_breaches: set[str] = set()
    for email, breaches in by_email.items():
        emails_with_breaches.add(email)
        unique_names = list(dict.fromkeys(
            name.strip()[:160] for item in breaches for name in item.breaches if isinstance(name, str) and name.strip()
        ))[:10]
        sources = []
        for item in breaches:
            sources.append({
                "source_type": "breach",
                "source_id": str(item.entity_id),
                "platform": None,
                "account": email,
                "url": next((_safe_url(url) for url in item.evidence_urls if _safe_url(url)), None),
                "occurred_at": None,
                "excerpt": (
                    f"Correo {email} presente en {len(unique_names) or len(breaches)} registro(s) de brecha."
                    + (f" Fuentes: {', '.join(unique_names[:3])}." if unique_names else "")
                    + " Exposición observada; no prueba identidad."
                )[:280],
            })
        public_match = email in public_emails
        severity: ExposureSeverity = "high" if public_match else "medium"
        suffix = (
            " Además, el mismo correo aparece públicamente en una fuente atribuida."
            if public_match else ""
        )
        collector.add(
            "breach_exposure", email, severity,
            "Correo público presente en registros de brecha" if public_match else "Correo presente en registros de brecha",
            f"El correo {email} aparece en {len(breaches)} registro(s) de brecha.{suffix}",
            "La exposición en una brecha no demuestra quién controlaba la cuenta. Revisa si reutilizaste credenciales y protege las cuentas actuales.",
            sources[:20],
            entity_ids=[str(item.entity_id) for item in breaches],
            signals=["email_exact_match_public" if public_match else "breach_email_observed",
                     "breach_exposure_is_not_identity_proof"],
        )
        if public_match:
            public = public_emails[email]
            collector.add(
                "cross_platform_correlation", f"public-breach-email:{email}", "high",
                "Correo visible y coincidente con una brecha",
                f"El mismo string de correo {email} aparece en una fuente pública atribuida y en {len(breaches)} registro(s) de brecha.",
                "La coincidencia exacta facilita correlacionar publicaciones y el aviso de brecha. La brecha no es prueba de identidad.",
                [*public[:10], *sources[:10]],
                entity_ids=[str(item.entity_id) for item in breaches] + [
                    item.get("source_id") for item in public if item.get("source_type") in {"entity", "document"}
                ],
                content_ids=[item.get("source_id") for item in public if item.get("source_type") == "content"],
                signals=["mismo_email_exacto", "correo_publico", "breach_exposure"],
            )
    return emails_with_breaches


def _email_cross_account(
    collector: _Collector,
    emails: dict[str, list[dict[str, Any]]],
) -> None:
    for email, evidence in emails.items():
        platforms = {item.get("platform") for item in evidence if item.get("platform")}
        sources = {item.get("source_id") for item in evidence if item.get("source_id")}
        if len(sources) < 2 or len(platforms) < 2:
            continue
        collector.add(
            "cross_platform_correlation", f"public-email:{email}", "medium",
            "Mismo correo visible en varias plataformas",
            f"El mismo correo aparece en {len(platforms)} plataformas y {len(sources)} fuentes atribuidas.",
            "La repetición exacta del correo permite relacionar perfiles aunque usen nombres distintos.",
            evidence[:20], entity_ids=list(sources),
            content_ids=[item.get("source_id") for item in evidence if item.get("source_type") == "content"],
            signals=["mismo_email_exacto", *sorted(str(item) for item in platforms)],
        )


def _combined_alias_email_link(
    collector: _Collector,
    accounts: list[ReviewedEntity],
    emails: dict[str, list[dict[str, Any]]],
    cross_link_pairs: set[tuple[str, str]],
) -> None:
    aliases: dict[str, list[ReviewedEntity]] = defaultdict(list)
    for account in accounts:
        if account.username and account.entity_id:
            aliases[account.username.casefold()].append(account)
    for alias, rows in aliases.items():
        ids = {str(item.entity_id) for item in rows}
        if len(ids) < 2 or not any(pair[0] in ids and pair[1] in ids for pair in cross_link_pairs):
            continue
        shared_email = next((
            email for email, evidence in emails.items()
            if len({item.get("source_id") for item in evidence if item.get("source_id")} & ids) >= 2
        ), None)
        if not shared_email:
            continue
        evidence = []
        evidence.extend(
            {"source_type": "entity", "source_id": _id(item), "platform": item.platform,
             "account": f"@{item.username}", "url": _safe_url(item.profile_url),
             "excerpt": f"Alias @{item.username} observado en {item.platform or 'perfil público'}."}
            for item in rows
        )
        evidence.extend(item for item in emails[shared_email] if item.get("source_id") in ids)
        collector.add(
            "cross_platform_correlation", f"combined:{alias}:{shared_email}", "high",
            "Varias señales públicas conectan cuentas atribuidas",
            f"Se combinan el alias @{rows[0].username}, el mismo correo público {shared_email} y un enlace cruzado explícito.",
            "Cada señal puede verificarse en sus fuentes. En conjunto hacen más sencilla la correlación entre perfiles; no se calcula una probabilidad de identidad.",
            evidence[:20], entity_ids=list(ids),
            content_ids=[item.get("source_id") for item in evidence if item.get("source_type") == "content"],
            signals=["mismo_alias", "mismo_email_exacto", "enlace_explicito"],
        )


def _report_data(
    investigation_id: UUID,
    data_hash: str,
    status: str,
    findings: list[ExposureFinding],
    top: list[ExposureTopItem],
    analyzed: int,
    skipped: int,
    model: str | None,
    config: dict[str, Any],
    *,
    partial_reasons: list[ExposurePartialReason] | None = None,
    cache_hit: bool = False,
    generated_at: datetime | None = None,
) -> ExposureReport:
    severity_counts = {name: 0 for name in SEVERITY_ORDER}
    category_counts = {category: 0 for category in CATEGORY_LABELS}
    for finding in findings:
        severity_counts[finding.severity] += 1
        category_counts[finding.category] += 1
    return ExposureReport(
        investigation_id=str(investigation_id),
        dataset_hash=data_hash,
        current_dataset_hash=data_hash,
        analysis_version=ANALYSIS_VERSION,
        status=status,
        partial_reasons=partial_reasons or [],
        cache_hit=cache_hit,
        summary=ExposureSummary(**severity_counts),
        categories=category_counts,
        findings=findings,
        top_exposures=top,
        analyzed_content_count=analyzed,
        skipped_content_count=skipped,
        generated_at=generated_at,
        model=model,
        config=config,
    )


async def _build_analysis(
    db: AsyncSession,
    investigation_id: UUID,
    dataset: ReviewedFootprintDataset,
    data_hash: str,
    config: dict[str, Any],
    model: str | None,
    config_hash: str,
) -> ExposureReport:
    accounts = [item for item in dataset.accounts if _is_attributed(item)]
    units = _units(dataset, accounts)
    selected, skipped = _select_units(units)
    unit_signals, cache_hits, ai_failed = await _cached_content_signals(
        db, selected, config_hash, model
    )
    collector = _Collector()

    aliases, cross_links = _alias_and_profile_findings(collector, accounts, selected)
    del aliases  # The exact alias groups are represented by their findings.

    # Public academic documents are included only because the finalized dataset
    # already tied them to a confirmed academic profile.
    documents = [
        item for item in dataset.documents
        if item.associated_profile_entity_id is not None and item.entity_type == "academic_publication"
    ]
    for document in documents:
        _document_findings(collector, [document])

    emails, _phones, _domains = _profile_contact_sources(selected, collector)
    _email_cross_account(collector, emails)
    _breach_findings(collector, dataset, emails)
    _infostealer_findings(collector, dataset)
    _combined_alias_email_link(collector, accounts, emails, cross_links)
    top = _content_and_document_signals(collector, selected, unit_signals)
    top.sort(key=lambda item: (
        -SEVERITY_ORDER[item.severity], -len(item.reveals), item.published_at or "", item.id
    ))
    top = top[:10]

    findings = collector.ordered(settings.exposure_max_findings)
    partial_reasons: list[ExposurePartialReason] = []
    if bool(dataset.execution.get("acquisition_partial")):
        partial_reasons.append("acquisition_partial")
    if skipped:
        partial_reasons.append("content_limit_reached")
    if ai_failed:
        partial_reasons.append("ai_failure")
    status = "partial" if partial_reasons else "completed"
    return _report_data(
        investigation_id, data_hash, status, findings, top,
        analyzed=len(selected), skipped=skipped, model=model, config=config,
        partial_reasons=partial_reasons,
        cache_hit=bool(cache_hits),
        generated_at=datetime.now(timezone.utc),
    )


def _report_from_run(run: ExposureRun, *, cache_hit: bool = False) -> ExposureReport:
    return ExposureReport(
        investigation_id=str(run.investigation_id),
        dataset_hash=run.dataset_hash,
        current_dataset_hash=run.dataset_hash,
        analysis_version=run.analysis_version,
        status=run.status,
        partial_reasons=(run.config or {}).get("partial_reasons", []),
        stale=False,
        cache_hit=cache_hit,
        summary=ExposureSummary.model_validate(run.summary or {}),
        categories={
            key: int((run.config or {}).get("category_counts", {}).get(key, 0))
            for key in CATEGORY_LABELS
        },
        findings=[ExposureFinding.model_validate(item) for item in (run.findings or [])],
        top_exposures=[ExposureTopItem.model_validate(item) for item in (run.top_exposures or [])],
        analyzed_content_count=run.analyzed_content_count,
        skipped_content_count=run.skipped_content_count,
        generated_at=run.completed_at,
        model=run.model,
        config={key: value for key, value in (run.config or {}).items()
                if key not in {"category_counts", "partial_reasons"}},
    )


async def get_report(db: AsyncSession, investigation_id: UUID) -> ExposureReport:
    _, _, current_hash = await _current_dataset(db, investigation_id)
    latest = (await db.scalars(
        select(ExposureRun)
        .where(ExposureRun.investigation_id == investigation_id)
        .order_by(ExposureRun.started_at.desc(), ExposureRun.id.desc())
        .limit(1)
    )).first()
    if latest is None:
        return ExposureReport(
            investigation_id=str(investigation_id),
            current_dataset_hash=current_hash,
            analysis_version=ANALYSIS_VERSION,
            status="pending",
        )
    report = _report_from_run(latest)
    if _running_abandoned(latest):
        # Read-only projection: persisted state is recovered only by POST.
        report.status = "failed"
    report.current_dataset_hash = current_hash
    report.stale = latest.dataset_hash != current_hash
    return report


def _running_abandoned(run: ExposureRun) -> bool:
    return (run.status == "running" and
            (datetime.now(timezone.utc) - run.started_at).total_seconds()
            > settings.exposure_run_lease_seconds)


async def analyze(db: AsyncSession, investigation_id: UUID) -> ExposureReport:
    _, dataset, data_hash = await _current_dataset(db, investigation_id, lock=True)
    config, model, config_hash = _analysis_config()
    # The unique constraint arbitrates creation even if another caller does not
    # hold the investigation lock. Lock the winning row before claiming retries.
    await db.execute(pg_insert(ExposureRun).values(
        investigation_id=investigation_id, dataset_hash=data_hash,
        config_hash=config_hash, analysis_version=ANALYSIS_VERSION,
        status="pending", config=config, model=model,
    ).on_conflict_do_nothing(constraint="uq_exposure_run_dataset_config"))
    run = (await db.scalars(select(ExposureRun).where(
        ExposureRun.investigation_id == investigation_id,
        ExposureRun.dataset_hash == data_hash,
        ExposureRun.analysis_version == ANALYSIS_VERSION,
        ExposureRun.config_hash == config_hash,
    ).with_for_update())).one()
    if run.status in {"completed", "partial"}:
        report = _report_from_run(run, cache_hit=True)
        await db.commit()
        return report
    if run.status == "running" and not _running_abandoned(run):
        report = _report_from_run(run)
        await db.commit()
        return report
    attempt_started = datetime.now(timezone.utc)
    run.status = "running"
    run.started_at = attempt_started
    run.completed_at = None
    run.summary = {}
    run.findings = []
    run.top_exposures = []
    run.config = config
    run.analyzed_content_count = run.skipped_content_count = 0
    run_id = run.id
    await db.commit()
    # Fence final writes by the attempt timestamp. A worker that outlives its
    # lease cannot overwrite a replacement, including on exception/cancellation.
    owned = (ExposureRun.id == run_id, ExposureRun.status == "running",
             ExposureRun.started_at == attempt_started)
    try:
        async with asyncio.timeout(settings.exposure_run_lease_seconds):
            report = await _build_analysis(db, investigation_id, dataset, data_hash, config, model, config_hash)
        saved = await db.execute(update(ExposureRun).where(*owned).values(
            status=report.status, completed_at=report.generated_at, model=model,
            summary=report.summary.model_dump(mode="json"),
            findings=[item.model_dump(mode="json") for item in report.findings],
            top_exposures=[item.model_dump(mode="json") for item in report.top_exposures],
            analyzed_content_count=report.analyzed_content_count,
            skipped_content_count=report.skipped_content_count,
            config={**config, "category_counts": report.categories, "partial_reasons": report.partial_reasons},
        ).execution_options(synchronize_session=False))
        if saved.rowcount == 0:
            await db.rollback()
            return _report_from_run(await db.get(ExposureRun, run_id, populate_existing=True))
        await db.commit()
        return report
    except (Exception, asyncio.CancelledError):
        # Roll back cache writes and any failed SQL transaction before recording failure.
        await db.rollback()
        await db.execute(update(ExposureRun).where(*owned).values(
            status="failed", completed_at=datetime.now(timezone.utc), config=config,
        ).execution_options(synchronize_session=False))
        await db.commit()
        raise
