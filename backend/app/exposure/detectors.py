from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9.!#$%&'*+/=?^_{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+",
    re.IGNORECASE,
)
PHONE_RE = re.compile(r"(?<!\w)(?:\+\s*)?\d[\d\s().-]{7,}\d(?!\w)")
URL_RE = re.compile(r"(?i)(?:https?://|www\.)[^\s<>{}\[\]\"']{4,500}")
CONTACT_URL_RE = re.compile(r"(?i)\b(?:mailto:|tel:|wa\.me/|api\.whatsapp\.com/|t\.me/|linktr\.ee/)")
SENSITIVE_SUBJECT_RE = re.compile(
    r"\b(?:religion|religious|religi[oó]n|religios[oa]s?|faith|church|muslim|"
    r"christian|judaism|islam|pol[ií]tic[oa]s?|politic(?:al|s)?|partisan|"
    r"health|salud|medical condition|condici[oó]n m[eé]dica|disease|enfermedad|"
    r"diagnos(?:is|ed)|diagn[oó]stic[oa]s?|sexual orientation|orientaci[oó]n sexual|"
    r"orientation|orientaci[oó]n|ethnic(?:ity)?|etnia|[eé]tnic[oa]s?|race|raza|racial)\b",
    re.IGNORECASE,
)
FAMILY_REFERENCE_RE = re.compile(
    r"\b(?:(?:my|our|his|her|their|mi|mis|nuestro|nuestra|nuestros|nuestras|su|sus)\s+)?"
    r"(?:mother|father|mom|dad|sister|brother|wife|husband|spouse|partner|daughter|son|child|"
    r"children|grandmother|grandfather|grandma|grandpa|aunt|uncle|cousin|niece|nephew|"
    r"madre|padre|mam[aá]|pap[aá]|hermana|hermano|esposa|esposo|pareja|hija|hijo|"
    r"abuela|abuelo|t[ií]a|t[ií]o|prima|primo|sobrina|sobrino)\b"
    r"(?:\s+(?:(?-i:[A-ZÁÉÍÓÚÜÑ])[-\wÁÉÍÓÚÜÑáéíóúüñ']*)){0,2}",
    re.IGNORECASE,
)

# This deliberately favors false negatives. A detected street address is
# generalized before it can become a quote, cache entry, report, or AI input.
PRECISE_ADDRESS_RE = re.compile(
    r"\b(?:av(?:enida)?\.?|jr\.?|jir[oó]n|calle|pasaje|psje\.?|street|st\.?|"
    r"avenue|road|rd\.?|boulevard|blvd\.?|urbanizaci[oó]n|urb\.?)\s+"
    r"[\wÁÉÍÓÚÜÑáéíóúüñ.'-]{2,}(?:\s+[\wÁÉÍÓÚÜÑáéíóúüñ.'-]{2,}){0,4}"
    r"(?:\s+(?:n[°ºo]?|#)?\s*\d{1,5}[A-Za-z]?)?"
    r"(?:[,\s]+(?:dpto\.?|depto\.?|apto\.?|piso|interior|suite|unit)\s*[\w-]{1,12})?",
    re.IGNORECASE,
)
ROUTINE_RE = re.compile(
    r"\b(?:every|each|daily|weekly|todos los|todas las|cada|semanalmente|diariamente)\b"
    r".{0,90}\b(?:at|a las|desde las|between|from)\s+\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?",
    re.IGNORECASE,
)
WEEKDAY_TIME_RE = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|lunes|martes|"
    r"mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)(?:s)?"
    r"(?:\s*(?:,|&|and|y)\s*(?:monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)(?:s)?){0,6}"
    r"\s+(?:(?:at|a las|desde las)\s*)?(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s*"
    r"(?:a\.?m\.?|p\.?m\.?)?\b",
    re.IGNORECASE,
)
TIME_RE = re.compile(
    r"\b(?:at|a las|desde las|between|from)\s+(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s*"
    r"(?:a\.?m\.?|p\.?m\.?)?\b|"
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:a\.?m\.?|p\.?m\.?)?\b|"
    r"\b(?:0?[1-9]|1[0-2])\s*(?:a\.?m\.?|p\.?m\.?)\b",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
    r"ene(?:ro)?|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|"
    r"noviembre|diciembre)\s+\d{1,2})\b",
    re.IGNORECASE,
)
WEEKDAY_RE = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|lunes|martes|"
    r"mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b",
    re.IGNORECASE,
)
TEMPORAL_WORD_RE = re.compile(
    r"\b(?:today|tomorrow|yesterday|hoy|mañana|ayer|viaje|viajando|visitando|"
    r"trip|travel|travelling|traveling|vacation|vacaciones|evento|event|conference|"
    r"conferencia|concert|concierto|reuni[oó]n|meeting|graduaci[oó]n|graduation)\b",
    re.IGNORECASE,
)
LOCATION_CONTEXT_RE = re.compile(
    r"\b(?:vivo en|vive en|ubicad[oa] en|based in|located in|visiting|visitando|"
    r"viaje a|viajando a|travel(?:ling|ing)? to|in the city of|en la ciudad de|"
    r"en campus de|at campus|en campus)\s+"
    r"([A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ.'-]*(?:\s+(?:de|del|la|las|los|and|of)\s+"
    r"[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ.'-]*|\s+[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ.'-]*){0,3})",
    re.IGNORECASE,
)
EDU_WORK_RE = re.compile(
    r"\b(?:universidad|university|college|campus|faculty|facultad|escuela|school|"
    r"instituto|institute|empresa|company|corporation|trabajo en|work(?:ing)? at|"
    r"emplead[oa] en|researcher at|professor at|estudiante de|student of|"
    r"graduad[oa] en|degree in|carrera de|department of|departamento de)\b",
    re.IGNORECASE,
)
BIO_ROLE_RE = re.compile(
    r"\b(?:engineer|ingenier[oa]|developer|desarrollador(?:a)?|professor|profesor(?:a)?|"
    r"researcher|investigador(?:a)?|designer|docente|founder|director(?:a)?|"
    r"manager|analyst|analista|journalist|periodista|architect|arquitect[oa])\b",
    re.IGNORECASE,
)

_COMMON_LINK_HOSTS = {
    "instagram.com", "tiktok.com", "youtube.com", "youtu.be", "x.com", "twitter.com",
    "facebook.com", "linkedin.com", "reddit.com", "github.com", "gitlab.com",
    "medium.com", "t.me", "telegram.me", "linktr.ee", "wa.me", "whatsapp.com",
    "bit.ly", "tinyurl.com", "openalex.org", "orcid.org", "scholar.google.com",
}


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def exact_emails(value: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).strip(".,;:!?").lower() for match in EMAIL_RE.finditer(value)))


def exact_phones(value: str) -> list[str]:
    found: list[str] = []
    for match in PHONE_RE.finditer(value):
        raw = match.group(0).strip()
        # ISO dates and date-time stamps can look like long phone strings after
        # punctuation is stripped. They are temporal evidence, not contacts.
        if re.search(r"\b\d{4}-\d{1,2}-\d{1,2}\b", raw):
            continue
        digits = re.sub(r"\D", "", raw)
        # Reject dates, counters and short fragments; require international
        # length so ordinary numbers in captions do not become contact data.
        if len(digits) < 9 or len(digits) > 15:
            continue
        normalized = ("+" if raw.lstrip().startswith("+") else "") + digits
        if normalized not in found:
            found.append(normalized)
    return found


def public_urls(value: str) -> list[str]:
    result: list[str] = []
    for match in URL_RE.finditer(value):
        raw = match.group(0).rstrip(".,;:!?)]}")
        candidate = f"https://{raw}" if raw.lower().startswith("www.") else raw
        try:
            parts = urlsplit(candidate)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                continue
            clean = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            if clean not in result:
                result.append(clean)
        except (TypeError, ValueError):
            continue
    return result[:20]


def domain_from_url(value: str) -> str | None:
    try:
        host = (urlsplit(value).hostname or "").lower().rstrip(".").removeprefix("www.")
    except ValueError:
        return None
    if not host or host in _COMMON_LINK_HOSTS:
        return None
    if any(host == domain or host.endswith("." + domain) for domain in _COMMON_LINK_HOSTS):
        return None
    if host.endswith(".edu") or ".edu." in host or host.endswith(".ac.uk"):
        return None
    return host


def has_precise_address(value: str) -> bool:
    return bool(PRECISE_ADDRESS_RE.search(value))


def has_operational_routine(value: str) -> bool:
    return bool(ROUTINE_RE.search(value) or WEEKDAY_TIME_RE.search(value))


def has_temporal_disclosure(value: str) -> bool:
    return bool(DATE_RE.search(value) or WEEKDAY_RE.search(value) or TEMPORAL_WORD_RE.search(value))


def has_general_location(value: str) -> bool:
    return bool(LOCATION_CONTEXT_RE.search(value))


def safe_category_evidence(category: str, value: str, limit: int = 280) -> str:
    """Extract only an explicit signal; unknown/ambiguous context fails closed.

    Case-sensitive name tokens deliberately stop at prose/conjunctions. Never
    quote a sentence surrounding an institution or a professional role.
    """
    text = normalize_text(value)
    if category == "location_disclosure":
        result = ("Referencia de ubicación específica [redactada]." if has_precise_address(text)
                  else "Se observó una ubicación general en una fuente pública.")
    elif category == "temporal_exposure":
        result = "Referencia temporal pública observada [generalizada]."
    elif category == "education_work_context":
        # Only institution markers plus a short, explicitly capitalized name.
        token = r"[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñA-ZÁÉÍÓÚÜÑ-]*"
        name = rf"{token}(?:(?: (?:de|del|la|los|las|of))? {token}){{0,5}}"
        match = re.search(
            rf"(?i:\b(universidad|university|college|instituto|institute|empresa|company)) "
            rf"((?:(?:de|del|la|los|las|of) )?{name})(?![\w-])", text,
        )
        result = "Se observó contexto público de estudio o trabajo."
        if match:
            institution = match.group(0)
            if not (SENSITIVE_SUBJECT_RE.search(institution) or FAMILY_REFERENCE_RE.search(institution)
                    or has_precise_address(institution) or TIME_RE.search(institution)):
                kind = "laboral" if match.group(1).lower() in {"empresa", "company"} else "educativo"
                result = f"Contexto {kind} observado: {institution}."
    elif category == "biographical_identifiers":
        match = BIO_ROLE_RE.search(text)
        result = (f"Cargo público observado: {match.group(0)}." if match
                  else "Se observó un identificador biográfico público.")
    elif category == "public_documents":
        result = "Documento público atribuido con identificadores visibles."
    else:
        result = "Se observó una señal pública de exposición."
    return result[:limit]


def safe_excerpt(value: str, limit: int = 280) -> str:
    """Generic fallback never reproduces unstructured source text."""
    if has_precise_address(value):
        return "La fuente contiene una referencia de ubicación específica [redactada]."[:limit]
    if has_operational_routine(value):
        return "La fuente contiene referencias temporales repetidas [generalizadas]."[:limit]
    return safe_category_evidence("content_disclosure", value, limit)


def ai_safe_text(value: str, limit: int) -> str:
    """Bounded text for the optional classifier; never send addresses or contact strings."""
    clean = normalize_text(value)
    clean = FAMILY_REFERENCE_RE.sub("[referencia familiar omitida]", clean)
    clean = PRECISE_ADDRESS_RE.sub("[ubicación específica omitida]", clean)
    clean = ROUTINE_RE.sub("[patrón temporal omitido]", clean)
    clean = WEEKDAY_TIME_RE.sub("[patrón temporal omitido]", clean)
    clean = EMAIL_RE.sub("[correo de contacto]", clean)
    clean = PHONE_RE.sub("[teléfono de contacto]", clean)
    clean = SENSITIVE_SUBJECT_RE.sub("[tema sensible omitido]", clean)
    clean = FAMILY_REFERENCE_RE.sub("[referencia familiar omitida]", clean)
    clean = TIME_RE.sub("[hora omitida]", clean)
    if len(clean) > limit:
        clean = clean[:limit]
    return clean


def explicit_context_signal(value: str) -> tuple[bool, bool]:
    """Returns explicit education/work and biographical-role markers."""
    return bool(EDU_WORK_RE.search(value)), bool(BIO_ROLE_RE.search(value))
