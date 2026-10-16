"""Declarative acquisition policy. Fair settings never mutate normal tool settings."""
from dataclasses import asdict, dataclass, field
from app.core.config import settings


@dataclass(frozen=True)
class SourcePlan:
    tool: str
    priority: int
    timeout_seconds: float
    scope: str = "context"
    first_wave: int = 1
    critical: bool = True
    enabled: bool = True
    cost_class: str = "native"
    can_pivot: bool = True
    max_invocations: int = 32
    reason: str | None = None


SOURCES = (
    SourcePlan("breach_checker", 0, 30, "email"),
    SourcePlan("apify_social", 1, 70, cost_class="paid", max_invocations=3),
    SourcePlan("gravatar_deep", 2, 20, "email"),
    SourcePlan("phone_lookup", 2, 20, "phone"),
    SourcePlan("search_dorker", 3, 65, max_invocations=3),
    SourcePlan("academic_finder", 3, 75, max_invocations=3),
    SourcePlan("ghunt", 4, 55, max_invocations=3),
    SourcePlan("github_deep_scanner", 4, 45, "username"),
    SourcePlan("email_checker", 5, 25, "email"),
    SourcePlan("username_finder", 5, 70, "username"),
    SourcePlan("social_verifier", 6, 30, max_invocations=3),
    SourcePlan("social_url_extractor", 6, 8, max_invocations=3),
    SourcePlan("email_enumerator", 8, 35, critical=False, max_invocations=2),
    SourcePlan("google_account_osint", 9, 35, critical=False, max_invocations=2),
    SourcePlan("domain_finder", 10, 25, first_wave=2, critical=False, max_invocations=2),
    *[SourcePlan(name, 100, 20, enabled=False, critical=False, reason=reason) for name, reason in (
        ("maigret_enricher", "deep_enrichment_outside_fast_preset"),
        ("keybase_resolver", "secondary_source_outside_fast_preset"),
        ("wikipedia_edits", "secondary_source_outside_fast_preset"),
        ("dni_lookup", "outside_fair_seed_scope"),
        ("reverse_image_search", "secondary_source_outside_fast_preset"),
        ("infostealer_checker", "optional_separate_consent_not_default_fair"))],
)


@dataclass(frozen=True)
class FairPlan:
    deadline_seconds: float = 225
    finalization_seconds: float = 20
    cancellation_seconds: float = 6
    checkpoint_seconds: float = 5
    progress_interval_seconds: float = 1
    max_waves: int = 3
    parallelism: int = 16
    optional_cutoff_fraction: float = .75
    latest_pivot_fraction: float = .9
    username_sites: int = 100
    search_queries: int = 8
    maigret_options: dict = field(default_factory=lambda: {"enrich": False, "parse": False, "retries": 0})
    apify_platforms: tuple[str, ...] = ("instagram", "tiktok", "youtube")
    frontier_limits: dict = field(default_factory=lambda: dict(max_per_round=6, max_total=12,
        cost_budget=100, min_priority=390, max_weak_per_round=0))
    sources: tuple[SourcePlan, ...] = SOURCES

    def __post_init__(self):
        import math
        numbers = (self.deadline_seconds, self.finalization_seconds, self.cancellation_seconds, self.checkpoint_seconds, self.progress_interval_seconds)
        if not all(math.isfinite(n) and n > 0 for n in numbers):
            raise ValueError("fair_time_budgets_must_be_positive_finite")
        if self.finalization_seconds + self.cancellation_seconds >= self.deadline_seconds:
            raise ValueError("fair_deadline_requires_acquisition_time")
        if not 1 <= self.max_waves <= 3 or self.parallelism < 1:
            raise ValueError("invalid_fair_scheduling_limits")
        if not 0 < self.optional_cutoff_fraction <= 1 or not 0 < self.latest_pivot_fraction <= 1:
            raise ValueError("invalid_fair_cutoff")

    @classmethod
    def configured(cls):
        from dataclasses import replace
        return cls(deadline_seconds=settings.fair_total_deadline_seconds,
            finalization_seconds=settings.fair_finalization_seconds,
            cancellation_seconds=settings.fair_cancellation_seconds,
            checkpoint_seconds=settings.fair_checkpoint_seconds,
            max_waves=settings.fair_max_waves, parallelism=settings.fair_parallelism,
            username_sites=settings.fair_username_sites, search_queries=settings.fair_search_queries,
            apify_platforms=tuple(settings.fair_apify_platforms),
            sources=tuple(replace(source, enabled=source.enabled and source.tool not in settings.fair_disabled_sources)
                          for source in SOURCES))

    def inspect(self, registry):
        return {**asdict(self), "sources": [{**asdict(source),
            "required_inputs": list(getattr(registry.get_tool(source.tool), "required_inputs", []))}
            for source in self.sources]}
