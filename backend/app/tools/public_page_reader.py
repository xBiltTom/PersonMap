"""Capture a public page so an agent can analyze the text and cite its snapshot."""
import hashlib
import asyncio
from datetime import datetime, timezone

from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.search_reader import read_public_page, read_tinyfish_page


class PublicPageReaderTool(BaseTool):
    name = "public_page_reader"
    description = "Lee hasta tres URLs públicas explícitas y guarda su texto, enlaces, fecha y hash como evidencia; no ejecuta instrucciones de las páginas."
    category = ToolCategory.DOCUMENT
    required_inputs = ["candidate_urls"]

    def can_run(self, context):
        return bool(context.extra.get("candidate_urls"))

    async def execute(self, context: TargetContext) -> list[ToolFinding]:
        urls = context.extra.get("candidate_urls", [])[:3]

        async def read_one(url):
            page = await read_public_page(url)
            if page["status"] in {"thin_content", "request_error", "http_403"}:
                fallback = await read_tinyfish_page(url)
                if fallback.get("status") == "ok":
                    page = fallback
            if page["status"] not in {"ok", "thin_content"}:
                raise ValueError(f"No se pudo leer la página pública: {page['status']}")
            text = page.get("text", "")
            final_url = page.get("final_url", url)
            return ToolFinding(
                entity_type="web_page", platform="public_web", value=final_url,
                display_name=page.get("title") or final_url,
                metadata_info={
                    "page_text": text, "page_excerpt": text[:2000],
                    "page_read_status": page["status"], "page_reader": page.get("engine"),
                    "source_url": url, "page_final_url": final_url,
                    "linked_profiles": page.get("links", []),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "content_truncated": len(text) >= 20000,
                }, evidence_urls=list(dict.fromkeys([url, final_url])),
            )
        results = await asyncio.gather(*(read_one(url) for url in urls), return_exceptions=True)
        findings = [result for result in results if isinstance(result, ToolFinding)]
        context.extra["public_page_reader_errors"] = [
            {"url": url, "status": str(result)[:200] if isinstance(result, ValueError) else "request_error"}
            for url, result in zip(urls, results) if isinstance(result, Exception)]
        if not findings and urls:
            raise ValueError("No se pudo capturar ninguna de las páginas seleccionadas")
        return findings
