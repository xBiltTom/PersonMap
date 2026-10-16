"""Reviewed Actor contracts, not claims of live source availability or measured cost."""
from dataclasses import asdict, dataclass
import hashlib
import json
import re

from app.core.config import settings

VERSION = 2


@dataclass(frozen=True)
class ApifyActorSpec:
    platform: str
    actor: str
    input_types: tuple[str, ...]
    output_types: tuple[str, ...]
    supports_username_lookup: bool = True
    supports_profile: bool = True
    supports_posts: bool = True
    supports_comments: bool | None = None
    supports_followers_following: bool | None = None
    estimated_cost_class: str = "unknown"
    estimated_latency_class: str = "unknown"
    priority: int = 20
    profile_row: bool = False
    notes: str = ""


ACTORS = {
    "instagram": ApifyActorSpec("instagram", "apify/instagram-profile-scraper",
        ("username",), ("profile", "recent_posts"), profile_row=True,
        notes="Multiple usernames per run; includeAboutSection=false. Nested recent posts have no Actor-side count input; local content truncation."),
    "tiktok": ApifyActorSpec("tiktok", "clockworks/tiktok-profile-scraper",
        ("username",), ("profile", "videos"), supports_comments=True, supports_followers_following=True,
        notes="resultsPerPage bounded. Comments, followers/following, downloads and transcripts explicitly disabled."),
    "threads": ApifyActorSpec("threads", "apify/threads-profile-api-scraper",
        ("username",), ("profile", "recent_posts"), profile_row=True,
        notes="Discard private profiles. Recent posts bounded locally; no pagination/count input documented."),
    "youtube": ApifyActorSpec("youtube", "streamers/youtube-channel-scraper",
        ("profile_url",), ("channel", "videos"), supports_comments=False, supports_followers_following=False,
        notes="maxResults bounded; shorts/streams disabled. No email CAPTCHA, login, media or transcript download."),
}

EVALUATED = {
    "reddit": {"actor": "apify/reddit-scraper", "input_types": ["username", "profile_url"],
        "output_types": ["profile", "posts", "comments"], "supports_username_lookup": True,
        "supports_profile": True, "supports_posts": True, "supports_comments": True,
        "supports_followers_following": None},
    "twitter": {"actor": "apidojo/twitter-profile-scraper", "input_types": ["username", "profile_url"],
        "output_types": ["profile", "tweets", "replies"], "supports_username_lookup": True,
        "supports_profile": True, "supports_posts": True, "supports_comments": True,
        "supports_followers_following": None},
    "facebook": {"actor": "apify/facebook-posts-scraper", "input_types": ["public_page_url"],
        "output_types": ["page_posts"], "supports_username_lookup": False,
        "supports_profile": False, "supports_posts": True, "supports_comments": False,
        "supports_followers_following": False},
    "linkedin": {"actor": "harvestapi/linkedin-profile-scraper", "input_types": ["profile_url", "public_identifier"],
        "output_types": ["profile"], "supports_username_lookup": True,
        "supports_profile": True, "supports_posts": False, "supports_comments": False,
        "supports_followers_following": None},
}

# Choices apply to PersonMap's scope, not to the inherent quality of every Actor.
POLICIES = {
    **{platform: ("hybrid", "Declared platform accounts enrich directly; discovered accounts require native observation and Frontier admission.") for platform in ACTORS},
    "reddit": ("native", "Maigret/SearchDorker remain; official Actor supports usernames and separate users/posts/comments modes; high priority, deferred pending live validation and comparative measurement."),
    "twitter": ("native", "Defer paid profile queries pending quality/cost comparison; never expand every alias into X."),
    "facebook": ("native", "Reviewed posts Actor documents public Pages, not personal profiles; scope mismatch."),
    "linkedin": ("native", "Public search/verification remain. Optional email-finder modes are outside scope; defer detailed profile adapter."),
    "telegram": ("native", "Existing public-page specialist; no demonstrated need for a paid duplicate."),
    "github": ("native", "Specialized public email/commit/repository evidence already retained by GitHub scanner."),
    "gravatar": ("native", "Exact email association and linked profiles already covered."),
    "academic": ("native", "Retain OpenAlex/Crossref, author validation, DOI and ORCID provenance."),
    "google": ("native", "Retain GHunt and complementary public Google discovery."),
    "email_phone_documents": ("native", "Keep email, breach, phone and document tools; Apify duplication not worth using here."),
}


def canonical_platform(value: str | None) -> str:
    value = (value or "").strip().casefold()
    return {"x": "twitter", "x/twitter": "twitter", "x_twitter": "twitter", "twitter/x": "twitter",
            "threads.net": "threads", "threads.com": "threads", "ig": "instagram", "yt": "youtube"}.get(value, value)


def actor_build(spec: ApifyActorSpec) -> str:
    value = settings.apify_actor_builds.get(spec.platform, "latest")
    token = settings.apify_token.get_secret_value() if settings.apify_token else None
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value)
            or value.startswith("apify_api_") or value == token):
        raise ValueError("invalid_actor_build")
    return value


def availability() -> str:
    if not settings.apify_enabled:
        return "disabled"
    if not settings.apify_token or not settings.apify_token.get_secret_value().strip():
        return "token_missing"
    return "configured_not_live_validated"


def capabilities() -> dict:
    allowed = {canonical_platform(value) for value in settings.apify_platforms}
    rows = []
    for platform, (policy, notes) in POLICIES.items():
        inputs = (["name", "orcid", "doi_url"] if platform == "academic" else
            ["email", "gaia_id", "public_drive_url", "name"] if platform == "google" else
            ["email"] if platform == "gravatar" else ["email", "phone", "document_url"] if platform == "email_phone_documents"
            else ["username", "profile_url"])
        rows.append({"platform": platform, "provider": "native", "actor": None,
            "strategy": policy, "priority": 10, "enabled": True, "notes": notes,
            "input_types": inputs, "output_types": ["ToolFinding"],
            "supports_username_lookup": "username" in inputs,
            "supports_profile": None, "supports_posts": None, "supports_comments": None,
            "supports_followers_following": None, "estimated_cost_class": "unknown",
            "estimated_latency_class": "unknown"})
        if platform in ACTORS:
            rows.append({**asdict(ACTORS[platform]), "input_types": list(ACTORS[platform].input_types),
                "output_types": list(ACTORS[platform].output_types), "provider": "apify", "strategy": policy,
                "enabled": platform in allowed and availability() == "configured_not_live_validated",
                "validation": {"input_schema": "validated", "dataset": "fixture-tested", "live_run": "not_live_validated"},
                "collection_scope": "public_profile_and_bounded_content_no_audience_lists"})
        elif platform in EVALUATED:
            rows.append({**EVALUATED[platform], "platform": platform, "provider": "apify", "enabled": False,
                "strategy": "not worth using" if platform == "facebook" else "native",
                "priority": 100, "estimated_cost_class": "unknown", "estimated_latency_class": "unknown",
                "notes": notes + " Evaluated, not integrated; enabling the platform cannot launch this Actor.",
                "validation": {"input_schema": "validated", "dataset": "not fixture-tested", "live_run": "not_live_validated"}})
    return {"version": VERSION, "availability": availability(), "matrix": rows,
        "budget": {"max_actors": settings.apify_max_actors, "max_runs": settings.apify_max_runs,
            "max_items_per_actor": settings.apify_max_items_per_actor,
            "max_profiles_per_actor": settings.apify_max_profiles_per_actor,
            "max_content_items_per_profile": settings.apify_max_content_items_per_profile,
            "run_timeout_seconds": settings.apify_run_timeout, "batch_timeout_seconds": settings.apify_batch_timeout,
            "request_timeout_seconds": settings.apify_request_timeout, "get_retries": settings.apify_max_retries,
            "start_retries": 0, "parallelism": settings.apify_parallelism,
            "max_charge_per_run_usd": settings.apify_max_charge_per_run_usd,
            "max_reserved_charge_per_investigation_usd": settings.apify_max_charge_per_investigation_usd}}


def config_id() -> str:
    # No token, credential hash, paths or authentication headers in observability.
    return hashlib.sha256(json.dumps({"capabilities": capabilities(), "builds": settings.apify_actor_builds},
                                     sort_keys=True).encode()).hexdigest()
