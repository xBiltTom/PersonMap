"""Search breadth, durable gaps, provider contracts and continuation without pivots."""
import json
import importlib
from types import SimpleNamespace

import httpx
import pytest
import respx
from pydantic import SecretStr, ValidationError

from app.agent.tool_dispatch import build_call_context, build_tool_schemas
from app.core.config import settings
from app.core.runtime import durable_runtime
from app.engine.rule_engine import RuleEngine
from app.models.target import Target
from app.tools.base import TargetContext
from app.tools.search_dorker import SearchBackend, SearchDorkerTool, SearchResults


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    for key, value in dict(search_max_queries=None, tavily_max_queries=20, search_max_queries_per_round=5,
                           search_read_pages=False, tavily_api_key=None, tinyfish_api_key=None,
                           brave_api_key=None).items():
        monkeypatch.setattr(settings, key, value)


def test_plan_covers_source_families_for_name_and_alias():
    tool = SearchDorkerTool()
    for context in [TargetContext(full_name="Ana Maria Perez Lopez"), TargetContext(username="fixture_alias")]:
        report = tool.coverage(context)
        assert {"general", "profiles", "documents", "forums", "publications", "academic", "open_documents"} <= report["scopes"].keys()
        assert report["used"] == 0 and report["pending_queries"] == report["planned_queries"]
        assert any("filetype:pdf" in item["query"] for item in report["next_queries"])


@pytest.mark.asyncio
async def test_rules_continue_pending_sources_even_without_new_pivots(monkeypatch):
    module = importlib.import_module("app.engine.rule_engine")
    tool = SearchDorkerTool()
    calls = []
    async def no_matches(client, dork, seen):
        calls.append((dork.query, tuple(dork.include_domains)))
        return SearchResults(status="no_verified_matches")
    monkeypatch.setattr(tool, "_backends", lambda: [SearchBackend("fixture", lambda: True, httpx.AsyncClient, no_matches)])
    monkeypatch.setattr(module, "tool_registry", SimpleNamespace(get_all=lambda: [tool]))
    monkeypatch.setattr(settings, "search_max_queries_per_round", 2)
    monkeypatch.setattr(settings, "search_max_queries", 8)
    result = await RuleEngine().collect_findings("fixture", Target(full_name="Ana Perez", username="fixture_alias"))
    assert result.rounds == 4 and len(calls) == 8 and len(set(calls)) == 8
    report = tool.coverage(result.context)
    assert report["used"] == 8 and report["budget_limited"] and report["pending_queries"] > 0
    assert sum(scope["without_verified_matches"] for scope in report["scopes"].values()) == 8
    assert not tool.can_run(result.context)
    restored = TargetContext(full_name="Ana Perez", username="fixture_alias", extra=durable_runtime(result.context.extra))
    assert tool.coverage(restored) == report


@pytest.mark.asyncio
async def test_failure_is_an_unavailable_scope_and_zero_budget_never_requests(monkeypatch):
    tool = SearchDorkerTool()
    calls = []
    async def blocked(client, dork, seen):
        calls.append(dork.query)
        return SearchResults(status="http_429")
    monkeypatch.setattr(tool, "_backends", lambda: [SearchBackend("fixture", lambda: True, httpx.AsyncClient, blocked)])
    monkeypatch.setattr(settings, "search_query_concurrency", 1)
    monkeypatch.setattr(settings, "search_max_queries", 0)
    context = TargetContext(username="fixture_alias")
    assert await tool.execute(context) == [] and calls == []
    monkeypatch.setattr(settings, "search_max_queries", 2)
    await tool.execute(context)
    report = tool.coverage(context)
    assert len(calls) == 1
    assert sum(row["unavailable"] for row in report["scopes"].values()) == 2
    assert sum(row["without_verified_matches"] for row in report["scopes"].values()) == 0


@pytest.mark.asyncio
@respx.mock
async def test_brave_uses_extra_snippets_and_rejects_wrong_domains(monkeypatch):
    monkeypatch.setattr(settings, "brave_api_key", SecretStr("fixture-secret"))
    route = respx.get("https://api.search.brave.com/res/v1/web/search").respond(200, json={"web": {"results": [
        {"url": "https://stackoverflow.com/questions/1", "title": "An answer", "description": "Public discussion",
         "extra_snippets": ["Comment from <b>fixture_alias</b>"]},
        {"url": "https://stackoverflow.com.evil.test/questions/1", "title": "fixture_alias", "description": "fixture_alias"},
        {"url": "https://stackoverflow.com/questions/2", "title": "Other", "description": "different_alias"},
    ]}})
    ddg = respx.post("https://html.duckduckgo.com/html/").respond(500)
    context = TargetContext(extra={"search_queries": [{"query": '"fixture_alias"', "rationale": "Public forum mentions", "include_domains": ["stackoverflow.com"]}]})
    findings = await SearchDorkerTool().execute(context)
    assert len(findings) == 1 and findings[0].platform == "stackoverflow"
    assert findings[0].metadata_info["engine"] == "brave" and findings[0].metadata_info["ownership_status"] == "unverified"
    assert route.calls[0].request.url.params["extra_snippets"] == "true"
    assert "site:stackoverflow.com" in route.calls[0].request.url.params["q"]
    assert route.calls[0].request.headers["X-Subscription-Token"] == "fixture-secret"
    assert not ddg.called
    diagnostics = context.extra["search_diagnostics"][0]
    assert diagnostics["rejections"] == {"outside_requested_domains": 1, "literal_evidence_missing": 1}
    assert "fixture-secret" not in json.dumps(durable_runtime(context.extra))


@pytest.mark.asyncio
@respx.mock
async def test_reordered_domains_do_not_repeat_queries_or_miscount_duplicate_matches(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "fixture")
    respx.post("https://api.tavily.com/search").respond(200, json={"results": [{"url": "https://github.com/fixture_alias", "title": "fixture_alias", "content": "fixture_alias"}]})
    tool = SearchDorkerTool()
    query = {"query": '"fixture_alias"', "rationale": "Profile", "include_domains": ["github.com", "gitlab.com"]}
    context = TargetContext(extra={"search_queries": [query]})
    await tool.execute(context)
    context.extra["search_queries"] = [{**query, "include_domains": ["gitlab.com", "github.com"]}]
    assert await tool.execute(context) == [] and context.extra["search_queries_used"] == 1
    context.extra["search_force"] = True
    assert len(await tool.execute(context)) == 1 and context.extra["search_queries_used"] == 2
    assert tool.coverage(context)["scopes"]["general"]["with_matches"] == 1


def test_internal_agent_has_validated_custom_queries_and_ephemeral_inputs():
    schema = next(item["function"]["parameters"] for item in build_tool_schemas() if item["function"]["name"] == "search_dorker")
    assert "queries" in schema["properties"] and {"required": ["queries"]} in schema["anyOf"]
    base = TargetContext(username="fixture_alias", extra={"search_queries_used": 2, "search_queries": [{"query": '"old"'}]})
    target = Target(username="fixture_alias")
    context = build_call_context({"queries": [{"query": '"fixture_alias" tesis', "rationale": "Documents", "include_domains": ["zenodo.org"]}]}, target, base)
    assert context.extra["search_queries_used"] == 2 and context.extra["search_queries"][0]["include_domains"] == ["zenodo.org"]
    assert "search_queries" not in build_call_context({}, target, base).extra
    with pytest.raises(ValidationError):
        build_call_context({"queries": [{"query": "unanchored", "rationale": "Invalid"}]}, target, base)


def test_retired_bing_key_does_not_enable_or_schedule_image_search(monkeypatch):
    from app.tools.reverse_image_search import ReverseImageSearchTool
    monkeypatch.setattr(settings, 'serpapi_key', None)
    monkeypatch.setattr(settings, 'bing_visual_search_key', 'legacy-key')
    assert not settings.reverse_image_enabled
    assert not ReverseImageSearchTool().can_run(TargetContext(extra={'avatar_urls': ['https://example.test/avatar.png']}))


@pytest.mark.asyncio
@respx.mock
async def test_duckduckgo_challenge_is_unavailable_and_not_repeated(monkeypatch):
    monkeypatch.setattr(settings, 'search_query_concurrency', 1)
    route = respx.post('https://html.duckduckgo.com/html/').respond(200, text='<form id="challenge-form">Please verify</form>')
    context = TargetContext(username='fixture_alias')
    tool = SearchDorkerTool()
    assert await tool.execute(context) == []
    assert route.call_count == 1 and context.extra['search_disabled_backends'] == ['duckduckgo']
    assert context.extra['search_diagnostics'][0]['status'] == 'blocked_response'
    assert sum(row['without_verified_matches'] for row in tool.coverage(context)['scopes'].values()) == 0
