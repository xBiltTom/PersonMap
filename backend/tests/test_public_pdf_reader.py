"""Real native PDF extraction and explicit unsupported/image-only gaps."""
import hashlib
import shutil

import pytest
import respx

from app.tools import search_reader
from app.tools.base import TargetContext
from app.tools.public_page_reader import PublicPageReaderTool


def native_pdf():
    stream = b'BT /F1 12 Tf 30 100 Td (Public paper by Ana Perez. Open research evidence.) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    body = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body.extend(str(index).encode() + b' 0 obj\n' + obj + b'\nendobj\n')
    start = len(body)
    body.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        body.extend(f'{offset:010} 00000 n \n'.encode())
    body.extend(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    return bytes(body)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.skipif(not shutil.which('pdftotext'), reason='Poppler not installed')
async def test_pdf_is_read_and_captured_with_text_hash_and_page_bound():
    url = 'https://repo.example.test/paper.pdf'
    respx.get(url).respond(200, content=native_pdf(), headers={'content-type': 'application/pdf'})
    page = await search_reader.read_public_page(url, focus_terms=['Ana Perez'])
    assert page['status'] == 'ok' and page['engine'] == 'native_pdf'
    assert 'Ana Perez' in page['text'] and page['pdf_pages_read'] == 1
    assert not page['pdf_page_limit_reached']
    findings = await PublicPageReaderTool().execute(TargetContext(full_name='Ana Perez', extra={'candidate_urls': [url]}))
    meta = findings[0].metadata_info
    assert meta['content_sha256'] == hashlib.sha256(meta['page_text'].encode()).hexdigest()
    assert meta['pdf_pages_read'] == 1


@pytest.mark.asyncio
@respx.mock
async def test_invalid_pdf_and_missing_parser_remain_explicit_gaps(monkeypatch):
    url = 'https://repo.example.test/paper.pdf'
    route = respx.get(url).respond(200, content=b'fake document', headers={'content-type': 'application/pdf'})
    assert (await search_reader.read_public_page(url))['status'] == 'invalid_pdf'
    route.respond(200, content=native_pdf(), headers={'content-type': 'application/pdf'})
    monkeypatch.setattr(search_reader.shutil, 'which', lambda _: None)
    assert (await search_reader.read_public_page(url))['status'] == 'pdf_reader_unavailable'
