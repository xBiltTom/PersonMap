import re
from pathlib import Path
from typing import List, Set
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from app.tools.base import TargetContext, ToolFinding


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9._-]{3,35}$")

IGNORE_EMAIL_PREFIXES = {"noreply", "no-reply", "mailer-daemon", "postmaster", "notifications", "support", "help", "contact"}
IGNORE_USERNAMES = {
    "login", "signup", "register", "about", "terms", "privacy", "explore", "search",
    "settings", "help", "support", "home", "index", "contact", "download", "auth",
    "admin", "root", "api", "dashboard", "user", "profile", "password", "reset",
}

# Try loading generic usernames from data file if available
GENERIC_FILE = Path(__file__).parent.parent / "tools" / "data" / "generic_usernames.txt"
if GENERIC_FILE.exists():
    try:
        content = GENERIC_FILE.read_text(encoding="utf-8")
        for line in content.splitlines():
            item = line.strip().lower()
            if item and not item.startswith("#"):
                IGNORE_USERNAMES.add(item)
    except Exception:
        pass


def _clean_url(raw_url: str) -> str:
    """Normalizes URL by stripping trailing slash and tracking query params."""
    try:
        parsed = urlparse(raw_url.strip())
        if not parsed.scheme or not parsed.netloc:
            return ""
        # Filter tracking parameters
        query_params = parse_qs(parsed.query)
        clean_params = {k: v for k, v in query_params.items() if not k.startswith("utm_") and k not in ["ref", "fbclid"]}
        clean_query = urlencode(clean_params, doseq=True)
        path = parsed.path.rstrip("/")
        return urlunparse((parsed.scheme, parsed.netloc.lower(), path, parsed.params, clean_query, ""))
    except Exception:
        return raw_url.strip().rstrip("/")


def extract_and_apply_pivots(findings: List[ToolFinding], context: TargetContext) -> bool:
    """
    Analyzes findings to extract validated, deduplicated pivot points:
    new emails, usernames, and profile URLs. Updates context and returns True if new targets were added.
    """
    pivoted = False
    candidate_urls: List[str] = list(context.extra.get("candidate_urls", []))
    existing_url_set: Set[str] = {_clean_url(u) for u in candidate_urls if u}

    for f in findings:
        metadata = f.metadata_info or {}

        # 1. New emails discovered (with strict validation & noise rejection)
        candidate_emails = metadata.get("emails", []) + metadata.get("extracted_emails", [])
        for em in candidate_emails:
            if not isinstance(em, str):
                continue
            em_clean = em.strip().lower()
            if EMAIL_REGEX.match(em_clean):
                prefix = em_clean.split("@")[0]
                if prefix not in IGNORE_EMAIL_PREFIXES and em_clean not in context.all_emails():
                    context.discovered_emails.append(em_clean)
                    pivoted = True

        # 2. New usernames discovered (with strict format validation & role blacklist)
        candidate_users = metadata.get("usernames", []) + metadata.get("extracted_usernames", [])
        for u in candidate_users:
            if not isinstance(u, str):
                continue
            u_clean = u.strip().lstrip("@")
            if USERNAME_REGEX.match(u_clean):
                if u_clean.lower() not in IGNORE_USERNAMES and u_clean not in context.all_usernames():
                    context.discovered_usernames.append(u_clean)
                    pivoted = True

        # 3. Candidate profile URLs to be evaluated by social_verifier / social_url_extractor
        urls_to_check = []
        if f.entity_type in ["social_account", "search_mention"] and f.value.startswith("http"):
            urls_to_check.append(f.value)
        if metadata.get("url") and str(metadata["url"]).startswith("http"):
            urls_to_check.append(str(metadata["url"]))
        for link in metadata.get("linked_profiles", []):
            if link and str(link).startswith("http"):
                urls_to_check.append(str(link))

        for raw_link in urls_to_check:
            clean_link = _clean_url(raw_link)
            if clean_link and clean_link not in existing_url_set:
                candidate_urls.append(clean_link)
                existing_url_set.add(clean_link)
                pivoted = True

    context.extra["candidate_urls"] = candidate_urls
    return pivoted
