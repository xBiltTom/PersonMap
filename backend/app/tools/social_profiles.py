"""Parse profile URLs by host and complete path, never by URL substrings."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


PROFILE_ROUTES = {
    "linkedin.com": ("linkedin", r"/in/([A-Za-z0-9_-]+)"),
    "github.com": ("github", r"/([A-Za-z0-9_-]+)"),
    "gitlab.com": ("gitlab", r"/([A-Za-z0-9_.-]+)"),
    "bitbucket.org": ("bitbucket", r"/([A-Za-z0-9_-]+)"),
    "twitter.com": ("twitter", r"/([A-Za-z0-9_]{1,15})"),
    "x.com": ("twitter", r"/([A-Za-z0-9_]{1,15})"),
    "instagram.com": ("instagram", r"/([A-Za-z0-9_.]+)"),
    "facebook.com": ("facebook", r"/([A-Za-z0-9_.]+)"),
    "t.me": ("telegram", r"/([A-Za-z0-9_]{5,32})"),
    "reddit.com": ("reddit", r"/u(?:ser)?/([A-Za-z0-9_-]+)"),
    "medium.com": ("medium", r"/@([A-Za-z0-9_.]+)"),
    "youtube.com": ("youtube", r"/(?:@|c/|user/)([A-Za-z0-9_-]+)"),
    "tiktok.com": ("tiktok", r"/@([A-Za-z0-9_.]+)"),
    "steamcommunity.com": ("steam", r"/id/([A-Za-z0-9_-]+)"),
    "pinterest.com": ("pinterest", r"/([A-Za-z0-9_]+)"),
    "soundcloud.com": ("soundcloud", r"/([A-Za-z0-9_-]+)"),
    "twitch.tv": ("twitch", r"/([A-Za-z0-9_]+)"),
    "dev.to": ("devto", r"/([A-Za-z0-9_-]+)"),
    "stackoverflow.com": ("stackoverflow", r"/users/\d+/([A-Za-z0-9_-]+)"),
}
RESERVED_ROUTES = {
    "home", "login", "signin", "signup", "register", "explore", "about",
    "terms", "privacy", "in", "search", "settings", "help", "support",
    "topics", "collections", "features", "marketplace", "organizations",
    "orgs", "apps", "intent", "share", "sharer", "i", "p", "reel",
    "reels", "stories", "accounts", "directory", "jobs", "watch", "feed",
    "groups", "pages", "events", "business", "developers", "discover",
    "join", "pricing", "notifications", "messages", "download", "site",
}


@dataclass(frozen=True)
class SocialProfile:
    platform: str
    username: str
    url: str


def normalize_web_url(raw: str, *, keep_query: bool = False) -> str | None:
    try:
        parsed = urlsplit(raw.strip())
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in {None, 80, 443}
                or any(ch.isspace() or ord(ch) < 32 for ch in raw)):
            return None
        query = ""
        if keep_query:
            # Preserve identifiers in forum/API URLs while dropping tracking.
            query = urlencode(sorted(
                (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                if not key.startswith("utm_") and key not in {"ref", "fbclid"}
            ), safe="{}")
        return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), query, ""))
    except (ValueError, AttributeError):
        return None


def parse_social_profile(raw: str) -> SocialProfile | None:
    normalized = normalize_web_url(raw)
    if not normalized:
        return None
    parsed = urlsplit(normalized)
    host = social_host(normalized)
    route = PROFILE_ROUTES.get(host)
    if not route:
        return None
    platform, pattern = route
    match = re.fullmatch(pattern, parsed.path, re.IGNORECASE)
    if not match or match[1].lower() in RESERVED_ROUTES:
        return None
    canonical_host = "x.com" if platform == "twitter" else host
    canonical = urlunsplit(("https", canonical_host, parsed.path, "", ""))
    return SocialProfile(platform, match[1], canonical)


def social_host(url: str) -> str:
    host = urlsplit(url).hostname or ""
    for prefix in ("www.", "m.", "mobile.", "old.", "new."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    if re.fullmatch(r"[a-z]{2}\.linkedin\.com", host):
        host = "linkedin.com"
    return host
