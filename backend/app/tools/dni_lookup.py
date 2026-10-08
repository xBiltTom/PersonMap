"""Observe DNI mentions in openly accessible publications, including RENIEC."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx

from app.core.config import settings
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.dni_public import normalize_dni, public_source_url, publisher, parse_public_document
from app.tools.public_network import UnsafePublicURL


async def _public_request(request: httpx.Request) -> None:
    if not public_source_url(str(request.url)):
        raise UnsafePublicURL('Not a public publication URL')


class DniLookupTool(BaseTool):
    name = 'dni_lookup'
    description = 'Verifica menciones de DNI en páginas y datasets públicos (incluido RENIEC), conservando fuente y contexto.'
    category = ToolCategory.DOCUMENT
    required_inputs = ['dni']

    def can_run(self, context: TargetContext) -> bool:
        return normalize_dni(context.dni) is not None

    async def execute(self, context: TargetContext) -> list[ToolFinding]:
        dni = normalize_dni(context.dni)
        if not dni:
            context.extra['dni_lookup_status'] = 'invalid_input'
            return []
        candidates = [*settings.dni_public_source_urls, *context.extra.get('dni_source_urls', [])]
        sources = list(dict.fromkeys(url for raw in candidates if isinstance(raw, str) and (url := public_source_url(raw))))
        outcomes = context.extra.setdefault('dni_public_results', {})
        findings = []
        limit = max(0, settings.dni_max_public_sources)
        async with http_client.build_client(timeout=10, public_only=True, max_retries=0, follow_redirects=True, max_redirects=3, event_hooks={'request': [_public_request]}) as client:
            for url in sources:
                key = dni + '|' + url
                if key in outcomes or len(outcomes) >= limit:
                    continue
                outcomes[key] = {'status': 'started', 'source_url': url}
                try:
                    async with client.stream('GET', url) as response:
                        if response.status_code != 200:
                            outcomes[key]['status'] = 'http_error'
                            outcomes[key]['http_status'] = response.status_code
                            continue
                        size = response.headers.get('content-length', '')
                        if size.isdecimal() and int(size) > 2000000:
                            outcomes[key]['status'] = 'too_large'
                            continue
                        chunks, length = [], 0
                        async for chunk in response.aiter_bytes():
                            length += len(chunk)
                            if length > 2000000:
                                break
                            chunks.append(chunk)
                        if length > 2000000:
                            outcomes[key]['status'] = 'too_large'
                            continue
                        source_url = str(response.url)
                        if not public_source_url(source_url):
                            outcomes[key]['status'] = 'unsupported_source'
                            continue
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            rows, kind = await asyncio.get_running_loop().run_in_executor(pool, parse_public_document, b''.join(chunks), response.headers.get('content-type', ''), source_url, dni)
                    outcomes[key].update(status='observed' if rows else 'no_match', document_format=kind, final_url=source_url)
                    for row in rows:
                        metadata = {**row, 'source_url': source_url, 'source_kind': 'public_document',
                                    'publisher': publisher(source_url), 'document_format': kind,
                                    'verification_status': 'public_document_observed', 'ownership_status': 'unverified',
                                    'checked_at': datetime.now(timezone.utc).isoformat(), 'source_tool': self.name}
                        findings.append(ToolFinding(entity_type='document', platform=publisher(source_url),
                            value=f'DNI: {dni} | {source_url} | {row.get("record_index", "mention")}',
                            display_name=row.get('full_name') or f'DNI {dni}', metadata_info=metadata,
                            confidence=0.65 if row.get('full_name') else 0.45, evidence_urls=[source_url]))
                except (httpx.HTTPError, UnsafePublicURL, ValueError):
                    outcomes[key]['status'] = 'request_error'
        context.extra['dni_lookup_status'] = 'public_evidence_found' if findings else 'no_new_public_evidence'
        return findings
