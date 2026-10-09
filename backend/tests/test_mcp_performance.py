"""Planning and bounded concurrency regressions without external requests."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
import respx
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.workspace import SearchQuery, ToolInputs
from app.services.workspace import call_fingerprint, merge_runtime
from app.tools.base import TargetContext, ToolFinding
from app.tools.public_page_reader import PublicPageReaderTool
from app.tools.search_dorker import SearchBackend, SearchDorkerTool, SearchResults
from app.tools.username_finder import UsernameFinderTool


@pytest.mark.parametrize("domain", ["localhost", "127.0.0.1", "https://github.com", "github.com/path", "github.com:443", "*.github.com", "user@github.com"])
def test_agent_search_rejects_invalid_domain_filters(domain):
    with pytest.raises(ValidationError):
        SearchQuery(query='"fixture" profile', rationale="Find public references", include_domains=[domain])


@pytest.mark.parametrize("query", ["unanchored query", '"unterminated', '"fixture"\nsecond line', '"fixture" site:github.com'])
def test_agent_search_requires_literal_anchors_and_structured_filters(query):
    with pytest.raises(ValidationError):
        SearchQuery(query=query, rationale="Find public references")


def test_planning_inputs_are_bounded_and_fingerprinted_by_actual_query():
    query = SearchQuery(query='"fixture" thesis', rationale="Find a publication", include_domains=["GITHUB.COM."])
    assert query.include_domains == ["github.com"]
    with pytest.raises(ValidationError):
        ToolInputs(queries=[query] * 6)
    first = TargetContext(username="seed", extra={"search_queries": [query.model_dump()]})
    second = TargetContext(username="different", discovered_usernames=["pivot"], extra={
        "search_queries": [{**query.model_dump(), "rationale": "Revised reasoning"}]})
    assert call_fingerprint("search_dorker", first) == call_fingerprint("search_dorker", second)
    second.extra["search_queries"][0]["query"] = '"other" thesis'
    assert call_fingerprint("search_dorker", first) != call_fingerprint("search_dorker", second)
    first.extra["username_scan_mode"] = "fast"
    second = first.model_copy(deep=True)
    second.extra["username_scan_mode"] = "deep"
    assert call_fingerprint("username_finder", first) != call_fingerprint("username_finder", second)


def test_concurrent_runtime_merge_preserves_counts_coverage_and_other_work():
    baseline = {"candidate_urls": ["a"], "stats": {"checked": 10}, "unchanged": "old"}
    current = {**baseline, "candidate_urls": ["a", "b"], "stats": {"checked": 13},
               "unchanged": "new", "other_tool": True, "username_finder_coverage": {"fixture": 300}}
    incoming = {**baseline, "candidate_urls": ["a", "c"], "stats": {"checked": 12},
                "username_finder_coverage": {"fixture": 200}}
    merged = merge_runtime(current, baseline, incoming)
    assert merged["candidate_urls"] == ["a", "b", "c"]
    assert merged["stats"]["checked"] == 15
    assert merged["username_finder_coverage"]["fixture"] == 300
    assert merged["other_tool"] is True and merged["unchanged"] == "new"
    assert current["stats"]["checked"] == 13
    assert merge_runtime({"observation": {"score": 0.8}}, {}, {"observation": {"score": 0.6}})["observation"]["score"] == 0.6


@pytest.mark.asyncio
async def test_fast_scan_extends_to_deep_without_rechecking_sites(monkeypatch):
    monkeypatch.setattr(settings, "mcp_username_fast_sites", 2)
    tool = UsernameFinderTool()
    sites = [SimpleNamespace(name=f"site-{i}", accepts_username=lambda username: True) for i in range(6)]
    monkeypatch.setattr(tool, "_load_sites", lambda: sites)
    checked = []

    async def check(client, username, site, *args):
        checked.append(site.name)
        return ToolFinding(entity_type="social_account", platform=site.name, value=f"https://example.test/{site.name}/{username}")
    monkeypatch.setattr(tool, "_check_site", check)
    context = TargetContext(username="fixture_person", extra={"username_scan_mode": "fast"})
    fast = await tool.execute(context)
    assert len(fast) == 2 and len(checked) == 2
    assert context.extra["username_finder_coverage"] == {"fixture_person": 2}
    assert await tool.execute(context) == []
    context.extra["username_scan_mode"] = "deep"
    deep = await tool.execute(context)
    assert len(deep) == 4 and len(checked) == len(set(checked)) == 6
    assert context.extra["username_finder_stats"]["checked"] == 6
    assert context.extra["username_finder_coverage"]["fixture_person"] == 6
    assert all(f.metadata_info["scan_mode"] == "deep" for f in deep)
    context.discovered_usernames.append("second_person")
    context.extra["username_scan_mode"] = "fast"
    assert len(await tool.execute(context)) == 2
    assert context.extra["username_finder_coverage"] == {"fixture_person": 6, "second_person": 2}


@pytest.mark.asyncio
async def test_search_queries_overlap_but_preserve_budget(monkeypatch):
    monkeypatch.setattr(settings, "tavily_max_queries", 3)
    monkeypatch.setattr(settings, "search_max_queries_per_round", 5)
    monkeypatch.setattr(settings, "search_query_concurrency", 2)
    monkeypatch.setattr(settings, "search_read_pages", False)
    tool = SearchDorkerTool()
    active, peak = 0, 0
    first_pair = asyncio.Event()

    async def search(client, dork, seen_urls):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            first_pair.set()
        await asyncio.wait_for(first_pair.wait(), 1)
        await asyncio.sleep(0)
        active -= 1
        return SearchResults(matched=1)
    monkeypatch.setattr(tool, "_backends", lambda: [SearchBackend("fixture", lambda: True, httpx.AsyncClient, search)])
    context = TargetContext(extra={"search_queries": [SearchQuery(query=f'"alias{i}"', rationale="Public mention").model_dump() for i in range(5)]})
    await tool.execute(context)
    assert peak == 2
    assert context.extra["search_queries_used"] == context.extra["search_provider_attempts"]["fixture"] == 3
    await tool.execute(context)
    assert context.extra["search_queries_used"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_agent_queries_use_provider_filters_and_keep_literal_validation(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "fixture-key")
    monkeypatch.setattr(settings, "tinyfish_api_key", None)
    monkeypatch.setattr(settings, "search_read_pages", False)
    route = respx.post("https://api.tavily.com/search").respond(200, json={"results": [
        {"title": "fixture thesis", "url": "https://github.com/fixture", "content": "fixture"},
        {"title": "fixture", "url": "https://github.com.evil.test/fixture", "content": "fixture"},
        {"title": "someone else", "url": "https://github.com/other", "content": "Unrelated"},
    ]})
    context = TargetContext(username="seed", extra={"search_queries": [
        SearchQuery(query='"fixture" thesis', rationale="Follow a publication", include_domains=["github.com"]).model_dump()]})
    findings = await SearchDorkerTool().execute(context)
    assert [f.value for f in findings] == ["https://github.com/fixture"]
    assert findings[0].metadata_info["query_origin"] == "agent"
    assert findings[0].metadata_info["ownership_status"] == "unverified"
    assert json.loads(route.calls[0].request.content)["include_domains"] == ["github.com"]


@pytest.mark.asyncio
async def test_forced_search_repeats_evidence_without_resetting_budget(monkeypatch):
    monkeypatch.setattr(settings, "tavily_max_queries", 2)
    monkeypatch.setattr(settings, "search_read_pages", False)
    tool = SearchDorkerTool()
    calls = 0
    async def search(client, dork, seen_urls):
        nonlocal calls
        calls += 1
        finding = tool._validated_finding(dork, "https://example.test/fixture", "fixture", "", "fixture")
        if finding.value in seen_urls:
            return SearchResults(matched=1)
        seen_urls.add(finding.value)
        return SearchResults([finding], matched=1)
    monkeypatch.setattr(tool, "_backends", lambda: [SearchBackend("fixture", lambda: True, httpx.AsyncClient, search)])
    context = TargetContext(extra={"search_queries": [SearchQuery(query='"fixture"', rationale="Verify mention").model_dump()]})
    assert len(await tool.execute(context)) == 1
    context.extra["search_force"] = True
    assert len(await tool.execute(context)) == 1
    assert await tool.execute(context) == []
    assert calls == 2 and context.extra["search_queries_used"] == 2
    assert context.extra["search_last_status"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_parallel_page_reader_retains_successes_when_one_page_fails(monkeypatch):
    import app.tools.public_page_reader as reader
    active, peak = 0, 0
    ready = asyncio.Event()
    async def read(url):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 3:
            ready.set()
        await asyncio.wait_for(ready.wait(), 1)
        active -= 1
        return {"status": "http_404"} if url.endswith("missing") else {"status": "ok", "text": "Public content", "final_url": url}
    monkeypatch.setattr(reader, "read_public_page", read)
    context = TargetContext(extra={"candidate_urls": ["https://example.test/one", "https://example.test/missing", "https://example.test/two"]})
    findings = await PublicPageReaderTool().execute(context)
    assert peak == 3 and len(findings) == 2
    assert context.extra["public_page_reader_errors"][0]["url"].endswith("missing")
