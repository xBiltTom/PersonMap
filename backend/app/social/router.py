"""Declared accounts enrich directly; discovered accounts require native admission."""
from dataclasses import asdict, dataclass

from app.core.config import settings
from app.social.capabilities import ACTORS, availability, canonical_platform
from app.social.safety import public_url
from app.tools.social_profiles import parse_social_profile

NATIVE_TOOLS = ("username_finder", "social_verifier", "search_dorker")


def remember_native_profiles(findings, context):
    profiles = context.extra.setdefault("social_native_profiles", [])
    known = {entry["url"] for entry in profiles}
    for finding in findings:
        meta = finding.metadata_info or {}
        tool = str(meta.get("source_tool", "")).rsplit(":", 1)[-1]
        if meta.get("provider") == "apify" or finding.entity_type not in {"social_account", "search_mention"}:
            continue
        search_candidate = tool == "search_dorker" and meta.get("literal_match") is True
        observed = (finding.entity_type == "social_account" and (
            tool == "social_verifier" and meta.get("verification_status") == "verified"
            or tool == "username_finder" and meta.get("negative_control") == "passed"
                and (meta.get("maigret_status") == "Claimed" or meta.get("catalog_source") == "whatsmyname"))
            or search_candidate)
        profile = parse_social_profile(url) if (url := public_url(finding.value)) else None
        if observed and profile and profile.url not in known and len(profiles) < 128:
            profiles.append({"platform": profile.platform, "username": profile.username, "url": profile.url,
                             "source_tool": tool, "evidence_role": "native_search_profile_candidate_not_ownership"
                             if search_candidate else "native_existence_observation_not_ownership"})
            known.add(profile.url)


@dataclass(frozen=True)
class RoutingDecision:
    platform: str
    username: str
    url: str | None
    strategy: str
    native_tools: tuple[str, ...]
    actor: str | None
    reason: str
    declared_seed: dict | None = None


class SocialSourceRouter:
    def plan(self, context) -> list[RoutingDecision]:
        state = context.extra.get("apify_runtime", {})
        available = state.get("unavailable") or availability()
        consent = context.extra.get("subject_consent") is True
        allowed = {canonical_platform(value) for value in settings.apify_platforms}
        if "apify_platform_allowlist" in context.extra:
            allowed &= {canonical_platform(value) for value in context.extra["apify_platform_allowlist"]}
        hints = {(seed.value.casefold(), canonical_platform(seed.platform)) for seed in context.declared_seeds
                 if seed.kind == "username" and seed.platform}
        # Respect Frontier's admitted execution view, not the unfiltered archive.
        visible = {profile.url for raw in context.extra.get("candidate_urls", [])
                   if public_url(raw) and (profile := parse_social_profile(raw))}
        decisions = []
        represented = set()
        from app.social.apify_adapter import TEMPLATES
        from app.schemas.footprint import account_ownership
        for seed in context.declared_seeds:
            platform = canonical_platform(seed.platform)
            if seed.kind != "username" or platform not in ACTORS:
                continue
            url = TEMPLATES[platform].format(seed.value)
            profile = parse_social_profile(url)
            if not profile:
                continue
            reason = ("subject_consent_required" if not consent else available if available != "configured_not_live_validated"
                else "platform_disabled" if platform not in allowed else "subject_declared_account_ready")
            ready = reason == "subject_declared_account_ready"
            represented.add((seed.value.casefold(), platform))
            decisions.append(RoutingDecision(platform, seed.value, profile.url, "hybrid" if ready else "native",
                NATIVE_TOOLS, ACTORS[platform].actor if ready else None, reason,
                account_ownership(context.declared_seeds, platform, seed.value)))
        for entry in context.extra.get("social_native_profiles", [])[:128]:
            platform, username, url = canonical_platform(entry["platform"]), entry["username"], entry["url"]
            if (username.casefold(), platform) in represented:
                continue
            represented.add((username.casefold(), platform))
            spec = ACTORS.get(platform)
            reason = ("subject_consent_required" if not consent else available if available != "configured_not_live_validated"
                else "platform_not_supported" if not spec else "platform_disabled" if platform not in allowed
                else "awaiting_frontier_admission" if url not in visible else "native_observation_ready_for_public_enrichment")
            enrich = reason == "native_observation_ready_for_public_enrichment"
            decisions.append(RoutingDecision(platform, username, url, "hybrid" if enrich else "native",
                NATIVE_TOOLS, spec.actor if enrich else None, reason))
        for username in context.all_usernames():
            namespaces = [platform for value, platform in hints if value == username.casefold()] or [""]
            for platform in sorted(namespaces):
                if (username.casefold(), platform) not in represented:
                    decisions.append(RoutingDecision(platform, username, None, "native", NATIVE_TOOLS, None,
                        "awaiting_native_existence_observation" if platform in ACTORS else "multiplatform_discovery_first"))
        return sorted(decisions, key=lambda item: (
            (item.username.casefold(), item.platform) not in hints, item.platform, item.url or "", item.username))

    def enrichment_requests(self, context) -> list[RoutingDecision]:
        return [decision for decision in self.plan(context) if decision.actor]

    def explain(self, context) -> list[dict]:
        return [{**asdict(decision), "native_tools": list(decision.native_tools)} for decision in self.plan(context)]
