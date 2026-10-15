"""Authorship is an observed ID relationship, not target ownership."""
import json

import pytest
import respx
from pydantic import SecretStr

from app.core.config import settings
from app.core.runtime import durable_runtime
from app.tools.academic_finder import AcademicFinderTool
from app.tools.base import TargetContext


@pytest.mark.asyncio
@respx.mock
async def test_works_use_candidate_ids_and_verify_returned_authorships(monkeypatch):
    respx.get("https://api.crossref.org/works").respond(200, json={"status": "ok", "message": {"items": []}})
    monkeypatch.setattr(settings, "openalex_api_key", SecretStr("fixture-key"))
    authors = respx.get("https://api.openalex.org/authors").respond(200, json={"results": [
        {"id": "https://openalex.org/A1", "display_name": "Ana Perez", "orcid": "https://orcid.org/0000-0001-0002-0003"},
        {"id": "https://openalex.org/A2", "display_name": "Ana Perez Lopez"},
        {"id": "https://openalex.org/A3", "display_name": "Ana Perez"},
    ]})
    works = respx.get("https://api.openalex.org/works").respond(200, json={"results": [
        {"id": "https://openalex.org/W1", "title": "Open study", "authorships": [{"author": {"id": "https://openalex.org/A1"}}],
         "primary_location": None, "best_oa_location": {"is_oa": True, "pdf_url": "https://repo.example.test/study.pdf", "landing_page_url": "https://repo.example.test/study"}},
        {"id": "https://openalex.org/W2", "title": "Wrong author", "authorships": [{"author": {"id": "https://openalex.org/A2"}}]},
        {"id": "https://openalex.org/W3", "title": "No authorship", "authorships": []},
    ]})
    tool = AcademicFinderTool()
    context = TargetContext(full_name="Ana Perez")
    findings = await tool.execute(context)
    assert {finding.value for finding in findings} == {"https://openalex.org/A1", "https://openalex.org/A3", "https://openalex.org/W1"}
    assert works.calls[0].request.url.params["filter"] == "author.id:A1|A3"
    assert authors.calls[0].request.url.params["api_key"] == "fixture-key"
    paper = findings[-1]
    assert paper.metadata_info["open_access_urls"] == ["https://repo.example.test/study.pdf"]
    assert paper.metadata_info["matched_author_ids"] == ["https://openalex.org/A1"]
    assert all(f.metadata_info["ownership_status"] == "unverified" for f in findings)
    assert not tool.can_run(context) and await tool.execute(context) == []
    assert "fixture-key" not in json.dumps(durable_runtime(context.extra))


@pytest.mark.asyncio
@respx.mock
async def test_blocked_author_source_never_looks_like_empty_success(monkeypatch):
    respx.get("https://api.crossref.org/works").respond(200, json={"status": "ok", "message": {"items": []}})
    monkeypatch.setattr(settings, "openalex_api_key", None)
    respx.get("https://api.openalex.org/authors").respond(429)
    works = respx.get("https://api.openalex.org/works").respond(200, json={"results": []})
    context = TargetContext(discovered_names=["Ana Perez"])
    assert await AcademicFinderTool().execute(context) == []
    assert context.extra["academic_diagnostics"] == [
        {"provider": "crossref", "endpoint": "works", "status": "no_results", "received": 0, "http_status": 200},
        {"provider": "openalex", "endpoint": "authors", "status": "rate_limited", "http_status": 429}]
    assert not works.called
    assert not AcademicFinderTool().can_run(TargetContext(email="seed@example.test"))
