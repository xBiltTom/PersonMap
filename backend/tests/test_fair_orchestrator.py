"""Fair acquisition with real Frontier and synthetic providers; no external services."""
import asyncio
from dataclasses import replace
import json
from time import perf_counter
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import settings
from app.core.events import event_bus
from app.engine.fair_engine import FairEngine
from app.engine.fair_plan import FairPlan, SourcePlan
from app.engine.pivot_frontier import PivotFrontier
from app.models.target import Target
from app.schemas.investigation import InvestigationCreate
from app.schemas.target import TargetCreate
from app.social.router import SocialSourceRouter
from app.tools.base import BaseTool, ToolCategory, ToolFinding
from app.tools.registry import tool_registry


class Stub(BaseTool):
    description = "Synthetic acquisition source"
    category = ToolCategory.SOCIAL
    def __init__(self, name, fn, required=("username",), ready=None):
        self.name, self.fn, self.required_inputs, self.ready = name, fn, list(required), ready
    async def execute(self, context):
        return await self.fn(context)
    def can_run(self, context):
        return self.ready(context) if self.ready else super().can_run(context)
    def input_fingerprint(self, context):
        return json.dumps([(r.platform, r.url) for r in SocialSourceRouter().enrichment_requests(context)])


def target(**kwargs):
    row = Target(id=uuid4(), **TargetCreate(**({"usernames": [{"username": "seed_alias"}]} | kwargs)).persistence_values())
    row.extra_data["subject_consent"] = True
    return row


def engine(monkeypatch, tools, sources=None, **options):
    monkeypatch.setattr(tool_registry, "_tools", {tool.name: tool for tool in tools})
    plan = FairPlan(deadline_seconds=options.pop("deadline_seconds", 10), finalization_seconds=.04,
        cancellation_seconds=.03, checkpoint_seconds=.03, progress_interval_seconds=.005,
        sources=tuple(sources or [SourcePlan(tool.name, index, 5) for index, tool in enumerate(tools)]), **options)
    return FairEngine(tool_registry, plan)


async def nothing(context):
    return []


@pytest.fixture(autouse=True)
def no_paid_calls(monkeypatch):
    monkeypatch.setattr(settings, "apify_enabled", False)
    monkeypatch.setattr(settings, "pivot_frontier_enabled", True)


@pytest.mark.asyncio
async def test_independent_sources_start_concurrently(monkeypatch):
    started, both = set(), asyncio.Event()
    def fn(name):
        async def execute(context):
            started.add(name)
            if len(started) == 2:
                both.set()
            await both.wait()
            return []
        return execute
    runner = engine(monkeypatch, [Stub("search_dorker", fn("search")), Stub("username_finder", fn("username"))])
    run = await runner.collect_findings(str(uuid4()), target())
    assert both.is_set() and all(s["status"] == "completed" for s in run.sources.values())
    assert not run.deadline_reached


@pytest.mark.asyncio
async def test_declared_apify_starts_without_waiting_for_native_discovery(monkeypatch):
    monkeypatch.setattr(settings, "apify_enabled", True)
    monkeypatch.setattr(settings, "apify_token", SecretStr("synthetic-token"))
    monkeypatch.setattr(settings, "apify_platforms", ["instagram"])
    native_started, apify_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def native(ctx):
        native_started.set()
        await release.wait()
        return []
    async def social(ctx):
        assert not ctx.extra.get("social_native_profiles")
        apify_started.set()
        return []
    tools = [Stub("username_finder", native), Stub("apify_social", social, required=("username", "candidate_urls"),
        ready=lambda c: bool(SocialSourceRouter().enrichment_requests(c)))]
    runner = engine(monkeypatch, tools)
    task = asyncio.create_task(runner.collect_findings(str(uuid4()), target(usernames=[{"username": "apify", "platform": "instagram"}])))
    await asyncio.wait_for(apify_started.wait(), 2)
    await asyncio.wait_for(native_started.wait(), 2)
    release.set()
    run = await task
    assert run.sources["apify_social"]["status"] == "completed"


@pytest.mark.asyncio
async def test_deadline_cancels_slow_source_and_preserves_completed_findings(monkeypatch):
    cancelled = asyncio.Event()
    async def fast(ctx):
        await asyncio.sleep(.005)
        return [ToolFinding(entity_type="email", value="found@example.org")]
    async def slow(ctx):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
    runner = engine(monkeypatch, [Stub("search_dorker", fast), Stub("username_finder", slow)], deadline_seconds=.18)
    before = perf_counter()
    run = await runner.collect_findings(str(uuid4()), target())
    assert perf_counter() - before < .4
    assert cancelled.is_set() and len(run.findings) == 1 and run.deadline_reached
    assert run.sources["username_finder"]["status"] == "timeout"
    assert run.snapshot()["execution"]["partial"]


@pytest.mark.asyncio
async def test_source_failures_skips_and_missing_inputs_are_distinct(monkeypatch):
    async def broken(c):
        raise RuntimeError("do not expose this secret")
    tools = [Stub("search_dorker", broken), Stub("username_finder", nothing), Stub("phone_lookup", nothing, ("phone",))]
    sources = [SourcePlan("search_dorker", 1, .1), SourcePlan("username_finder", 2, .1, enabled=False),
               SourcePlan("phone_lookup", 2, .1)]
    run = await engine(monkeypatch, tools, sources).collect_findings(str(uuid4()), target())
    assert run.sources["search_dorker"]["status"] == "failed"
    assert run.sources["username_finder"]["status"] == "skipped"
    assert run.sources["phone_lookup"]["status"] == "not_applicable"
    assert "secret" not in json.dumps(run.snapshot())


@pytest.mark.asyncio
async def test_apify_disabled_leaves_native_acquisition_operational(monkeypatch):
    from app.tools.apify_social import ApifySocialTool
    runner = engine(monkeypatch, [Stub("username_finder", nothing), ApifySocialTool()])
    run = await runner.collect_findings(str(uuid4()), target(usernames=[{"username": "apify", "platform": "instagram"}]))
    assert run.sources["apify_social"]["status"] == "provider_unavailable"
    assert run.sources["username_finder"]["status"] == "completed"
    assert run.context.extra["apify_runtime"]["runs"] == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("frontier_flag", [True, False])
async def test_strong_native_profile_feeds_same_investigation_wave_two(monkeypatch, frontier_flag):
    monkeypatch.setattr(settings, "pivot_frontier_enabled", frontier_flag)
    monkeypatch.setattr(settings, "apify_enabled", True)
    monkeypatch.setattr(settings, "apify_token", SecretStr("synthetic-token"))
    monkeypatch.setattr(settings, "apify_platforms", ["instagram"])
    urls = []
    async def native(c):
        return [ToolFinding(entity_type="social_account", platform="instagram", value="https://instagram.com/fresh_alias",
            metadata_info={"username": "fresh_alias", "verification_status": "verified"})]
    async def social(c):
        urls.extend(r.url for r in SocialSourceRouter().enrichment_requests(c))
        return [ToolFinding(entity_type="social_account", platform="instagram", value=urls[-1],
                            metadata_info={"provider": "apify"})]
    runner = engine(monkeypatch, [Stub("social_verifier", native), Stub("apify_social", social, required=("username", "candidate_urls"),
        ready=lambda c: bool(SocialSourceRouter().enrichment_requests(c)))])
    run = await runner.collect_findings(str(uuid4()), target())
    assert urls == ["https://instagram.com/fresh_alias"], (run.sources, run.snapshot()["pivots"], run.context.extra.get("social_native_profiles"))
    assert run.sources["apify_social"]["attempts"][0]["wave"] == 2
    assert run.findings[-1].metadata_info.get("ownership_status") != "subject_declared"


@pytest.mark.asyncio
async def test_weak_pivot_does_not_consume_second_wave(monkeypatch):
    async def weak(c):
        return [ToolFinding(entity_type="search_mention", value="https://example.org/article",
            metadata_info={"extracted_usernames": ["weak_candidate"], "evidence_level": "snippet"})]
    calls = []
    async def scan(c):
        calls.extend(c.all_usernames())
        return []
    runner = engine(monkeypatch, [Stub("search_dorker", weak), Stub("username_finder", scan)])
    run = await runner.collect_findings(str(uuid4()), target())
    assert calls == ["seed_alias"]
    assert any(c.value == "weak_candidate" and c.status == "deferred" for c in PivotFrontier(run.context).candidates.values())


@pytest.mark.asyncio
async def test_all_declared_emails_keep_separate_breach_observations(monkeypatch):
    from app.tools.breach_checker import BreachCheckerTool
    from app.tools import http_client
    emails = ["one@example.org", "two@example.org", "three@example.org"]
    observed = []
    def respond(request):
        email = request.url.path.rsplit("/", 1)[-1]
        observed.append(email)
        return httpx.Response(200, json={"breaches": [["Breach:" + email]]})
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    runner = engine(monkeypatch, [BreachCheckerTool()], [SourcePlan("breach_checker", 0, .2, "email")])
    run = await runner.collect_findings(str(uuid4()), target(usernames=[], emails=emails))
    assert observed == emails
    assert {finding.value for finding in run.findings} == set(emails)
    assert all(f.metadata_info["breaches"] == ["Breach:" + f.value] for f in run.findings)
    assert all(a["wave"] == 1 for a in run.sources["breach_checker"]["attempts"])


@pytest.mark.asyncio
async def test_all_declared_usernames_are_planned_individually(monkeypatch):
    observed = []
    async def scan(c):
        assert c.extra["username_scan_mode"] == "fast"
        assert c.extra["maigret_options"] == {"enrich": False, "parse": False, "retries": 0}
        observed.extend(c.all_usernames())
        return []
    runner = engine(monkeypatch, [Stub("username_finder", scan)], [SourcePlan("username_finder", 1, .2, "username")])
    await runner.collect_findings(str(uuid4()), target(usernames=[{"username": name} for name in ["first", "second", "third"]]))
    assert observed == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_checkpoint_failure_keeps_findings_and_can_recover(monkeypatch):
    attempts = []
    async def fast(c):
        return [ToolFinding(entity_type="email", value="observed@example.org")]
    async def save(run):
        attempts.append(len(run.findings))
        if len(attempts) == 1:
            raise RuntimeError("transient database failure")
    run = await engine(monkeypatch, [Stub("search_dorker", fast)]).collect_findings(str(uuid4()), target(), checkpoint=save)
    assert run.persistence == "persisted" and run.persistence_errors == 1
    assert len(run.findings) == 1 and attempts[-1] == 1


@pytest.mark.asyncio
async def test_failed_persistence_is_reported_without_erasing_partial_results(monkeypatch):
    async def save(run):
        raise RuntimeError("database unavailable")
    run = await engine(monkeypatch, [Stub("search_dorker", nothing)]).collect_findings(str(uuid4()), target(), checkpoint=save)
    assert run.persistence == "partial"
    assert run.snapshot()["execution"]["partial"]


@pytest.mark.asyncio
async def test_partial_http_failure_is_not_reported_as_no_profile(monkeypatch):
    from app.tools import http_client
    async def failing(c):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
            await http_client.get(client, "https://example.org/")
        return []
    run = await engine(monkeypatch, [Stub("search_dorker", failing)]).collect_findings(str(uuid4()), target())
    assert run.sources["search_dorker"]["status"] == "failed"


def test_mode_is_explicit_and_normal_schema_preserves_strategies():
    normal = InvestigationCreate(target=TargetCreate(username="fixture"))
    assert normal.acquisition_mode == "normal" and normal.strategy == "auto"
    fair = InvestigationCreate(target=TargetCreate(username="fixture"), acquisition_mode="fair", strategy="hybrid")
    assert fair.acquisition_mode == "fair"
    with pytest.raises(ValidationError):
        InvestigationCreate(target=TargetCreate(username="fixture"), acquisition_mode="fair", execution_mode="external")


def test_plan_has_critical_breach_and_excludes_unvalidated_social_by_default(monkeypatch):
    monkeypatch.setattr(settings, "personmap_env", "normal")
    monkeypatch.setattr(settings, "fair_apify_platforms", ["instagram", "tiktok", "youtube"])
    plan = FairPlan.configured()
    breach = next(s for s in plan.sources if s.tool == "breach_checker")
    assert breach.priority == 0 and breach.first_wave == 1 and breach.critical
    assert set(plan.apify_platforms) == {"instagram", "tiktok", "youtube"}
    assert plan.max_waves <= 3 and plan.deadline_seconds == 225


@pytest.mark.asyncio
async def test_progress_and_snapshot_share_existing_event_bus(monkeypatch):
    inv_id = str(uuid4())
    run = await engine(monkeypatch, [Stub("search_dorker", nothing)]).collect_findings(inv_id, target())
    history = event_bus.get_history(inv_id)
    assert history[0]["type"] == "fair_progress"
    assert history[-1]["type"] == "fair_snapshot"
    assert history[-1]["snapshot"]["execution"]["semantics"] == "discovery_not_attributed_dataset"
    assert run.phase == "complete"


@pytest.mark.asyncio
async def test_waves_stop_after_three_generations_of_strong_pivots(monkeypatch):
    calls = []
    async def chain(ctx):
        calls.append(ctx.email)
        index = int(ctx.email.split("@")[0][1:])
        return [ToolFinding(entity_type="social_account", platform="instagram", value=f"https://instagram.com/u{index}",
            metadata_info={"verification_status": "verified", "extracted_emails": [f"e{index+1}@example.org"]})]
    runner = engine(monkeypatch, [Stub("gravatar_deep", chain, ("email",))],
        [SourcePlan("gravatar_deep", 1, 1, "email")])
    run = await runner.collect_findings(str(uuid4()), target(usernames=[], emails=["e0@example.org"]))
    assert calls == ["e0@example.org", "e1@example.org", "e2@example.org"]
    assert [a["wave"] for a in run.sources["gravatar_deep"]["attempts"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_optional_source_is_cancelled_before_acquisition_deadline(monkeypatch):
    async def slow(ctx):
        await asyncio.sleep(10)
        return []
    runner = engine(monkeypatch, [Stub("username_finder", nothing), Stub("google_account_osint", slow)],
        [SourcePlan("username_finder", 1, 1), SourcePlan("google_account_osint", 2, 1, critical=False)], deadline_seconds=.3)
    run = await runner.collect_findings(str(uuid4()), target())
    assert not run.deadline_reached
    assert run.sources["username_finder"]["status"] == "completed"
    assert run.sources["google_account_osint"]["attempts"][0]["reason"] == "optional_time_budget"


@pytest.mark.asyncio
async def test_cancellation_resistant_source_cannot_hold_snapshot_open(monkeypatch):
    release = asyncio.Event()
    async def resistant(ctx):
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
        return []
    runner = engine(monkeypatch, [Stub("username_finder", resistant)], deadline_seconds=.18)
    before = perf_counter()
    run = await runner.collect_findings(str(uuid4()), target())
    assert perf_counter()-before < .35 and run.cleanup_pending
    assert run.sources["username_finder"]["status"] == "timeout"
    release.set()
    await asyncio.sleep(.01)


@pytest.mark.asyncio
async def test_fair_uses_existing_apify_batch_ledger_and_profile_charge_caps(monkeypatch):
    from app.tools.apify_social import ApifySocialTool, execution_summary
    from app.social.apify_client import ApifyRunResult
    calls = []
    class Client:
        async def run(self, spec, submitted, item_limit, charge_limit, *, on_update):
            calls.append((submitted, item_limit, charge_limit))
            return ApifyRunResult(actor=spec.actor, status="SUCCEEDED", items=[
                {"username": name, "url": f"https://instagram.com/{name}", "fullName": name}
                for name in submitted["usernames"]])
    for key, value in {"apify_enabled": True, "apify_token": SecretStr("synthetic-token"),
        "apify_platforms": ["instagram"], "apify_max_profiles_per_actor": 2, "apify_max_runs": 1,
        "apify_max_actors": 1, "apify_max_charge_per_investigation_usd": .05,
        "apify_max_charge_per_run_usd": .05}.items():
        monkeypatch.setattr(settings, key, value)
    runner = engine(monkeypatch, [ApifySocialTool(Client)])
    run = await runner.collect_findings(str(uuid4()), target(usernames=[
        {"username": name, "platform": "instagram"} for name in ["first", "second", "third"]]))
    assert len(calls) == 1 and len(calls[0][0]["usernames"]) == 2
    assert len(run.findings) == 2
    assert execution_summary(run.context)["reserved_charge_usd"] == .05
    assert execution_summary(run.context)["runs_reserved"] == 1
    assert run.sources["apify_social"]["status"] == "partial"


@pytest.mark.asyncio
async def test_wave_two_can_run_while_slow_wave_one_source_is_still_active(monkeypatch):
    monkeypatch.setattr(settings, "apify_enabled", True)
    monkeypatch.setattr(settings, "apify_token", SecretStr("synthetic-token"))
    monkeypatch.setattr(settings, "apify_platforms", ["instagram"])
    enriched = asyncio.Event()
    async def native(ctx):
        return [ToolFinding(entity_type="social_account", platform="instagram", value="https://instagram.com/new_profile",
            metadata_info={"verification_status": "verified", "username": "new_profile"})]
    async def slow(ctx):
        await enriched.wait()
        return []
    async def social(ctx):
        enriched.set()
        return []
    runner = engine(monkeypatch, [Stub("social_verifier", native), Stub("username_finder", slow),
        Stub("apify_social", social, required=("username", "candidate_urls"),
            ready=lambda c: bool(SocialSourceRouter().enrichment_requests(c)))])
    run = await runner.collect_findings(str(uuid4()), target())
    assert enriched.is_set() and run.sources["username_finder"]["status"] == "completed"
    assert run.sources["apify_social"]["attempts"][0]["wave"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "fair"])
async def test_master_dispatch_keeps_normal_engine_and_fair_skips_ai(monkeypatch, mode):
    import importlib
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    module = importlib.import_module("app.engine.orchestrator")
    fair_module = importlib.import_module("app.engine.fair_engine")
    inv = SimpleNamespace(id=uuid4(), target=target(), strategy="rule_based",
                          metrics={"acquisition_mode": mode}, status="pending")
    class Result:
        def scalar_one_or_none(self):
            return inv
        def scalars(self):
            return self
        def all(self):
            return []
    db = SimpleNamespace(execute=AsyncMock(return_value=Result()), commit=AsyncMock(), flush=AsyncMock(), add=lambda row: None)
    @asynccontextmanager
    async def session():
        yield db
    monkeypatch.setattr(module, "async_session_maker", session)
    normal = AsyncMock(return_value=[])
    fair = AsyncMock()
    enrich = AsyncMock(return_value={})
    monkeypatch.setattr(module.rule_engine, "execute_investigation", normal)
    monkeypatch.setattr(fair_module.fair_engine, "execute_investigation", fair)
    monkeypatch.setattr(module.identity_enrichment, "enrich_correlations", enrich)
    monkeypatch.setattr(module.correlation_resolver, "resolve_groups", AsyncMock(return_value=[]))
    monkeypatch.setattr(module, "run_fingerprint", lambda: {})
    await module.Orchestrator().run_investigation(inv.id)
    if mode == "fair":
        fair.assert_awaited_once()
        normal.assert_not_awaited()
        enrich.assert_not_awaited()
    else:
        normal.assert_awaited_once()
        fair.assert_not_awaited()
        enrich.assert_awaited_once()
        assert inv.metrics["engine_used"] == "rules"


@pytest.mark.asyncio
async def test_fair_state_api_returns_progress_when_persistence_is_unavailable(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.api.v1.investigations import fair_acquisition_state
    inv_id = uuid4()
    runner = engine(monkeypatch, [Stub("search_dorker", nothing)])
    await runner.collect_findings(str(inv_id), target())
    response = await fair_acquisition_state(inv_id, SimpleNamespace(get=AsyncMock(
        return_value=SimpleNamespace(metrics={"acquisition_mode": "fair"}))))
    assert response["progress"]["phase"] == "complete"
    assert response["snapshot"]["version"] == 1
    assert response["snapshot"]["execution"]["persistence"] == "not_requested"


@pytest.mark.asyncio
async def test_readiness_error_in_one_source_does_not_stop_others(monkeypatch):
    def broken(c):
        raise ValueError("bad provider config")
    runner = engine(monkeypatch, [Stub("ghunt", nothing, ready=broken), Stub("search_dorker", nothing)])
    run = await runner.collect_findings(str(uuid4()), target())
    assert run.sources["ghunt"]["status"] == "failed"
    assert run.sources["search_dorker"]["status"] == "completed"


@pytest.mark.asyncio
async def test_native_input_cap_is_visible_for_remaining_declared_emails(monkeypatch):
    async def check(ctx):
        ctx.extra.setdefault("email_checker_checked", []).append(ctx.email)
        return [ToolFinding(entity_type="email", value=ctx.email)]
    tool = Stub("email_checker", check, ("email",), ready=lambda ctx: len(ctx.extra.get("email_checker_checked", [])) < 2)
    runner = engine(monkeypatch, [tool], [SourcePlan("email_checker", 1, 1, "email")])
    run = await runner.collect_findings(str(uuid4()), target(usernames=[], emails=["one@example.org", "two@example.org", "three@example.org"]))
    assert len(run.findings) == 2
    assert run.sources["email_checker"]["status"] == "partial"
    assert run.sources["email_checker"]["reason"] == "provider_input_budget"


@pytest.mark.asyncio
async def test_stalled_checkpoint_cannot_block_final_snapshot(monkeypatch):
    release = asyncio.Event()
    async def stalled(run):
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
    runner = engine(monkeypatch, [Stub("search_dorker", nothing)], deadline_seconds=.3)
    before = perf_counter()
    run = await runner.collect_findings(str(uuid4()), target(), checkpoint=stalled)
    assert perf_counter() - before < .5
    assert run.cleanup_pending and run.persistence == "partial"
    release.set()
    await asyncio.sleep(.01)


@pytest.mark.asyncio
async def test_http_timeout_inside_silent_native_helper_is_visible(monkeypatch):
    from app.tools import http_client
    async def execute(ctx):
        def respond(request):
            raise httpx.ReadTimeout("sensitive upstream detail", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert await http_client.get(client, "https://example.org/") is None
        return []
    run = await engine(monkeypatch, [Stub("search_dorker", execute)]).collect_findings(str(uuid4()), target())
    assert run.sources["search_dorker"]["status"] == "timeout"
    assert "sensitive upstream detail" not in json.dumps(run.snapshot())


@pytest.mark.asyncio
async def test_deadline_retains_completed_actor_from_multi_actor_apify_job(monkeypatch):
    from app.tools.apify_social import ApifySocialTool
    from app.social.apify_client import ApifyRunResult
    class Client:
        async def run(self, spec, submitted, item_limit, charge_limit, *, on_update):
            if spec.platform == "tiktok":
                await asyncio.sleep(10)
            return ApifyRunResult(actor=spec.actor, status="SUCCEEDED", items=[
                {"username": "first", "url": "https://instagram.com/first", "fullName": "First"}])
    for key, value in {"apify_enabled": True, "apify_token": SecretStr("synthetic-token"),
        "apify_platforms": ["instagram", "tiktok"], "apify_parallelism": 2,
        "apify_max_runs": 2, "apify_max_actors": 2, "apify_max_charge_per_investigation_usd": .1}.items():
        monkeypatch.setattr(settings, key, value)
    runner = engine(monkeypatch, [ApifySocialTool(Client)], deadline_seconds=.3)
    run = await runner.collect_findings(str(uuid4()), target(usernames=[
        {"username": "first", "platform": "instagram"}, {"username": "second", "platform": "tiktok"}]))
    assert len(run.findings) == 1 and run.findings[0].platform == "instagram"
    assert run.sources["apify_social"]["status"] == "partial"
    assert len(run.context.extra["apify_runtime"]["runs"]) == 2
