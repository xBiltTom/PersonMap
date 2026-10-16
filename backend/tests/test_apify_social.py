"""No paid runs: synthetic datasets and mocked HTTP over the actual adapter/client."""
import asyncio
from copy import deepcopy
import json
import re
import respx
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.agent.tool_dispatch import build_call_context, build_tool_schemas
from app.core.config import settings
from app.core.runtime import durable_runtime
from app.engine.persistence import dedupe_findings, persist_findings
from app.engine.pivot_frontier import PivotFrontier
from app.engine.pivot_rules import extract_and_apply_pivots
from app.engine.rule_engine import RuleEngine
from app.identity.evidence import target_affinity
from app.models.entity import Entity
from app.models.target import Target
from app.schemas.target import TargetCreate
from app.services.workspace import WorkspaceService, call_fingerprint
from app.social.apify_adapter import ApifyAdapter, actor_input
from app.social.apify_client import ApifyClient, ApifyRunResult
from app.social.capabilities import ACTORS, capabilities, config_id
from app.social.router import SocialSourceRouter
from app.social.safety import public_url
from app.tools import http_client
from app.tools.apify_social import ApifySocialTool, execution_summary
from app.tools.base import BaseTool, TargetContext, ToolFinding
from app.tools.registry import tool_registry

FIXTURES = json.loads((Path(__file__).parent / "fixtures/apify_social.json").read_text())
HANDLES = {"instagram": "fixture.person", "tiktok": "fixture_person", "threads": "fixture_person", "youtube": "fixturechannel"}
URLS = {"instagram": "https://instagram.com/fixture.person", "tiktok": "https://tiktok.com/@fixture_person",
        "threads": "https://threads.net/@fixture_person", "youtube": "https://youtube.com/@fixturechannel"}


@pytest.fixture(autouse=True)
def config(monkeypatch):
    monkeypatch.setattr(settings, "apify_instagram_posts_enabled", False)
    for key, value in {"apify_enabled": True, "apify_token": SecretStr("apify_api_TEST_SECRET"),
        "apify_platforms": list(ACTORS), "apify_actor_builds": {}, "apify_max_runs": 2, "apify_max_actors": 2,
        "apify_max_profiles_per_actor": 3, "apify_max_content_items_per_profile": 10, "apify_max_items_per_actor": 5, "apify_dataset_page_size": 2, "apify_run_timeout": 60,
        "apify_batch_timeout": 150, "apify_request_timeout": 15, "apify_max_retries": 1,
        "apify_parallelism": 1, "apify_max_charge_per_run_usd": .05,
        "apify_max_charge_per_investigation_usd": .1, "apify_max_response_bytes": 2_000_000}.items():
        monkeypatch.setattr(settings, key, value)


def native(platform="instagram", *, url=None, **metadata):
    return ToolFinding(entity_type="social_account", platform=platform, value=url or URLS[platform], metadata_info={
        "source_tool": "social_verifier", "verification_status": "verified", **metadata})


def target(platform="instagram", *, consent=True):
    row = Target(id=uuid4(), **TargetCreate(usernames=[{"username": HANDLES[platform], "platform": platform}]).persistence_values())
    row.extra_data["subject_consent"] = consent
    return row


def context(platform="instagram", *, observed=True, consent=True):
    ctx = TargetContext.from_target(target(platform, consent=consent))
    if observed:
        extract_and_apply_pivots([native(platform)], ctx)
    return ctx


def request(platform="instagram"):
    return SocialSourceRouter().enrichment_requests(context(platform))[0]


def result(platform="instagram", **overrides):
    values = {"actor": ACTORS[platform].actor, "actor_id": "actor123", "run_id": "run123", "dataset_id": "dataset123",
        "build_id": "build123", "build_number": "0.1.2", "status": "SUCCEEDED", "retrieved_at": "2026-10-15T12:00:00+00:00",
        "items": deepcopy(FIXTURES[platform]), "usage": {"usageTotalUsd": .0026, "computeUnits": .001}}
    return ApifyRunResult(**{**values, **overrides})


class FixtureClient:
    async def run(self, spec, submitted, item_limit, charge, *, on_update):
        output = result(spec.platform)
        output.items = output.items[:item_limit]
        on_update(output.summary())
        return output


def mock_http(monkeypatch, handler):
    calls = []
    async def respond(req):
        calls.append(req)
        value = handler(req)
        return await value if hasattr(value, "__await__") else value
    def client(**kwargs):
        assert kwargs["max_retries"] == 0 and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), headers=kwargs["headers"], follow_redirects=False)
    monkeypatch.setattr(http_client, "build_client", client)
    return calls


def run_response(status="SUCCEEDED", **extra):
    return {"data": {"id": "run123", "actId": "actor123", "status": status,
        "defaultDatasetId": "dataset123", "buildId": "build123", "buildNumber": "0.1.2", **extra}}


@pytest.mark.parametrize("platform", list(ACTORS))
def test_declared_platform_routes_immediately_and_keeps_native_discovery(platform):
    ctx = context(platform, observed=False)
    router = SocialSourceRouter()
    assert ApifySocialTool().can_run(ctx)
    assert router.enrichment_requests(ctx)[0].reason == "subject_declared_account_ready"
    extract_and_apply_pivots([native(platform)], ctx)
    selected = router.enrichment_requests(ctx)
    assert len(selected) == 1 and selected[0].actor == ACTORS[platform].actor
    assert selected[0].native_tools == ("username_finder", "social_verifier", "search_dorker")
    assert tool_registry.get_tool("username_finder").can_run(ctx)


@pytest.mark.parametrize("platform", [None, "Unknown Social", "GitHub", "X", "LinkedIn"])
def test_unknown_or_native_platforms_do_not_expand_to_paid_actors(platform):
    row = Target(**TargetCreate(usernames=[{"username": "fixture", "platform": platform}]).persistence_values())
    row.extra_data["subject_consent"] = True
    ctx = TargetContext.from_target(row)
    assert not SocialSourceRouter().enrichment_requests(ctx)
    assert all(item.strategy == "native" for item in SocialSourceRouter().plan(ctx))


@pytest.mark.parametrize("state,reason", [("disabled", "disabled"), ("missing", "token_missing"), ("unavailable", "quota_exhausted")])
def test_optional_provider_unavailable_falls_back_to_native(monkeypatch, state, reason):
    ctx = context()
    if state == "disabled":
        monkeypatch.setattr(settings, "apify_enabled", False)
    elif state == "missing":
        monkeypatch.setattr(settings, "apify_token", None)
    else:
        ctx.extra["apify_runtime"] = {"unavailable": reason}
    assert not ApifySocialTool().can_run(ctx)
    assert any(item.reason == reason and item.strategy == "native" for item in SocialSourceRouter().plan(ctx))


def test_namespace_prioritizes_but_does_not_disable_other_supported_profiles():
    ctx = context("tiktok")
    extract_and_apply_pivots([native("instagram")], ctx)
    selected = SocialSourceRouter().enrichment_requests(ctx)
    assert [item.platform for item in selected] == ["tiktok", "instagram"]


def test_unlabelled_username_can_enrich_only_after_native_discovery():
    ctx = TargetContext(username=HANDLES["instagram"], extra={"subject_consent": True})
    assert not SocialSourceRouter().enrichment_requests(ctx)
    extract_and_apply_pivots([native()], ctx)
    assert len(SocialSourceRouter().enrichment_requests(ctx)) == 1


@pytest.mark.parametrize("literal,expected", [(True, True), (False, False), (None, False)])
def test_native_literal_search_profile_is_plausible_without_claiming_existence(literal, expected):
    ctx = context(observed=False)
    ctx.declared_seeds = []
    finding = ToolFinding(entity_type="search_mention", value=URLS["instagram"],
        metadata_info={"source_tool": "search_dorker", "literal_match": literal, "ownership_status": "unverified"})
    extract_and_apply_pivots([finding], ctx)
    assert bool(ApifySocialTool().can_run(ctx)) is expected
    if expected:
        assert ctx.extra["social_native_profiles"][0]["evidence_role"] == "native_search_profile_candidate_not_ownership"


def test_frontier_admission_cannot_be_bypassed_by_saved_profile_archive():
    ctx = context()
    ctx.declared_seeds = []
    ctx.extra["candidate_urls"] = []
    assert not ApifySocialTool().can_run(ctx)
    assert any(item.reason == "awaiting_frontier_admission" for item in SocialSourceRouter().plan(ctx))


@pytest.mark.parametrize("kind", ["search", "candidate", "actor", "uncontrolled", "controlled"])
def test_only_explicit_native_existence_observations_unlock_enrichment(kind):
    ctx = context(observed=False)
    ctx.declared_seeds = []
    ctx.declared_seeds = []
    finding = native(verification_status="candidate")
    if kind == "search":
        finding.entity_type = "search_mention"
    if kind == "actor":
        finding.metadata_info.update(provider="apify", verification_status="verified")
    if kind in {"uncontrolled", "controlled"}:
        finding.metadata_info.update(source_tool="username_finder", catalog_source="maigret", maigret_status="Claimed",
            negative_control="passed" if kind == "controlled" else "untested")
    extract_and_apply_pivots([finding], ctx)
    assert bool(ApifySocialTool().can_run(ctx)) == (kind == "controlled")


def test_consent_is_separate_from_infostealer_flag_and_agent_arguments():
    row = target(consent=False)
    row.extra_data["self_consent"] = True
    ctx = TargetContext.from_target(row)
    extract_and_apply_pivots([native()], ctx)
    assert not ApifySocialTool().can_run(ctx)
    ctx.extra["subject_consent"] = True
    assert build_call_context({"subject_consent": True}, row, ctx).extra["subject_consent"] is False


@pytest.mark.parametrize("platform,content_count", [("instagram", 1), ("tiktok", 2), ("threads", 1), ("youtube", 2)])
def test_actor_shapes_normalize_to_common_account_content_and_provenance(platform, content_count):
    spec, query = ACTORS[platform], request(platform)
    submitted = actor_input(spec, query, 5)
    findings = ApifyAdapter().normalize(spec, query, result(platform), submitted)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.entity_type == "social_account" and finding.value == URLS[platform]
    meta = finding.metadata_info
    assert meta["ownership_status"] == "subject_declared" and meta["provenance"]["origin"] == "automatic"
    assert meta["provenance"]["status"] == "discovered" and meta["provenance"]["needs_review"]
    assert len(meta["public_content"]) == content_count
    source = meta["collection_sources"][0]
    assert source["actor"] == spec.actor and source["run_id"] == "run123" and source["dataset_id"] == "dataset123"
    assert source["build_id"] == "build123" and source["build_number"] == "0.1.2"
    assert source["source_url"] == URLS[platform] and source["retrieved_at"]
    assert source["input"] == submitted and source["query"]["platform"] == platform


def test_public_content_and_suggestions_do_not_manufacture_target_identifiers():
    query = request()
    finding = ApifyAdapter().normalize(ACTORS["instagram"], query, result(), actor_input(ACTORS["instagram"], query, 1))[0]
    ctx = context()
    extract_and_apply_pivots([finding], ctx)
    assert ctx.discovered_emails == ["public@example.org"]  # Explicit public mailto, not bio/caption regex.
    assert "fixture-alias" not in ctx.all_usernames()  # URL enters verification, not an identity assertion.
    assert "https://github.com/fixture-alias" in ctx.extra["candidate_urls"]
    assert "https://example.org/public" in ctx.extra["personal_domain_urls"]
    assert not {"stray@example.org", "comment_author", "other_person", "unrelated_suggestion"} & set(ctx.all_emails() + ctx.all_usernames())
    previous = deepcopy((ctx.discovered_emails, ctx.extra["candidate_urls"], ctx.extra["personal_domain_urls"]))
    extract_and_apply_pivots([finding, finding], ctx)
    assert previous == (ctx.discovered_emails, ctx.extra["candidate_urls"], ctx.extra["personal_domain_urls"])


@pytest.mark.parametrize("platform", list(ACTORS))
def test_private_or_mismatched_actor_output_is_not_retained(platform):
    spec, query = ACTORS[platform], request(platform)
    output = result(platform)
    if platform == "tiktok":
        for row in output.items:
            row["authorMeta"]["privateAccount"] = True
    elif platform == "youtube":
        for row in output.items:
            row["isAgeRestricted"] = True
    else:
        output.items[0]["private" if platform == "instagram" else "is_private"] = True
    assert ApifyAdapter().normalize(spec, query, output, {}) == []
    output = result(platform)
    if platform == "tiktok":
        for row in output.items:
            row["authorMeta"].update(name="different", profileUrl="https://tiktok.com/@different")
    elif platform == "youtube":
        for row in output.items:
            (row.get("aboutChannelInfo") or row)["channelUsername"] = "@different"
    else:
        output.items[0].update(username="different", url="https://instagram.com/different" if platform == "instagram" else "https://threads.net/@different")
    assert ApifyAdapter().normalize(spec, query, output, {}) == []


def test_normalization_does_not_promote_alias_only_matches_to_identity():
    output = result()
    output.items[0]["externalUrls"] = []
    finding = ApifyAdapter().normalize(ACTORS["instagram"], request(), output, {})[0]
    entity = Entity(entity_type=finding.entity_type, platform=finding.platform, value=finding.value,
        metadata_info=finding.metadata_info, source_tool="apify_social")
    affinity = target_affinity(entity, target())
    assert affinity["weight"] == 0 and affinity["ownership_status"] == "unverified"


@pytest.mark.parametrize("row", [{"url": URLS["instagram"]},
    {"url": URLS["instagram"], "username": HANDLES["instagram"]},
    {"inputUrl": URLS["instagram"], "errorDescription": "Only a query echo"}])
def test_query_echo_or_url_only_is_not_manufactured_into_an_observed_account(row):
    assert ApifyAdapter().normalize(ACTORS["instagram"], request(), result(items=[row]), {}) == []


@pytest.mark.asyncio
async def test_deduplication_preserves_native_and_actor_provenance_without_second_evidence_store():
    query = request()
    finding = ApifyAdapter().normalize(ACTORS["instagram"], query, result(), {})[0]
    initial = native()
    initial.confidence = .9
    merged = dedupe_findings([initial, finding, finding])
    assert len(merged) == 1 and len(merged[0].metadata_info["collection_sources"]) == 1
    assert len(merged[0].metadata_info["public_content"]) == 1
    db = SimpleNamespace(add=lambda row: None, flush=AsyncMock())
    saved = await persist_findings(str(uuid4()), merged, target(), db)
    assert saved[0].metadata_info["provenance"]["status"] == "discovered"
    assert saved[0].metadata_info["provenance"]["origin"] == "automatic"
    assert set(saved[0].metadata_info["source_tools"]) == {"social_verifier", "apify_social"}


@pytest.mark.parametrize("value", ["https://example.org/a?token=secret", "https://example.org/a?X-Amz-Signature=secret",
    "https://example.org/a?sig=secret", "https://example.org/a?expires=99", "http://localhost/private", "https://user:secret@example.org/a"])
def test_signed_private_or_credential_urls_are_not_retained(value):
    assert public_url(value) is None


def test_tracking_is_removed_without_discarding_a_public_link_or_video_id():
    assert public_url("https://example.org/public?utm_source=instagram&fbclid=tracking") == "https://example.org/public"
    assert public_url("https://youtube.com/watch?v=abcdefghijk&utm_source=profile") == "https://youtube.com/watch?v=abcdefghijk"


def test_allowlist_and_redaction_never_persist_raw_tokens_headers_or_signed_links():
    output = result()
    row = output.items[0]
    row.update(Authorization="Bearer BAD", token="BAD", profilePicUrl="https://example.org/a?signature=BAD",
        biography="Bearer abc123 apify_api_TEST_SECRET https://example.org/a?secret=BAD")
    row["externalUrls"].append({"url": "https://example.org/a?token=BAD"})
    finding = ApifyAdapter().normalize(ACTORS["instagram"], request(), output, {})[0]
    serialized = finding.model_dump_json()
    assert "BAD" not in serialized and "apify_api_TEST_SECRET" not in serialized and "abc123" not in serialized
    assert "avatar_url" not in finding.metadata_info and "Authorization" not in serialized


@pytest.mark.asyncio
async def test_run_item_actor_and_charge_reservations_survive_reload_and_prevent_cycles(monkeypatch):
    monkeypatch.setattr(settings, "apify_max_runs", 1)
    ctx = context()
    extract_and_apply_pivots([native("tiktok")], ctx)
    tool = ApifySocialTool(FixtureClient)
    fingerprint = tool.input_fingerprint(ctx)
    assert len(await tool.execute(ctx)) == 1
    assert tool.input_fingerprint(ctx) == fingerprint
    assert execution_summary(ctx)["runs_reserved"] == 1
    assert any(row["status"] == "run_budget_exhausted" for row in execution_summary(ctx)["diagnostics"])
    restored = TargetContext.model_validate_json(ctx.model_dump_json())
    restored.extra = durable_runtime(restored.extra) | {"candidate_urls": ctx.extra["candidate_urls"], "subject_consent": True}
    assert not tool.can_run(restored)
    assert await tool.execute(restored) == []
    assert execution_summary(restored)["runs_reserved"] == 1


@pytest.mark.asyncio
async def test_paid_runtime_reload_is_independent_of_frontier_feature_flag(monkeypatch):
    ctx = context()
    await ApifySocialTool(FixtureClient).execute(ctx)
    inv = SimpleNamespace(id=uuid4(), target=target(), metrics={"collection_runtime": durable_runtime(ctx.extra)})
    monkeypatch.setattr(settings, "pivot_frontier_enabled", False)
    restored = WorkspaceService()._context(inv, [])
    assert execution_summary(restored)["runs_reserved"] == 1
    assert restored.extra["social_native_profiles"] == ctx.extra["social_native_profiles"]


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,limit,reason", [("apify_max_actors", 1, "actor_budget_exhausted"),
    ("apify_max_charge_per_investigation_usd", .05, "charge_budget_exhausted")])
async def test_distinct_actor_and_reserved_cost_limits(monkeypatch, budget, limit, reason):
    monkeypatch.setattr(settings, budget, limit)
    ctx = context()
    extract_and_apply_pivots([native("tiktok")], ctx)
    await ApifySocialTool(FixtureClient).execute(ctx)
    assert execution_summary(ctx)["runs_reserved"] == 1
    assert any(row["status"] == reason for row in execution_summary(ctx)["diagnostics"])


@pytest.mark.asyncio
async def test_items_are_allocated_per_actor_across_profiles(monkeypatch):
    monkeypatch.setattr(settings, "apify_max_runs", 10)
    monkeypatch.setattr(settings, "apify_max_profiles_per_actor", 2)
    monkeypatch.setattr(settings, "apify_max_charge_per_investigation_usd", 1)
    ctx = context()
    extract_and_apply_pivots([native(url="https://instagram.com/another"), native(url="https://instagram.com/third")], ctx)
    await ApifySocialTool(FixtureClient).execute(ctx)
    assert execution_summary(ctx)["runs_reserved"] == 1
    assert any(row["status"] == "profile_budget_exhausted" for row in execution_summary(ctx)["diagnostics"])


@pytest.mark.asyncio
async def test_parallelism_limit_is_shared_and_failures_do_not_drop_other_accounts(monkeypatch):
    monkeypatch.setattr(settings, "apify_parallelism", 2)
    monkeypatch.setattr(settings, "apify_max_runs", 4)
    monkeypatch.setattr(settings, "apify_max_actors", 4)
    monkeypatch.setattr(settings, "apify_max_charge_per_investigation_usd", .2)
    active, peak = 0, 0
    class ConcurrentClient(FixtureClient):
        async def run(self, spec, *args, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(.01)
                if spec.platform == "tiktok":
                    raise ValueError("malformed output with secrets that must not be logged")
                return await super().run(spec, *args, **kwargs)
            finally:
                active -= 1
    ctx = context()
    extract_and_apply_pivots([native(platform) for platform in ACTORS], ctx)
    findings = await ApifySocialTool(ConcurrentClient).execute(ctx)
    assert peak == 2 and active == 0
    assert len(findings) == 3
    assert "adapter_error" in execution_summary(ctx)["outcomes"]


@pytest.mark.asyncio
async def test_http_client_polls_pages_caps_and_never_puts_token_in_url(monkeypatch):
    def handler(req):
        assert req.headers["Authorization"] == "Bearer apify_api_TEST_SECRET"
        assert "apify_api" not in str(req.url) and "token" not in req.url.params
        if req.method == "POST":
            assert req.url.path == "/v2/actors/clockworks~tiktok-profile-scraper/runs"
            assert req.url.params["maxItems"] == "3" and req.url.params["maxTotalChargeUsd"] == "0.05"
            body = json.loads(req.content)
            assert body["commentsPerPost"] == body["maxFollowersPerProfile"] == body["maxFollowingPerProfile"] == 0
            return httpx.Response(201, json=run_response("RUNNING"))
        if "/actor-runs/" in req.url.path:
            return httpx.Response(200, json=run_response(usageTotalUsd=.01, stats={"computeUnits": .001}))
        assert int(req.url.params["limit"]) <= 2
        offset, limit = int(req.url.params["offset"]), int(req.url.params["limit"])
        return httpx.Response(200, json=[{"index": i} for i in range(offset, offset + limit)])
    calls = mock_http(monkeypatch, handler)
    spec, query = ACTORS["tiktok"], request("tiktok")
    output = await ApifyClient().run(spec, actor_input(spec, query, 3), 3, .05)
    assert len(output.items) == 3 and output.run_id == "run123" and output.dataset_id == "dataset123"
    assert output.usage == {"usageTotalUsd": .01, "computeUnits": .001}
    assert len([req for req in calls if req.method == "POST"]) == 1
    assert [req.url.params["offset"] for req in calls if "/items" in req.url.path] == ["0", "2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reason", [(401, "authentication_failed"), (402, "quota_exhausted"),
    (429, "rate_limited"), (500, "upstream_error")])
async def test_failed_starts_are_not_retried_and_fall_back_without_absence_claims(monkeypatch, status, reason):
    calls = mock_http(monkeypatch, lambda req: httpx.Response(status, json={"error": "apify_api_TEST_SECRET"}))
    ctx = context()
    tool = ApifySocialTool()
    assert await tool.execute(ctx) == []
    assert len(calls) == 1  # Paid POST has no retry, including HTTP 5xx.
    record = next(iter(ctx.extra["apify_runtime"]["runs"].values()))
    assert record["error"] == reason and "not_found" not in json.dumps(record)
    assert await tool.execute(ctx) == []
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_get_retries_are_bounded_and_preserve_known_run(monkeypatch):
    reads = 0
    def handler(req):
        nonlocal reads
        if req.method == "POST":
            return httpx.Response(201, json=run_response())
        reads += 1
        return httpx.Response(500, json={}) if reads == 1 else httpx.Response(200, json=FIXTURES["instagram"])
    calls = mock_http(monkeypatch, handler)
    query = request()
    output = await ApifyClient().run(ACTORS["instagram"], actor_input(ACTORS["instagram"], query, 1), 1, .05)
    assert reads == 2 and len(output.items) == 1
    assert len([req for req in calls if req.method == "POST"]) == 1


@pytest.mark.asyncio
async def test_ambiguous_start_network_failure_is_reserved_and_never_resubmitted(monkeypatch):
    def handler(req):
        raise httpx.ReadTimeout("do not persist apify_api_TEST_SECRET", request=req)
    calls = mock_http(monkeypatch, handler)
    ctx = context()
    tool = ApifySocialTool()
    assert await tool.execute(ctx) == []
    assert await tool.execute(ctx) == []
    assert len(calls) == 1
    record = next(iter(ctx.extra["apify_runtime"]["runs"].values()))
    assert record["status"] == "start_uncertain" and record["reserved_charge_usd"] == .05
    assert "apify_api" not in json.dumps(durable_runtime(ctx.extra))


@pytest.mark.asyncio
async def test_timeout_aborts_known_remote_run_and_returns_no_false_absence(monkeypatch):
    monkeypatch.setattr(settings, "apify_run_timeout", .02)
    async def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json=run_response("ABORTED" if req.url.path.endswith("abort") else "RUNNING"))
        await asyncio.sleep(10)
        return httpx.Response(200, json=run_response("RUNNING"))
    calls = mock_http(monkeypatch, handler)
    query = request()
    output = await ApifyClient().run(ACTORS["instagram"], actor_input(ACTORS["instagram"], query, 1), 1, .05)
    assert output.error == "timeout" and output.status == "abort_requested"
    assert any(req.url.path.endswith("/run123/abort") for req in calls)


@pytest.mark.asyncio
async def test_cancellation_requests_abort_without_swallowing_cancellation(monkeypatch):
    entered = asyncio.Event()
    async def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json=run_response("ABORTED" if req.url.path.endswith("abort") else "RUNNING"))
        entered.set()
        await asyncio.sleep(10)
        return httpx.Response(200, json=run_response("RUNNING"))
    calls = mock_http(monkeypatch, handler)
    updates = []
    task = asyncio.create_task(ApifyClient().run(ACTORS["instagram"], {}, 1, .05, on_update=updates.append))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(req.url.path.endswith("/abort") for req in calls)
    assert updates[-1]["error"] == "cancelled" and updates[-1]["status"] == "abort_requested"


@pytest.mark.asyncio
async def test_batch_timeout_retains_jobs_already_completed(monkeypatch):
    monkeypatch.setattr(settings, "apify_batch_timeout", .02)
    class SlowClient(FixtureClient):
        async def run(self, spec, *args, **kwargs):
            if spec.platform == "tiktok":
                await asyncio.sleep(1)
            return await super().run(spec, *args, **kwargs)
    ctx = context()
    extract_and_apply_pivots([native("tiktok")], ctx)
    findings = await ApifySocialTool(SlowClient).execute(ctx)
    assert len(findings) == 1 and findings[0].platform == "instagram"
    assert any(row["status"] == "batch_timeout" for row in execution_summary(ctx)["diagnostics"])
    assert "batch_timeout_or_cancelled" in execution_summary(ctx)["outcomes"]


@pytest.mark.asyncio
@pytest.mark.parametrize("disabled", ["flag", "token", "consent"])
async def test_direct_execution_is_fail_closed_even_with_a_plausible_profile(monkeypatch, disabled):
    ctx = context()
    if disabled == "flag":
        monkeypatch.setattr(settings, "apify_enabled", False)
    elif disabled == "token":
        monkeypatch.setattr(settings, "apify_token", None)
    else:
        ctx.extra["subject_consent"] = False
    calls = []
    def forbidden_client():
        calls.append(True)
        raise AssertionError("No HTTP client may be created")
    assert await ApifySocialTool(forbidden_client).execute(ctx) == []
    assert calls == []


@pytest.mark.asyncio
async def test_capability_endpoint_is_read_only_and_json_serializable():
    from fastapi import FastAPI
    from app.api.v1.social_sources import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/sources/social")
    assert response.status_code == 200 and response.json() == capabilities()
    assert "apify_api_TEST_SECRET" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], {"changed": "shape"}, [None, "unexpected", {"error": "not available"}]])
async def test_empty_or_changed_datasets_are_partial_source_failures(monkeypatch, rows):
    calls = mock_http(monkeypatch, lambda req: httpx.Response(201, json=run_response()) if req.method == "POST"
                      else httpx.Response(200, json=rows))
    ctx = context()
    assert await ApifySocialTool().execute(ctx) == []
    assert "not_found" not in json.dumps(ctx.extra["apify_runtime"])
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_partial_failed_run_keeps_usable_public_rows(monkeypatch):
    mock_http(monkeypatch, lambda req: httpx.Response(201, json=run_response("FAILED")) if req.method == "POST"
              else httpx.Response(200, json=FIXTURES["instagram"]))
    ctx = context()
    findings = await ApifySocialTool().execute(ctx)
    assert len(findings) == 1 and execution_summary(ctx)["outcomes"] == ["partial"]


@pytest.mark.asyncio
async def test_streamed_response_size_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "apify_max_response_bytes", 1024)
    mock_http(monkeypatch, lambda req: httpx.Response(201, json=run_response()) if req.method == "POST"
              else httpx.Response(200, content=b"[" + b" " * 2000 + b"]"))
    query = request()
    output = await ApifyClient().run(ACTORS["instagram"], {}, 1, .05)
    assert output.error == "response_too_large" and output.items == []


def test_capability_matrix_config_and_run_keys_are_inspectable_without_secrets(monkeypatch):
    serialized = json.dumps(capabilities())
    assert "apify_api_TEST_SECRET" not in serialized and "Authorization" not in serialized
    assert json.loads(serialized) == capabilities()  # JSONB/review baselines must round-trip exactly.
    assert len([row for row in capabilities()["matrix"] if row["provider"] == "apify" and row["enabled"]]) == 4
    assert len([row for row in capabilities()["matrix"] if row["provider"] == "apify"]) == 8
    before = config_id()
    monkeypatch.setattr(settings, "apify_token", SecretStr("DIFFERENT_SECRET"))
    assert config_id() == before
    tool, ctx = ApifySocialTool(), context()
    assert RuleEngine()._get_tool_run_key(tool, ctx).endswith(tool.input_fingerprint(ctx))
    assert call_fingerprint("apify_social", ctx) == tool.input_fingerprint(ctx)
    assert any(schema["function"]["name"] == "apify_social" for schema in build_tool_schemas())


@pytest.mark.asyncio
async def test_rules_use_same_native_pivot_tool_and_common_findings_pipeline(monkeypatch):
    ctx = context(observed=False)
    class NativeFixture(BaseTool):
        name = "social_verifier"
        description = "Controlled public existence check"
        required_inputs = ["username"]
        async def execute(self, context):
            return [native()]
    tool = ApifySocialTool(FixtureClient)
    monkeypatch.setattr(tool_registry, "get_all", lambda: [NativeFixture(), tool])
    sweep = await RuleEngine().collect_findings(str(uuid4()), target(), initial_context=ctx)
    assert {finding.metadata_info["source_tool"] for finding in sweep.findings} == {"social_verifier", "apify_social"}
    assert execution_summary(sweep.context)["runs_reserved"] == 1
    assert "public@example.org" in sweep.context.discovered_emails
    assert any(item.type == "email" and item.value == "public@example.org" for item in PivotFrontier(sweep.context).rank())


@pytest.mark.asyncio
async def test_three_declared_accounts_share_one_batch_and_keep_individual_provenance():
    row = Target(**TargetCreate(usernames=[{"username": name, "platform": "instagram"}
        for name in [HANDLES["instagram"], "second", "third"]]).persistence_values())
    row.extra_data["subject_consent"] = True
    ctx = TargetContext.from_target(row)
    calls = []
    class BatchClient:
        async def run(self, spec, submitted, item_limit, charge, *, on_update):
            calls.append(submitted)
            rows = []
            for username in submitted["usernames"]:
                entry = deepcopy(FIXTURES["instagram"][0])
                entry.update(username=username, url=f"https://instagram.com/{username}")
                if username == "second":
                    entry = {"error": "unavailable", "username": username}
                rows.append(entry)
            return result(items=rows)
    findings = await ApifySocialTool(BatchClient).execute(ctx)
    assert len(calls) == 1 and len(calls[0]["usernames"]) == 3
    assert len(findings) == 2
    summary = execution_summary(ctx)
    assert summary["runs_reserved"] == 1 and summary["reserved_charge_usd"] == .05
    assert summary["outcomes"] == ["partial"]
    for finding in findings:
        meta = finding.metadata_info
        assert meta["ownership"]["status"] == "subject_declared"
        assert meta["ownership"]["seed_id"] and not meta["ownership"]["needs_review"]
        assert not meta["ownership_review_required"]
        assert meta["provenance"]["origin"] == "automatic"
        assert meta["collection_sources"][0]["query"]["profile_url"] == finding.value
        for content in meta["public_content"]:
            assert content["origin"] == "automatic"
            assert content["collection_source"]["query"]["profile_url"] == finding.value
    restored = TargetContext.model_validate_json(ctx.model_dump_json())
    assert not ApifySocialTool().can_run(restored)


@pytest.mark.asyncio
async def test_persistence_recomputes_ownership_from_seed_without_confirming_other_profiles():
    query = request()
    declared = ApifyAdapter().normalize(ACTORS["instagram"], query, result(), {})[0]
    other = native(url="https://instagram.com/someone_else")
    other.metadata_info["ownership"] = {"status": "subject_declared", "needs_review": False}
    db = SimpleNamespace(add=lambda row: None, flush=AsyncMock())
    saved = await persist_findings(str(uuid4()), [declared, other], target(), db)
    meta = saved[0].metadata_info
    assert meta["ownership_status"] == "subject_declared" and not meta["ownership_review_required"]
    assert meta["provenance"]["origin"] == "automatic"
    assert saved[1].metadata_info["ownership_status"] == "unverified"
    assert saved[1].metadata_info["ownership_review_required"]


@pytest.mark.parametrize("platform", list(ACTORS))
def test_batch_builders_and_per_profile_content_limit(monkeypatch, platform):
    from dataclasses import replace
    query = request(platform)
    queries = [query, replace(query, username="another", url="https://youtube.com/@another")]
    submitted = actor_input(ACTORS[platform], queries, 1)
    field = {"instagram": "usernames", "threads": "usernames", "tiktok": "profiles", "youtube": "startUrls"}[platform]
    assert len(submitted[field]) == 2
    monkeypatch.setattr(settings, "apify_max_content_items_per_profile", 1)
    normalized = ApifyAdapter().normalize(ACTORS[platform], query, result(platform), submitted)
    assert len(normalized[0].metadata_info["public_content"]) <= 1


@pytest.mark.asyncio
async def test_legacy_reservations_count_toward_new_profile_budget(monkeypatch):
    ctx = context()
    ctx.extra["apify_runtime"] = {"runs": {"old": {
        "actor": ACTORS["instagram"].actor, "status": "start_uncertain", "item_allowance": 1,
        "reserved_charge_usd": .05, "profile_keys": ["instagram:username:previous"]}}}
    monkeypatch.setattr(settings, "apify_max_profiles_per_actor", 1)
    tool = ApifySocialTool(FixtureClient)
    assert not tool.can_run(ctx)
    assert await tool.execute(ctx) == []
    assert execution_summary(ctx)["runs_reserved"] == 1
    assert execution_summary(ctx)["reserved_charge_usd"] == .05
    assert execution_summary(ctx)["diagnostics"][-1]["status"] == "profile_budget_exhausted"


@pytest.mark.asyncio
async def test_instagram_profile_without_nested_posts_gets_explicit_public_posts(monkeypatch):
    from app.social.capabilities import INSTAGRAM_POSTS
    monkeypatch.setattr(settings, 'apify_instagram_posts_enabled', True)
    calls = []
    class Client:
        async def run(self, spec, submitted, item_limit, charge_limit, on_update):
            calls.append((spec.actor, submitted))
            if spec.actor == INSTAGRAM_POSTS.actor:
                assert submitted['resultsLimit'] == 10 and submitted['resultsType'] == 'posts'
                rows = [{'id': 'post-1', 'ownerUsername': HANDLES['instagram'], 'ownerId': '12345',
                    'caption': 'Estudio en Universidad Ejemplo.', 'url': 'https://www.instagram.com/p/SAFE123/',
                    'timestamp': '2026-10-16T08:10:00Z', 'likesCount': 12}]
            else:
                rows = [{'id': '12345', 'username': HANDLES['instagram'], 'fullName': 'Fixture'}]
            return result(items=rows, actor=spec.actor)
    ctx = context(observed=False)
    findings = await ApifySocialTool(client_factory=Client).execute(ctx)
    posts = [post for f in findings for post in f.metadata_info.get('public_content', [])]
    assert len(calls) == 2 and len(posts) == 1 and posts[0]['likes'] == 12
    assert not ApifySocialTool().pending(ctx)


def test_instagram_post_row_requires_explicit_matching_author():
    from app.social.capabilities import INSTAGRAM_POSTS
    wrong = {'id': 'post-1', 'ownerUsername': 'different_person', 'ownerId': '12345',
             'caption': 'Do not attribute', 'url': 'https://www.instagram.com/p/SAFE123/'}
    assert ApifyAdapter().normalize(INSTAGRAM_POSTS, request(), result(items=[wrong]), {}) == []
    wrong.pop('ownerUsername')
    assert ApifyAdapter().normalize(INSTAGRAM_POSTS, request(), result(items=[wrong]), {}) == []


def test_profile_build_pin_is_not_reused_for_a_different_content_actor(monkeypatch):
    from app.social.capabilities import actor_build, INSTAGRAM_POSTS
    monkeypatch.setattr(settings, 'apify_actor_builds', {'instagram': '0.0.643'})
    assert actor_build(ACTORS['instagram']) == '0.0.643'
    assert actor_build(INSTAGRAM_POSTS) == 'latest'
    monkeypatch.setattr(settings, 'apify_actor_builds', {INSTAGRAM_POSTS.actor: '1.2.3'})
    assert actor_build(INSTAGRAM_POSTS) == '1.2.3'


def test_instagram_collaboration_is_attributed_only_with_explicit_coauthor():
    from app.social.capabilities import INSTAGRAM_POSTS
    row = {'id': 'post-collab', 'ownerUsername': 'other_author', 'ownerId': '987',
           'caption': 'Estudio en Universidad Ejemplo.', 'url': 'https://www.instagram.com/p/COLLAB123/',
           'coauthorProducers': [{'id': '123', 'username': HANDLES['instagram'], 'full_name': 'Fixture'}]}
    findings = ApifyAdapter().normalize(INSTAGRAM_POSTS, request(), result(items=[row]), {})
    assert len(findings) == 1
    content = findings[0].metadata_info['public_content']
    assert len(content) == 1 and content[0]['authorship_role'] == 'coauthor'
    assert 'other_author' not in json.dumps(content)
    row['coauthorProducers'] = []
    row['mentions'] = [HANDLES['instagram']]
    assert not ApifyAdapter().normalize(INSTAGRAM_POSTS, request(), result(items=[row]), {})


@pytest.mark.asyncio
@respx.mock
async def test_missing_actor_build_is_not_reported_as_account_denial():
    respx.post(re.compile(r'https://api\.apify\.com/v2/actors/.*/runs.*')).respond(
        403, json={'error': {'type': 'build-not-found', 'message': 'Do not log this body'}})
    returned = await ApifyClient().run(ACTORS['instagram'], {'usernames':['fixture.person']}, 1, .025)
    assert returned.error == 'actor_build_not_found'
    assert returned.status == 'rejected_before_start' and returned.run_id is None
