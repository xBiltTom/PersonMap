import importlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.runtime import durable_runtime
from app.engine.pivot_frontier import PivotFrontier, PivotSupport, pivot_id, frontier_from_metrics
from app.engine.pivot_rules import extract_and_apply_pivots
from app.engine.rule_engine import RuleEngine, SweepResult
from app.engine.hybrid_engine import HybridEngine
from app.models.target import Target
from app.tools.base import BaseTool, TargetContext, ToolFinding
from app.tools.registry import tool_registry


def profile(email, source="https://github.com/relevant", tool="social_verifier", **metadata):
    return ToolFinding(entity_type="social_account", value=source, metadata_info={
        "source_tool": tool, "verification_status": "verified", "extracted_emails": [email], **metadata})


def document(email, source="https://university.example/paper.pdf"):
    return ToolFinding(entity_type="document", value=source, metadata_info={
        "source_tool": "search_dorker", "source_kind": "public_document", "extracted_emails": [email]})


def snippet(email, source="https://search.example/result"):
    return ToolFinding(entity_type="search_mention", value=source, metadata_info={
        "source_tool": "search_dorker", "extracted_emails": [email]})


@pytest.fixture(autouse=True)
def policy(monkeypatch):
    monkeypatch.setattr(settings, "pivot_frontier_enabled", True)
    monkeypatch.setattr(settings, "pivot_max_per_round", 12)
    monkeypatch.setattr(settings, "pivot_max_total", 128)
    monkeypatch.setattr(settings, "pivot_max_weak_per_round", 2)
    monkeypatch.setattr(settings, "pivot_min_priority", 0)
    monkeypatch.setattr(settings, "pivot_round_cost_budget", 100)


def candidates(context):
    return {c.value: c for c in PivotFrontier(context).rank()}


def test_seed_has_maximum_priority_for_all_supported_input_types():
    target = Target(email="seed@example.org", username="seeduser", full_name="Seed User",
        phone="+51987654321", dni="12345678", extra_data={
            "identifiers": [{"id_type": "orcid", "value": "0000-0002-1825-0097"}],
            "url": "https://example.org/seed"})
    context = TargetContext(email=target.email, username=target.username)
    frontier = PivotFrontier(context)
    frontier.seed(target)
    seeds = [c for c in frontier.rank() if c.confidence_class == "P0"]
    assert len(seeds) == 7
    assert {c.pivot_priority for c in seeds} == {1000}


def test_profile_contact_outranks_incidental_document_contact():
    ctx = TargetContext()
    extract_and_apply_pivots([document("professor@university.edu"), profile("author@example.org")], ctx)
    found = candidates(ctx)
    assert found["author@example.org"].confidence_class == "P1"
    assert found["professor@university.edu"].confidence_class == "P3"
    assert found["author@example.org"].pivot_priority > found["professor@university.edu"].pivot_priority
    assert "mention_email" in found["professor@university.edu"].reasons


def test_independent_sources_raise_priority_and_consolidate_one_pivot():
    ctx = TargetContext()
    email = "shared@example.org"
    extract_and_apply_pivots([profile(email)], ctx)
    initial = candidates(ctx)[email].pivot_priority
    extract_and_apply_pivots([profile(email, "https://gravatar.com/profile/relevant", "gravatar_deep")], ctx)
    c = candidates(ctx)[email]
    assert ctx.all_emails() == [email]
    assert c.support_count == 2
    assert c.independent_source_count == 2
    assert c.pivot_priority > initial


def test_duplicate_observations_and_provider_adapters_do_not_inflate_independence():
    ctx = TargetContext()
    email = "shared@example.org"
    observed = profile(email)
    extract_and_apply_pivots([observed, observed], ctx)
    extract_and_apply_pivots([observed], ctx)
    c = candidates(ctx)[email]
    assert (c.support_count, c.independent_source_count) == (1, 1)
    extract_and_apply_pivots([profile(email, "https://api.github.com/users/relevant", "github_deep_scanner")], ctx)
    assert candidates(ctx)[email].independent_source_count == 1


def test_support_keeps_existing_trace_references():
    ctx = TargetContext()
    extract_and_apply_pivots([profile("email@example.org", source_tool_execution_id="execution-123",
        source_observation_id="observation-456")], ctx)
    support = candidates(ctx)["email@example.org"].supports[0]
    assert support.source_execution_id == "execution-123"
    assert support.source_observation_id == "observation-456"


def test_derivative_source_and_exact_lookup_echo_do_not_create_corroboration():
    ctx = TargetContext()
    email = "shared@example.org"
    extract_and_apply_pivots([profile(email), profile(email, "https://mirror.example/a", original_source_url="https://github.com/relevant")], ctx)
    echo = ToolFinding(entity_type="social_account", value="https://gravatar.com/profile/a", metadata_info={
        "source_tool": "gravatar_deep", "email": email})
    extract_and_apply_pivots([echo], ctx)
    assert candidates(ctx)[email].independent_source_count == 1


def test_contextual_corroboration_is_p2_and_stays_below_explicit_contact():
    ctx = TargetContext()
    extract_and_apply_pivots([document("context@example.org"), document("context@example.org", "https://publisher.example/article"),
                              profile("declared@example.org")], ctx)
    found = candidates(ctx)
    assert found["context@example.org"].confidence_class == "P2"
    assert found["declared@example.org"].pivot_priority > found["context@example.org"].pivot_priority


def test_weak_pivot_survives_budget_and_is_released_in_deep_mode(monkeypatch):
    monkeypatch.setattr(settings, "pivot_max_weak_per_round", 0)
    monkeypatch.setattr(settings, "pivot_min_priority", 300)
    ctx = TargetContext()
    extract_and_apply_pivots([snippet("weak@example.org")], ctx)
    frontier = PivotFrontier(ctx)
    frontier.next(1)
    weak = frontier.candidates[pivot_id("email", "weak@example.org")]
    assert weak.status == "deferred"
    assert "weak@example.org" in ctx.all_emails()
    assert "weak@example.org" not in frontier.execution_view().all_emails()
    assert any(c.value == "weak@example.org" for c in frontier.next(2, "deep"))
    assert "weak@example.org" in frontier.execution_view().all_emails()


def test_round_budget_selects_p1_then_p2_before_p4(monkeypatch):
    monkeypatch.setattr(settings, "pivot_max_per_round", 2)
    ctx = TargetContext()
    # No URLs here: use the real extraction but isolate the email candidates.
    extract_and_apply_pivots([profile("strong@example.org"), document("corroborated@example.org"),
        document("corroborated@example.org", "https://second.example/paper"), snippet("weak@example.org")], ctx)
    ctx.extra["candidate_urls"] = []
    frontier = PivotFrontier(ctx)
    frontier.candidates = {k: c for k, c in frontier.candidates.items() if c.type == "email"}
    selected = frontier.next(1)
    assert [c.value for c in selected] == ["strong@example.org", "corroborated@example.org"]
    assert frontier.candidates[pivot_id("email", "weak@example.org")].status == "deferred"


def test_total_and_cost_budgets_defer_without_deleting(monkeypatch):
    monkeypatch.setattr(settings, "pivot_max_total", 1)
    ctx = TargetContext(discovered_emails=["a@example.org", "b@example.org"])
    frontier = PivotFrontier(ctx)
    frontier.sync(0)
    assert len(frontier.next(1, "deep")) == 1
    assert len(frontier.candidates) == 2
    assert sum(c.status == "deferred" for c in frontier.candidates.values()) == 1
    monkeypatch.setattr(settings, "pivot_round_cost_budget", 1)
    ctx2 = TargetContext(discovered_usernames=["expensive"])
    frontier2 = PivotFrontier(ctx2)
    frontier2.sync(0)
    assert frontier2.next(1, "deep") == []
    assert next(iter(frontier2.candidates.values())).deferred_reason == "round exploration cost budget"


def test_roundtrip_preserves_pending_explored_and_provenance():
    ctx = TargetContext(email="seed@example.org")
    frontier = PivotFrontier(ctx)
    frontier.seed()
    frontier.next(1)
    frontier.mark_explored(frontier.execution_view(), [tool_registry.get_tool("gravatar_deep")], {"gravatar_deep"})
    state = json.loads(json.dumps(durable_runtime(ctx.extra)))
    snapshot = frontier_from_metrics({"collection_runtime": state})
    assert snapshot["summary"]["explored"] == 1
    assert snapshot["explored"][0]["explored_by"] == ["gravatar_deep"]
    assert snapshot["explored"][0]["supports"][0]["source_tool"] == "target_input"
    forbidden = {"identity_probability", "ownership_probability", "same_person_probability"}
    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(v) for v in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(v) for v in value))
        return set()
    assert not keys(snapshot) & forbidden


def test_view_merge_keeps_deferred_inputs_and_tool_runtime_mutations(monkeypatch):
    monkeypatch.setattr(settings, "pivot_max_weak_per_round", 0)
    ctx = TargetContext(email="seed@example.org", discovered_emails=["deferred@example.org"],
        extra={"candidate_urls": ["https://weak.example/u"], "phone_observations": {}})
    frontier = PivotFrontier(ctx)
    frontier.seed()
    frontier.next(1)
    view = frontier.execution_view()
    assert view.all_emails() == ["seed@example.org"]
    view.discovered_emails.append("new@example.org")
    view.extra["candidate_urls"].append("https://new.example/u")
    view.extra["search_queries_used"] = 2
    frontier.merge_view(view)
    assert set(ctx.all_emails()) == {"seed@example.org", "deferred@example.org", "new@example.org"}
    assert ctx.extra["candidate_urls"] == ["https://weak.example/u", "https://new.example/u"]
    assert ctx.extra["search_queries_used"] == 2


class EmailProbe:
    name = "email_probe"
    description = "Fixture: one simulated lookup per email"
    required_inputs = ["email"]

    def __init__(self, calls, fail=False):
        self.calls, self.fail = calls, fail

    def can_run(self, context):
        return bool(context.all_emails())

    async def execute(self, context):
        self.calls.append(list(context.all_emails()))
        if self.fail:
            raise RuntimeError("fixture failure")
        return []


@pytest.mark.asyncio
async def test_rule_engine_deep_eventually_dispatches_weak_and_records_trace(monkeypatch):
    calls, events = [], []
    tool = EmailProbe(calls)
    monkeypatch.setattr(tool_registry, "_tools", {tool.name: tool})
    monkeypatch.setattr(settings, "pivot_max_per_round", 1)
    monkeypatch.setattr(settings, "pivot_max_weak_per_round", 0)
    ctx = TargetContext(email="seed@example.org")
    extract_and_apply_pivots([document("context@example.org"), snippet("weak@example.org")], ctx)
    async def publish(identifier, event):
        events.append(event)
    module = importlib.import_module("app.engine.rule_engine")
    monkeypatch.setattr(module.event_bus, "publish", publish)
    result = await RuleEngine().collect_findings("fixture", Target(email=ctx.email, extra_data={"pivot_frontier_mode": "deep"}), initial_context=ctx)
    assert calls[0] == ["seed@example.org", "context@example.org"]
    assert calls[1] == ["seed@example.org", "context@example.org", "weak@example.org"]
    frontier = PivotFrontier(result.context)
    assert candidates(result.context)["weak@example.org"].status == "explored"
    assert len(result.executed_runs) == 2
    assert any(e.get("phase") == "pivot_frontier" for e in events)
    assert frontier.duplicate_executions_avoided >= 1


@pytest.mark.asyncio
async def test_disabled_frontier_retains_accumulated_context_and_exact_run_keys(monkeypatch):
    monkeypatch.setattr(settings, "pivot_frontier_enabled", False)
    calls = []
    tool = EmailProbe(calls)
    monkeypatch.setattr(tool_registry, "_tools", {tool.name: tool})
    ctx = TargetContext(email="seed@example.org", discovered_emails=["weak@example.org"])
    result = await RuleEngine().collect_findings("fixture", Target(email=ctx.email), initial_context=ctx)
    assert calls == [["seed@example.org", "weak@example.org"]]
    assert "pivot_frontier" not in result.context.extra
    assert result.executed_runs == {"email_probe|e:seed@example.org,weak@example.org"}
    from app.services.workspace import WorkspaceService
    inv = SimpleNamespace(id=uuid4(), target=Target(email=ctx.email), metrics={
        "collection_runtime": {"search_queries_used": 7, "pivot_frontier": {"candidates": {}}}})
    restored = WorkspaceService()._context(inv, [])
    assert "pivot_frontier" not in restored.extra
    assert "search_queries_used" not in restored.extra


@pytest.mark.asyncio
async def test_failed_tool_does_not_mark_pivot_explored(monkeypatch):
    tool = EmailProbe([], fail=True)
    monkeypatch.setattr(tool_registry, "_tools", {tool.name: tool})
    result = await RuleEngine().collect_findings("fixture", Target(email="seed@example.org"))
    pivot = candidates(result.context)["seed@example.org"]
    assert pivot.status == "pending"
    assert pivot.explored_by == []


def test_hybrid_gets_compact_deterministic_unresolved_frontier():
    ctx = TargetContext(email="seed@example.org")
    frontier = PivotFrontier(ctx)
    frontier.seed()
    extract_and_apply_pivots([document("professor@university.edu"), profile("strong@example.org"), snippet("weak@example.org")], ctx)
    before = durable_runtime(ctx.extra)
    digest = HybridEngine()._build_digest(Target(email=ctx.email), SweepResult(context=ctx))
    assert "high_priority_unresolved" in digest
    assert "strong@example.org" in digest
    assert "medium_unresolved" in digest
    assert "weak_available" in digest
    assert durable_runtime(ctx.extra) == before


@pytest.mark.asyncio
async def test_frontier_endpoint_reads_persisted_runtime_without_database_migration():
    from app.api.v1.investigations import get_investigation_frontier
    ctx = TargetContext(email="seed@example.org")
    PivotFrontier(ctx).seed()
    class DB:
        async def get(self, model, key):
            return SimpleNamespace(metrics={"collection_runtime": durable_runtime(ctx.extra)})
    result = await get_investigation_frontier(uuid4(), DB())
    assert result["pivot_frontier"]["summary"]["total"] == 1


def test_case_sensitive_typed_ids_and_url_aliases_keep_their_existing_identity():
    assert pivot_id("yelp_userid", "AbCd") != pivot_id("yelp_userid", "abcd")
    assert pivot_id("url", "https://www.github.com/example/?utm_source=x") == pivot_id("url", "https://github.com/example")
    assert pivot_id("email", "User@Example.org") == pivot_id("email", "user@example.org")


def test_format_validation_alone_does_not_strengthen_document_association():
    ctx = TargetContext()
    email = "professor@university.edu"
    extract_and_apply_pivots([document(email)], ctx)
    score = candidates(ctx)[email].pivot_priority
    extract_and_apply_pivots([ToolFinding(entity_type="email", value=email,
        metadata_info={"source_tool": "email_checker"})], ctx)
    c = candidates(ctx)[email]
    assert c.confidence_class == "P3"
    assert c.pivot_priority == score
    assert c.independent_source_count == 1


def test_seed_and_discovery_rounds_are_distinct():
    ctx = TargetContext(email="seed@example.org", extra={"pivot_round": 2})
    extract_and_apply_pivots([profile("new@example.org")], ctx)
    found = candidates(ctx)
    assert found["seed@example.org"].discovered_round == 0
    assert found["seed@example.org"].confidence_class == "P0"
    assert found["new@example.org"].discovered_round == 2


@pytest.mark.asyncio
async def test_discovered_only_inputs_reach_legacy_primary_field_tools(monkeypatch):
    calls = []
    class LegacyEmail(BaseTool):
        name = "legacy_email"
        description = "Uses BaseTool.can_run and context.email"
        required_inputs = ["email"]
        async def execute(self, context):
            calls.append(context.email)
            return []
    tool = LegacyEmail()
    monkeypatch.setattr(tool_registry, "_tools", {tool.name: tool})
    ctx = TargetContext(username="seeduser")
    extract_and_apply_pivots([profile("new@example.org")], ctx)
    result = await RuleEngine().collect_findings("fixture", Target(username=ctx.username), initial_context=ctx)
    assert calls == ["new@example.org"]
    assert result.context.email is None  # A discovered contact does not become the user's seed.
    assert candidates(result.context)["new@example.org"].status == "explored"


def test_api_mode_is_explicit_and_does_not_change_username_scan_mode():
    from app.schemas.investigation import InvestigationCreate
    payload = InvestigationCreate(target={"username": "seeduser"}, pivot_mode="deep")
    assert payload.pivot_mode == "deep"
    assert payload.maigret_plan is None
    with pytest.raises(ValueError):
        InvestigationCreate(target={"username": "seeduser"}, pivot_mode="unbounded")
    with pytest.raises(ValueError, match="array"):
        PivotFrontier(TargetContext()).suggest({"candidate_urls": 123}, 1)
    frontier = PivotFrontier(TargetContext())
    frontier.seed(Target(username="seeduser", extra_data={"identifiers": ["legacy malformed input"]}))
    assert [c.type for c in frontier.rank()] == ["username"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected_calls", [("standard", 0), ("deep", 1)])
async def test_hybrid_respects_admission_and_records_actual_exploration(monkeypatch, mode, expected_calls):
    module = importlib.import_module("app.engine.hybrid_engine")
    tool = EmailProbe([])
    monkeypatch.setattr(tool_registry, "_tools", {tool.name: tool})
    monkeypatch.setattr(settings, "pivot_max_weak_per_round", 0)
    monkeypatch.setattr(settings, "hybrid_max_refinement_turns", 1)
    ctx = TargetContext(email="seed@example.org", extra={"pivot_frontier_mode": mode})
    frontier = PivotFrontier(ctx)
    frontier.seed()
    frontier.next(1)
    frontier.mark_explored(frontier.execution_view(), [tool], {tool.name})
    args = {"email": "suggested@example.org", "evidence_role": "declared_email", "confidence_class": "P1"}
    calls = [SimpleNamespace(id="c1", function=SimpleNamespace(name=tool.name, arguments=json.dumps(args)))]
    async def reply(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=calls))])
    dispatched = []
    async def dispatch(name, args, target, **kwargs):
        dispatched.append(args["email"])
        assert "suggested@example.org" in kwargs["base_context"].all_emails()
        return []
    monkeypatch.setattr(module, "complete_with_retries", reply)
    monkeypatch.setattr(module, "dispatch_tool_call", dispatch)
    result = await HybridEngine()._refine_with_llm("fixture", Target(email=ctx.email), SweepResult(context=ctx, rounds=1))
    assert len(dispatched) == expected_calls
    c = candidates(ctx)["suggested@example.org"]
    assert c.confidence_class == "P4"  # LLM-supplied evidence fields have no authority.
    assert c.independent_source_count == 0
    assert c.status == ("explored" if mode == "deep" else "deferred")
    assert result[3] == (1 if mode == "standard" else 0)


@pytest.mark.asyncio
async def test_multiple_llm_calls_cannot_reset_one_turn_budget(monkeypatch):
    module = importlib.import_module("app.engine.hybrid_engine")
    tool = EmailProbe([])
    monkeypatch.setattr(tool_registry, "_tools", {tool.name: tool})
    monkeypatch.setattr(settings, "pivot_max_per_round", 1)
    monkeypatch.setattr(settings, "hybrid_max_refinement_turns", 1)
    ctx = TargetContext(email="seed@example.org", extra={"pivot_frontier_mode": "deep"})
    frontier = PivotFrontier(ctx)
    frontier.seed()
    frontier.next(1)
    frontier.mark_explored(frontier.execution_view(), [tool], {tool.name})
    tool_calls = [SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=tool.name,
        arguments=json.dumps({"email": f"suggestion{i}@example.org"}))) for i in range(3)]
    async def reply(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=tool_calls))])
    dispatched = []
    async def dispatch(name, args, target, **kwargs):
        dispatched.append(args["email"])
        return []
    monkeypatch.setattr(module, "complete_with_retries", reply)
    monkeypatch.setattr(module, "dispatch_tool_call", dispatch)
    await HybridEngine()._refine_with_llm("fixture", Target(email=ctx.email), SweepResult(context=ctx, rounds=1))
    assert dispatched == ["suggestion0@example.org"]
    found = candidates(ctx)
    assert found["suggestion1@example.org"].status == "deferred"
    assert found["suggestion2@example.org"].status == "deferred"
