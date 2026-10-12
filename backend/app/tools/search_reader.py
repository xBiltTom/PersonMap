"""Bounded reading of public search pages; optional JS extraction via TinyFish."""
import asyncio
import json
import hashlib
import re
import shutil
import subprocess
import tempfile
import unicodedata
from array import array
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.tools import http_client
from app.tools.base import TargetContext, ToolFinding
from app.tools.dni_public import public_source_url

MAX_BYTES = 1_000_000
MAX_TEXT = 20_000
MAX_PDF_BYTES = 5_000_000
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


def _pdf_text(body: bytes) -> dict:
    """Bounded Poppler extraction in a worker thread; image-only pages stay explicit gaps."""
    if not body.startswith(b"%PDF-"):
        return {"status": "invalid_pdf"}
    if not shutil.which("pdftotext"):
        return {"status": "pdf_reader_unavailable"}
    try:
        with tempfile.TemporaryDirectory(prefix="person-map-public-pdf-") as directory:
            source = Path(directory) / "source.pdf"
            output = Path(directory) / "text.txt"
            source.write_bytes(body)
            subprocess.run(["pdftotext", "-f", "1", "-l", "31", "-layout", str(source), str(output)],
                           timeout=5, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if output.stat().st_size > MAX_BYTES:
                return {"status": "text_too_large"}
            pages = output.read_text(errors="replace").split("\f")
            if pages and not pages[-1].strip():
                pages.pop()
            text = "\n".join(pages[:30])
            return {"status": "ok" if text.strip() else "pdf_no_extractable_text", "text": text,
                    "pdf_pages_read": min(30, len(pages)), "pdf_page_limit_reached": len(pages) > 30}
    except subprocess.TimeoutExpired:
        return {"status": "pdf_parse_timeout"}
    except (subprocess.SubprocessError, OSError):
        return {"status": "pdf_parse_error"}


def _focus_excerpt(text: str, terms: list[str]) -> tuple[str, bool]:
    """Keep a bounded excerpt around a full name even late in a long public roll."""
    if not terms:
        return text[:MAX_TEXT], False
    folded, positions = [], array("I")
    for index, char in enumerate(text):
        normalized = "".join(c for c in unicodedata.normalize("NFKD", char).casefold() if not unicodedata.combining(c))
        folded.append(normalized)
        positions.extend([index] * len(normalized))
    shadow = "".join(folded)
    for term in terms[:2]:
        normalized = "".join(c for c in unicodedata.normalize("NFKD", term).casefold() if not unicodedata.combining(c))
        pattern = r"(?<!\w)" + r"[\s,;:]+".join(re.escape(part) for part in normalized.split()) + r"(?!\w)"
        match = re.search(pattern, shadow) if normalized.strip() else None
        if match:
            start, end = positions[match.start()], positions[match.end()-1] + 1
            excerpt = text[max(0, start-500):end+1000]
            prefix = text[:min(800, max(0, start-500))]
            return (prefix + ("\n[…]\n" if prefix else "") + excerpt)[:MAX_TEXT], True
    return text[:MAX_TEXT], False


async def read_public_page(url: str, *, focus_terms: list[str] | None = None) -> dict:
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
                        is_pdf = "application/pdf" in content_type
                        if not is_pdf and not any(t in content_type for t in ("text/html", "application/xhtml+xml", "text/plain")):
                            return {"status": "unsupported_content"}
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > (MAX_PDF_BYTES if is_pdf else MAX_BYTES):
                                return {"status": "too_large"}
                        if is_pdf:
                            # Match the existing public-document worker: bounded subprocess
                            # work stays off the loop; polling also works in restricted runtimes.
                            with ThreadPoolExecutor(max_workers=1) as pool:
                                future = pool.submit(_pdf_text, bytes(body))
                                while not future.done():
                                    await asyncio.sleep(0.05)
                                extracted = future.result()
                            if extracted["status"] != "ok":
                                return extracted
                            text = extracted.pop("text")
                            selected, focused = _focus_excerpt(text, focus_terms or [])
                            return {**extracted, "text": selected, "title": "", "links": [],
                                    "final_url": url, "engine": "native_pdf",
                                    "content_selection": "name_excerpt" if focused else "prefix",
                                    "content_truncated": len(selected) < len(text) or extracted["pdf_page_limit_reached"]}
                        text = bytes(body).decode(response.encoding or "utf-8", errors="replace")
                        title = ""
                        links = []
                        if "html" in content_type:
                            soup = BeautifulSoup(text, "html.parser")
                            # A login page is not public evidence from the requested article.
                            if soup.select_one('input[type="password"]'):
                                return {"status": "login_required"}
                            title = soup.title.get_text(" ", strip=True) if soup.title else ""
                            for tag in soup.select("script, style, nav, footer, header, noscript, form"):
                                tag.decompose()
                            for anchor in soup.select("a[href]"):
                                linked = _public_page_url(urljoin(url, anchor.get("href", "")))
                                if linked and linked not in links and len(links) < 150:
                                    links.append(linked)
                            text = soup.get_text(" ", strip=True)
                        selected, focused = _focus_excerpt(text, focus_terms or [])
                        return {"status": "ok" if len(text.strip()) >= 80 else "thin_content",
                                "title": title, "text": selected, "final_url": url, "engine": "native", "links": links,
                                "content_selection": "name_excerpt" if focused else "prefix",
                                "content_truncated": len(selected) < len(text)}
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
    from app.tools.search_dorker import Dork, _matches_literally, DOCUMENT_PLATFORMS
    read_urls = context.extra.setdefault("search_read_urls", [])
    fetch_disabled = context.extra.get("search_fetch_disabled", False)
    for finding in findings:
        if len(read_urls) >= max(0, min(10, settings.search_max_pages)):
            break
        # Platform verification and public DNI document reading have their own tools.
        if finding.platform not in {"web_search", *DOCUMENT_PLATFORMS, "medium", "devto", "zenodo", "figshare", "academia"} or finding.metadata_info.get("dni_query") or finding.value in read_urls:
            continue
        read_urls.append(finding.value)
        page = await read_public_page(finding.value, focus_terms=finding.metadata_info.get("name_search_variants", []))
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
        meta["page_content_selection"] = page.get("content_selection", "prefix")
        meta["page_content_truncated"] = page.get("content_truncated", False)
        if page["status"] != "ok":
            continue
        dork = Dork(meta["query"], meta["rationale"], phone=meta.get("phone_query"),
                    name_variants=meta.get("name_search_variants", []))
        match = _matches_literally(dork, page["title"], page["text"], "")
        meta["page_literal_match"] = match
        meta["page_reader"] = page["engine"]
        meta["page_final_url"] = page["final_url"]
        meta["retrieved_at"] = datetime.now(timezone.utc).isoformat()
        meta["content_sha256"] = hashlib.sha256(page["text"].encode()).hexdigest()
        meta["pdf_pages_read"] = page.get("pdf_pages_read")
        if match:
            meta["page_excerpt"] = page["text"][:2000]
            meta["page_text"] = page["text"]
            meta["page_evidence_status"] = "public_mention_unverified_owner"
            if page["final_url"] not in finding.evidence_urls:
                finding.evidence_urls.append(page["final_url"])
