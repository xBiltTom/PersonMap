"""Only typed identifiers and minimized Exposure evidence enter the snapshot."""
import re
from datetime import date
from urllib.parse import unquote

from app.exposure.detectors import (
    FAMILY_REFERENCE_RE, SENSITIVE_SUBJECT_RE, TIME_RE, exact_emails, exact_phones,
    has_operational_routine, has_precise_address, normalize_text, safe_category_evidence,
)
from app.services.exposure_lens import _safe_url as exposure_safe_url


def safe_url(value) -> str | None:
    clean = exposure_safe_url(value)
    if not clean:
        return None
    decoded = clean
    for _ in range(8):
        decoded = unquote(decoded)
    if TIME_RE.search(decoded) or re.search(r'(?i)\b(?:calle|street|avenida|av\.?|jr\.?)\s+\S+\s+\d', decoded):
        return None
    return clean


def safe_identifier(kind: str, value: str) -> str | None:
    value = normalize_text(value)
    if (len(value) > 160 or SENSITIVE_SUBJECT_RE.search(value) or FAMILY_REFERENCE_RE.search(value)
            or has_precise_address(value) or has_operational_routine(value) or TIME_RE.search(value)):
        return None
    if kind == 'alias':
        return value.lstrip('@') if re.fullmatch(r'@?[\w.-]{1,100}', value) else None
    if kind == 'email':
        return value.lower() if exact_emails(value) == [value.lower()] else None
    if kind == 'phone':
        phones = exact_phones(value)
        return phones[0] if len(phones) == 1 else None
    if kind == 'name':
        return value if re.fullmatch(r"[^\W\d_]+(?:[ '-][^\W\d_]+){0,7}", value) else None
    if kind == 'domain':
        return value.lower() if re.fullmatch(r'[a-zA-Z0-9.-]+\.[a-zA-Z]{2,24}', value) else None
    if kind == 'url':
        return safe_url(value)
    return None


def safe_platform(value: str | None) -> str | None:
    # Platform identifiers are namespaces, never free form profile descriptions.
    if value and re.fullmatch(r'[a-zA-Z0-9_.-]{1,50}', value) and safe_identifier('alias', value):
        return value.lower()
    return None


def safe_day(value) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T[^\s]+)?', value):
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def minimized_evidence(category: str, excerpt: str) -> str:
    if category == 'contact_exposure':
        emails = [v for v in exact_emails(excerpt) if safe_identifier('email', v)]
        phones = [v for v in exact_phones(excerpt) if safe_identifier('phone', v)]
        if emails:
            return f'Correo público visible: {emails[0]}'[:280]
        if phones:
            return f'Teléfono público visible: {phones[0]}'[:280]
    return safe_category_evidence(category, excerpt)
