"""Bounded reading of public search pages; optional JS extraction via TinyFish."""
import asyncio
import json
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.tools import http_client
from app.tools.base import TargetContext, ToolFinding
from app.tools.dni_public import public_source_url

MAX_BYTES = 1_000_000
MAX_TEXT = 20_000
TINYFETCH_URL = "https://api.fetch.tinyfish.ai"


def _public_page_url(value: str) -> str | None:
    url = public_source_url(value)
    if not url:
        return None
    parts = set(urlsplit(url).path.lower().split("/"))
    return None if parts & {"login", "signin", "sign-in", "oauth", "logout", "auth"} else url


async def _check_request(request: httpx.Request) -> None:
    if not _public_page_url(str(request.url)):
        raise httpx.InvalidURL("Non-public publication URL")


async def read_public_page(url: str) -> dict:
    if not _public_page_url(url):
        return {"status": "unsafe_url"}
    try:
        async with asyncio.timeout(15):
            async with http_client.build_client(timeout=8, max_retries=0, public_only=True,
                                                 follow_redirects=False,
                                                 event_hooks={"request": [_check_request]}) as client:
                for _ in range(4):
                    async with client.stream("GET", url) as response:
                        if response.is_redirect:
                            url = urljoin(url, response.headers.get("location", ""))
                            if not _public_page_url(url):
                                return {"status": "unsafe_redirect"}
                            continue
                        if response.status_code != 200:
                            return {"status": f"http_{response.status_code}"}
                        content_type = response.headers.get("content-type", "").lower()
                        if not any(t in content_type for t in ("text/html", "application/xhtml+xml", "text/plain")):
                            return {"status": "unsupported_content"}
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_BYTES:
                                return {"status": "too_large"}
                        text = bytes(body).decode(response.encoding or "utf-8", errors="replace")
                        title = ""
                        links = []
                        if "html" in content_type:
                            soup = BeautifulSoup(text, "html.parser")
                            # A login page is not public evidence from the requested article.
                            if soup.select_one('input[type="password"]'):
                                return {"status": "login_required"}
                            title = soup.title.get_text(" ", strip=True) if soup.title else ""
                            for anchor in soup.select("a[href]"):
                                linked = _public_page_url(urljoin(url, anchor.get("href", "")))
                                if linked and linked not in links and len(links) < 150:
                                    links.append(linked)
                            for tag in soup.select("script, style, nav, footer, header, noscript, form"):
                                tag.decompose()
                            text = soup.get_text(" ", strip=True)
                        return {"status": "ok" if len(text.strip()) >= 80 else "thin_content",
                                "title": title, "text": text[:MAX_TEXT], "final_url": url, "engine": "native", "links": links}
                return {"status": "redirect_limit"}
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError):
        return {"status": "request_error"}


async def read_tinyfish_page(url: str) -> dict:
    if not settings.tinyfish_enabled or not settings.tinyfish_fetch_enabled:
        return {"status": "disabled"}
    if not _public_page_url(url):
        return {"status": "unsafe_url"}
    try:
        async with asyncio.timeout(20):
            async with http_client.build_client(timeout=18, max_retries=0, rotate_ua=False,
                                                 follow_redirects=False) as client:
                # Stream to enforce a response size bound, even for upstream extraction.
                async with client.stream("POST", TINYFETCH_URL,
                    headers={"X-API-Key": settings.tinyfish_api_key.get_secret_value()},
                    json={"urls": [url], "format": "markdown", "per_url_timeout_ms": 15000}) as response:
                    if response.status_code != 200:
                        return {"status": f"http_{response.status_code}"}
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            return {"status": "too_large"}
                    data = json.loads(body)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            return {"status": "invalid_payload"}
        if data.get("errors"):
            return {"status": "provider_error"}
        for item in data["results"]:
            if not isinstance(item, dict) or item.get("url") != url:
                continue
            final_url = item.get("final_url") or url
            if not isinstance(final_url, str) or not _public_page_url(final_url):
                return {"status": "unsafe_redirect"}
            text = item.get("text")
            if not isinstance(text, str):
                return {"status": "invalid_payload"}
            return {"status": "ok" if len(text.strip()) >= 80 else "thin_content",
                    "text": text[:MAX_TEXT], "title": item.get("title") if isinstance(item.get("title"), str) else "",
                    "final_url": final_url, "engine": "tinyfish_fetch"}
        return {"status": "empty"}
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError):
        return {"status": "request_error"}


async def enrich_search_findings(findings: list[ToolFinding], context: TargetContext) -> None:
    from app.tools.search_dorker import Dork, _matches_literally
    read_urls = context.extra.setdefault("search_read_urls", [])
    fetch_disabled = context.extra.get("search_fetch_disabled", False)
    for finding in findings:
        if len(read_urls) >= max(0, min(10, settings.search_max_pages)):
            break
        # Platform verification and public DNI document reading have their own tools.
        if finding.platform != "web_search" or finding.metadata_info.get("dni_query") or finding.value in read_urls:
            continue
        read_urls.append(finding.value)
        page = await read_public_page(finding.value)
        native_status = page["status"]
        if (native_status not in {"ok", "unsafe_url", "unsafe_redirect", "login_required", "unsupported_content", "too_large"}
                and settings.tinyfish_enabled and settings.tinyfish_fetch_enabled and not fetch_disabled):
            page = await read_tinyfish_page(finding.value)
            if page["status"] in {"http_401", "http_402", "http_403", "http_429"}:
                fetch_disabled = True
                context.extra["search_fetch_disabled"] = True
        meta = finding.metadata_info
        meta["page_read_status"] = page["status"]
        meta["page_native_status"] = native_status
        if page["status"] != "ok":
            continue
        dork = Dork(meta["query"], meta["rationale"], phone=meta.get("phone_query"))
        match = _matches_literally(dork, page["title"], page["text"], "")
        meta["page_literal_match"] = match
        meta["page_reader"] = page["engine"]
        meta["page_final_url"] = page["final_url"]
        if match:
            meta["page_excerpt"] = page["text"][:2000]
            meta["page_evidence_status"] = "public_mention_unverified_owner"
            if page["final_url"] not in finding.evidence_urls:
                finding.evidence_urls.append(page["final_url"])
