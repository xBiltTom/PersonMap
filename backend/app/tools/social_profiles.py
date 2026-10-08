"""Parse profile URLs by host and complete path, never by URL substrings."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, unquote, quote


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
    "youtube.com": ("youtube", r"/(?:@|c/|user/)([\w.·-]+)"),
    "snapchat.com": ("snapchat", r"/(?:@|add/)([A-Za-z][A-Za-z0-9_.-]{1,13}[A-Za-z0-9])"),
    "threads.net": ("threads", r"/@([A-Za-z0-9_.]+)"),
    "threads.com": ("threads", r"/@([A-Za-z0-9_.]+)"),
    "bsky.app": ("bluesky", r"/profile/([A-Za-z0-9.-]+)"),
    "keybase.io": ("keybase", r"/([A-Za-z0-9_]+)"),
    "vk.com": ("vk", r"/([A-Za-z0-9_.]+)"),
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


TELEGRAM_HOSTS = {"t.me", "telegram.me", "telegram.dog"}
TELEGRAM_RESERVED = {
    "addemoji", "addlist", "addstickers", "addstyle", "addtheme", "auction",
    "auth", "boost", "call", "confirmphone", "contact", "giftcode", "invoice",
    "joinchat", "login", "m", "nft", "proxy", "setlanguage", "share", "socks",
    "web", "a", "k", "z", "c", "s", "iv", "msg", "passport", "bg",
}
TELEGRAM_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")


def valid_telegram_username(username: str) -> bool:
    return bool(TELEGRAM_USERNAME.fullmatch(username)) and username.lower() not in TELEGRAM_RESERVED


def _telegram_profile(host: str, path: str):
    # Public aliases, previews and message links identify the same public peer.
    if host.endswith(".t.me") and host.count(".") == 2:
        username = host[:-5]
        if path and not re.fullmatch(r"/\d+(?:/\d+)?", path):
            return None
    elif host in TELEGRAM_HOSTS:
        match = re.fullmatch(r"/(?:s/)?([A-Za-z0-9_]+)(?:/\d+(?:/\d+)?)?", path)
        if not match:
            return None
        username = match[1]
    else:
        return None
    if not valid_telegram_username(username):
        return None
    return SocialProfile("telegram", username, f"https://t.me/{username}")


@dataclass(frozen=True)
class SocialProfile:
    platform: str
    username: str
    url: str
    resource_kind: str = "username"


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
    normalized = normalize_web_url(raw, keep_query=True)
    if not normalized:
        return None
    parsed = urlsplit(normalized)
    telegram_host = (parsed.hostname or "").removeprefix("www.")
    if telegram_host in TELEGRAM_HOSTS or telegram_host.endswith(".t.me"):
        return _telegram_profile(telegram_host, unquote(parsed.path))
    host = social_host(normalized)
    route = PROFILE_ROUTES.get(host)
    if not route:
        return None
    platform, pattern = route
    if platform == "facebook":
        params = dict(parse_qsl(parsed.query))
        if parsed.path == "/profile.php":
            identity = params.get("id", "")
            if not re.fullmatch(r"[1-9][0-9]{0,24}", identity):
                return None
            return SocialProfile(platform, identity, f"https://facebook.com/profile.php?id={identity}", "profile_id")
        people = re.fullmatch(r"/people/[^/]+/([1-9][0-9]{0,24})", parsed.path)
        numeric = re.fullmatch(r"/([1-9][0-9]{0,24})", parsed.path)
        if people or numeric:
            identity = (people or numeric)[1]
            return SocialProfile(platform, identity, f"https://facebook.com/profile.php?id={identity}", "profile_id")
        if parsed.path.endswith(".php"):
            return None
    path = unquote(parsed.path)
    if platform == "youtube":
        channel = re.fullmatch(r"/channel/(UC[A-Za-z0-9_-]{22})(?:/(?:about|videos|featured))?", path)
        if channel:
            return SocialProfile(platform, channel[1], f"https://youtube.com/channel/{channel[1]}", "channel_id")
        path = re.sub(r"/(?:about|videos|featured)$", "", path)
    match = re.fullmatch(pattern, path, re.IGNORECASE)
    if not match or match[1].lower() in RESERVED_ROUTES:
        return None
    canonical_host = "x.com" if platform == "twitter" else host
    if platform == "snapchat":
        path = f"/@{match[1]}"
    canonical = urlunsplit(("https", canonical_host, quote(path, safe="/@._-"), "", ""))
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


def core_profile_candidates(username: str) -> list[str]:
    """Derived URLs are requests to verify, never evidence of an account."""
    templates = ["https://x.com/{}", "https://instagram.com/{}", "https://facebook.com/{}",
                 "https://tiktok.com/@{}", "https://youtube.com/@{}", "https://snapchat.com/@{}",
                 "https://t.me/{}"]
    return [profile.url for template in templates
            if (profile := parse_social_profile(template.format(quote(username, safe="")))) is not None]
