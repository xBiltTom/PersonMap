"""Allowlisted public metadata only; never retain raw Actor rows or signed URLs."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.config import settings
from app.tools.dni_public import public_source_url


def public_url(value) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    token = settings.apify_token.get_secret_value() if settings.apify_token else None
    if token and token in value or re.search(r"apify_api_[A-Za-z0-9_-]+", value):
        return None
    safe = public_source_url(value)
    if not safe:
        return None
    parsed = urlsplit(safe)
    query = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.casefold().startswith("utm_") and key.casefold() not in {"ref", "fbclid"}}
    # Reject rather than retain (or accidentally break) signed CDN/storage URLs.
    allowed = ({"v"} if parsed.hostname in {"youtube.com", "www.youtube.com"} and parsed.path == "/watch"
               else {"id"} if parsed.hostname in {"facebook.com", "www.facebook.com"} and parsed.path == "/profile.php"
               else set())
    if set(query) - allowed:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def text(value, limit=4000) -> str:
    if not isinstance(value, str):
        return ""
    value = value[:limit]
    if settings.apify_token and (token := settings.apify_token.get_secret_value()):
        value = value.replace(token, "[REDACTED]")
    value = re.sub(r"(?i)\b(?:apify_api_[A-Za-z0-9_-]+|Bearer\s+[A-Za-z0-9_.-]+)", "[REDACTED]", value)
    value = re.sub(r"https?://[^\s<>\"']+", lambda match: public_url(match[0]) or "[URL omitted]", value)
    return "".join(char for char in value if ord(char) >= 32 or char in "\n\t")
