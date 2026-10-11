"""Document recall without dropping literal name safeguards or increasing budgets."""
import json

import httpx
import pytest
import respx

from app.core.config import settings
from app.tools.base import TargetContext
from app.tools.search_dorker import DOCUMENT_DOMAINS, Dork, SearchDorkerTool, _matches_literally, name_search_variants
from app.tools.search_reader import enrich_search_findings, read_public_page, MAX_TEXT

NAME = "José Luis Ríos Vega"
REVERSED = "Ríos Vega José Luis"


def test_name_ordering_is_bounded_and_keeps_all_name_tokens():
    assert name_search_variants(NAME) == [NAME, REVERSED]
    assert name_search_variants("Ana Pérez") == ["Ana Pérez"]
    dork = Dork(f'"{NAME}" OR "{REVERSED}"', "Document search", name_variants=name_search_variants(NAME))
    assert _matches_literally(dork, "Padrón", "RIOS VEGA, JOSE LUIS INGENIERIA", "https://es.scribd.com/document/123/listado")
    assert not _matches_literally(dork, "Padrón", "Ríos Vega Juan Luis", "https://example.test/")
    assert not _matches_literally(dork, "José publicó un libro", "Vega estudió a Ríos y a Luis", "https://example.test/")
    # The agent's independent quoted anchors still mean AND, never an implicit OR.
    assert not _matches_literally(Dork(f'"{NAME}" "{REVERSED}"', "Agent query"), NAME, "", "https://example.test/")


@pytest.mark.asyncio
@respx.mock
async def test_document_query_fits_existing_budget_with_every_identifier(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "fixture")
    monkeypatch.setattr(settings, "tavily_max_queries", 5)
    monkeypatch.setattr(settings, "search_max_queries_per_round", 5)
    monkeypatch.setattr(settings, "search_read_pages", False)
    route = respx.post("https://api.tavily.com/search").respond(200, json={"results": [{
        "title": "Relación de estudiantes", "url": "https://es.scribd.com/document/123/padron",
        "content": "RIOS VEGA JOSE LUIS INGENIERIA"}]})
    respx.post("https://html.duckduckgo.com/html/").respond(202)
    ctx = TargetContext(full_name=NAME, email="fixture@example.test", username="fixture", phone="+51987654321",
                        dni="00123456", university="Universidad de Prueba")
    findings = await SearchDorkerTool().execute(ctx)
    payloads = [json.loads(call.request.content) for call in route.calls]
    assert len(payloads) == 5 and ctx.extra["search_queries_used"] == 5
    query = next(payload for payload in payloads if payload.get("include_domains") == DOCUMENT_DOMAINS)
    assert REVERSED in query["query"] and "Universidad" not in query["query"]
    assert len(findings) == 1 and findings[0].platform == "scribd"
    assert findings[0].metadata_info["matched_name_variant"] == REVERSED
    assert findings[0].metadata_info["ownership_status"] == "unverified"
    assert any(item["rejections"].get("literal_evidence_missing") for item in ctx.extra["search_diagnostics"])


@pytest.mark.asyncio
@respx.mock
async def test_optional_reader_checks_scribd_document_name_without_promoting_identity(monkeypatch):
    monkeypatch.setattr(settings, "tinyfish_api_key", None)
    url = "https://www.collegesidekick.com/study-docs/123"
    respx.get(url).respond(200, text=("Listado institucional. RIÓS VEGA, JOSÉ LUIS. " * 5), headers={"content-type": "text/plain"})
    tool = SearchDorkerTool()
    dork = Dork(f'"{NAME}" OR "{REVERSED}"', "Document search", name_variants=name_search_variants(NAME), scope="documents")
    finding = tool._validated_finding(dork, url, "Padrón", REVERSED, "tavily")
    assert finding.platform == "college_sidekick"
    await enrich_search_findings([finding], TargetContext())
    assert finding.metadata_info["page_literal_match"] is True
    assert finding.metadata_info["page_evidence_status"] == "public_mention_unverified_owner"
    assert finding.metadata_info["ownership_status"] == "unverified"


@pytest.mark.asyncio
@respx.mock
async def test_reader_finds_name_past_prefix_and_excludes_navigation_links():
    url = "https://es.scribd.com/document/123/padron"
    text = "Fila no relacionada con el objetivo. " * 1000
    html = f'<title>Padrón de Prueba</title><nav><a href="https://example.test/pricing">Precios</a></nav><article>{text}<p>RIOS VEGA, JOSE LUIS INGENIERIA</p><a href="https://example.test/document-source">Fuente</a></article><footer><a href="https://example.test/help">Ayuda</a></footer>'
    respx.get(url).respond(200, text=html, headers={"content-type": "text/html"})
    page = await read_public_page(url, focus_terms=name_search_variants(NAME))
    assert "RIOS VEGA, JOSE LUIS" in page["text"]
    assert len(page["text"]) <= MAX_TEXT
    assert page["content_selection"] == "name_excerpt" and page["content_truncated"]
    assert page["links"] == ["https://example.test/document-source"]
