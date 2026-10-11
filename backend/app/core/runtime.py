"""Serializable execution coverage shared by rules and external review."""
import json

RUNTIME_KEYS = (
    "username_finder_coverage", "username_finder_scanned", "username_finder_stats",
    "search_queries_executed", "search_queries_used", "search_provider_attempts", "search_seen_urls",
    "search_disabled_backends", "search_diagnostics", "search_query_limit",
    "domain_finder_checked", "personal_domain_urls",
)


def durable_runtime(extra):
    values = {key: extra[key] for key in RUNTIME_KEYS if key in extra}
    return json.loads(json.dumps(values, default=lambda value: sorted(value) if isinstance(value, set) else str(value)))


def search_limit(context, configured):
    return max(0, min(configured, context.extra.get("search_query_limit", configured)))
