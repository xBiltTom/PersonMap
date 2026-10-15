"""Serializable execution coverage shared by rules and external review."""
import json

RUNTIME_KEYS = (
    "email_enum_checked", "email_enum_diagnostics", "email_enum_config_id",
    "ghunt_checked", "ghunt_diagnostics", "ghunt_config_id", "ghunt_resolved_gaia",
    "google_public_checked", "google_public_youtube_queries",
    "username_finder_coverage", "username_finder_scanned", "username_finder_stats",
    "username_finder_catalog_id", "username_finder_outcomes",
    "username_finder_diagnostics", "username_finder_permutations",
    "username_finder_checks", "maigret_enricher_checks",
    "maigret_identifiers", "maigret_identifier_sources", "maigret_enricher_parsed",
    "maigret_url_identifiers",
    "maigret_enricher_url_attempts",
    "maigret_enricher_scanned", "maigret_enricher_catalog_id", "maigret_enricher_diagnostics",
    "search_queries_executed", "search_queries_used", "search_provider_attempts", "search_seen_urls",
    "search_disabled_backends", "search_diagnostics", "search_query_limit",
    "search_query_plan", "search_last_status", "search_read_urls", "search_fetch_disabled",
    "domain_finder_checked", "personal_domain_urls",
    "academic_checked_names", "academic_diagnostics",
    "github_checked_usernames",
)


def durable_runtime(extra):
    values = {key: extra[key] for key in RUNTIME_KEYS if key in extra}
    return json.loads(json.dumps(values, default=lambda value: sorted(value) if isinstance(value, set) else str(value)))


def search_limit(context, configured):
    return max(0, min(configured, context.extra.get("search_query_limit", configured)))
