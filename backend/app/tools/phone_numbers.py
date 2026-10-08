"""Numbering-plan facts and bounded extraction; never subscriber identity."""

import re
from urllib.parse import unquote

import phonenumbers
from phonenumbers import carrier, geocoder, timezone

PHONE_INPUT = re.compile(r"^(?:tel:)?\+?[0-9\s().-]+(?:(?:ext\.?|x|;ext=|#)\s*[0-9]{1,10})?$", re.I)
PHONE_LABEL = re.compile(r"(?:tel(?:éfono|efono|ephone)?|phone|cel(?:ular)?|móvil|movil|mobile|whatsapp|contacto|contact|llama|fono)\s*[:=.-]?\s*$", re.I)


def analyze_phone(raw: str, default_region: str = "PE") -> dict:
    facts = {"raw_input": raw, "default_region": default_region, "source_kind": "local_numbering_plan",
             "library_version": phonenumbers.__version__, "active_status": "unknown", "ownership_status": "unverified"}
    if not isinstance(raw, str) or len(raw) > 100 or not PHONE_INPUT.fullmatch(raw.strip()):
        return {**facts, "valid": False, "validation_reason": "invalid_input"}
    try:
        number = phonenumbers.parse(raw.strip(), default_region)
    except phonenumbers.NumberParseException as exc:
        return {**facts, "valid": False, "validation_reason": f"parse_error_{exc.error_type}"}
    possible = phonenumbers.is_possible_number_with_reason(number)
    reasons = {0: "possible", 1: "invalid_country_code", 2: "too_short", 3: "too_long", 4: "local_only", 5: "invalid_length"}
    valid = phonenumbers.is_valid_number(number)
    if not valid:
        return {**facts, "valid": False, "possible": possible in {0, 4}, "validation_reason": reasons.get(possible, "invalid_range") if possible else "invalid_range"}
    kinds = {0: "fixed_line", 1: "mobile", 2: "fixed_or_mobile", 3: "toll_free", 4: "premium_rate", 5: "shared_cost", 6: "voip", 7: "personal_number", 8: "pager", 9: "uan", 10: "voicemail", 99: "unknown"}
    iso = phonenumbers.region_code_for_number(number)
    return {**facts, "valid": True, "possible": True, "validation_reason": "valid_numbering_plan",
            "e164": phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164),
            "national": phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL),
            "international": phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
            "extension": number.extension, "country_iso": iso, "country_calling_code": number.country_code,
            "default_region_applied": not raw.strip().startswith(("+", "tel:+")),
            "line_type": kinds.get(phonenumbers.number_type(number), "unknown"),
            "numbering_region": geocoder.description_for_number(number, "es") or None,
            "timezones": [z for z in timezone.time_zones_for_number(number) if z != "Etc/Unknown"],
            "original_carrier": carrier.name_for_number(number, "es") or None,
            "current_carrier": None, "current_carrier_status": "unknown"}


def phone_identity(raw: str, default_region: str = "PE") -> str | None:
    facts = analyze_phone(raw, default_region)
    if not facts["valid"]:
        return None
    return facts["e164"] + (";ext=" + facts["extension"] if facts.get("extension") else "")


def extract_phone_observations(text: str, default_region: str = "PE", limit: int = 5) -> list[dict]:
    """National numbers need a contact label; explicit international numbers do not."""
    text = unquote(text[:20000])
    observations = []
    seen = set()
    for match in phonenumbers.PhoneNumberMatcher(text, default_region, leniency=phonenumbers.Leniency.VALID, max_tries=100):
        raw = match.raw_string
        before = text[max(0, match.start - 40):match.start]
        after = text[match.end:match.end + 1]
        if (before and (before[-1].isalnum() or before[-1] == '_')) or (after and (after.isalnum() or after == '_')):
            continue
        if not raw.startswith('+') and not PHONE_LABEL.search(before):
            continue
        facts = analyze_phone(raw, default_region)
        identity = phone_identity(raw, default_region)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        observations.append({"phone": identity, "raw": raw, "context": text[max(0, match.start - 40):match.end + 40]})
        if len(observations) >= limit:
            break
    return observations


def matches_phone_text(target: str, *texts: str) -> bool:
    facts = analyze_phone(target)
    if not facts["valid"]:
        return False
    region = facts["country_iso"] if facts["country_iso"] != "001" else "PE"
    expected = phone_identity(target)
    return any(item["phone"] == expected for text in texts for item in extract_phone_observations(text, region))
