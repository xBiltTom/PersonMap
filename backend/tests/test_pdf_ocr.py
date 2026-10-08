import io
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import respx
from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.tools import pdf_ocr
from app.tools.base import TargetContext
from app.tools.dni_lookup import DniLookupTool
from app.tools.dni_public import parse_public_document
from app.engine.pivot_rules import extract_and_apply_pivots

DNI = '00123456'
URL = 'https://www.reniec.gob.pe/publicacion.pdf'
HEADER = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'


def tsv(number=DNI, score=97):
    return HEADER + '5\t1\t1\t1\t1\t1\t10\t10\t50\t20\t96\tDNI:\n' + f'5\t1\t1\t1\t1\t2\t70\t10\t100\t20\t{score}\t{number}\n'


@pytest.fixture(autouse=True)
def ocr_settings(monkeypatch):
    monkeypatch.setattr(settings, 'pdf_ocr_enabled', True)
    monkeypatch.setattr(settings, 'pdf_ocr_max_pages', 3)
    monkeypatch.setattr(settings, 'pdf_ocr_timeout_seconds', 20)
    monkeypatch.setattr(settings, 'pdf_ocr_languages', 'auto')


@pytest.mark.parametrize('number,score,accepted', [(DNI,97,True),(DNI,84,False),(DNI,'nan',False),(DNI,101,False),('001234S6',99,False),('99'+DNI+'99',99,False),('00 12 34 56',99,False)])
def test_ocr_digits_are_not_repaired_or_partial(number,score,accepted):
    rows=pdf_ocr.read_ocr_tsv(tsv(number,score),DNI,2,'spa')
    assert bool(rows) is accepted
    if accepted:
        assert rows[0]['page'] == 2
        assert rows[0]['review_required'] is True
        assert rows[0]['ocr_bbox_pixels'] == [70,10,100,20]
        assert 'full_name' not in rows[0]


def test_ocr_disabled_or_missing_tools_is_diagnostic(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'pdf_ocr_enabled',False)
    assert pdf_ocr.ocr_pdf(tmp_path/'source.pdf',tmp_path,[''],DNI) == ([], 'pdf_ocr_disabled')
    monkeypatch.setattr(settings,'pdf_ocr_enabled',True)
    monkeypatch.setattr(pdf_ocr.shutil,'which',lambda name: None)
    assert pdf_ocr.ocr_pdf(tmp_path/'source.pdf',tmp_path,[''],DNI) == ([], 'pdf_ocr_unavailable')


def test_ocr_timeout_does_not_produce_finding(tmp_path,monkeypatch):
    monkeypatch.setattr(pdf_ocr.shutil,'which',lambda name: name)
    def fail(*args,**kwargs):
        raise subprocess.TimeoutExpired(args[0],1)
    monkeypatch.setattr(pdf_ocr,'_run',fail)
    assert pdf_ocr.ocr_pdf(tmp_path/'source.pdf',tmp_path,[''],DNI) == ([], 'pdf_ocr_timeout')


def test_ocr_honors_page_limit_and_skips_dense_native_pages(tmp_path,monkeypatch):
    monkeypatch.setattr(pdf_ocr.shutil,'which',lambda name: name)
    monkeypatch.setattr(settings,'pdf_ocr_max_pages',2)
    rendered=[]
    def fake_run(command,*args,**kwargs):
        if '--list-langs' in command:
            return SimpleNamespace(stdout=b'List of available languages (1):\neng\n')
        if command[0] == 'pdftoppm':
            rendered.append(int(command[2]))
            Path(command[-1]+'.png').write_bytes(b'image')
        elif command[0] == 'tesseract':
            Path(command[2]+'.tsv').write_text(HEADER)
        return SimpleNamespace(stdout=b'')
    monkeypatch.setattr(pdf_ocr,'_run',fake_run)
    assert pdf_ocr.ocr_pdf(tmp_path/'source.pdf',tmp_path,['A'*100,'','',''],DNI)[1] == 'pdf_ocr_no_match'
    assert rendered == [2]


def test_explicit_language_missing_does_not_silently_switch(tmp_path,monkeypatch):
    monkeypatch.setattr(pdf_ocr.shutil,'which',lambda name: name)
    monkeypatch.setattr(settings,'pdf_ocr_languages','spa+eng')
    monkeypatch.setattr(pdf_ocr,'_run',lambda *args,**kwargs:SimpleNamespace(stdout=b'Available:\nafr\nosd\n'))
    assert pdf_ocr.ocr_pdf(tmp_path/'source.pdf',tmp_path,[''],DNI)[1] == 'pdf_ocr_language_unavailable'


def scanned_pdf():
    # A synthetic image-only PDF: there is deliberately no embedded text layer.
    image=Image.new('RGB',(1600,1000),'white')
    draw=ImageDraw.Draw(image)
    font_path = next(Path('/usr/share/fonts').rglob('LiberationMono-Regular.ttf'), None)
    font=ImageFont.truetype(str(font_path),72) if font_path else ImageFont.load_default(size=72)
    draw.text((120,280),f'DNI: {DNI}',fill='black',font=font)
    output=io.BytesIO()
    image.save(output,format='PDF',resolution=150)
    return output.getvalue()


def require_real_tools():
    if not all(shutil.which(name) for name in ('tesseract','pdftoppm','pdftotext')):
        pytest.skip('Real OCR integration requires Tesseract and Poppler')
    info = subprocess.run(['tesseract', '--list-langs'], capture_output=True, check=True, timeout=5)
    models = set(info.stdout.decode(errors='replace').splitlines()[1:])
    cache = Path(__file__).resolve().parents[1] / '.ocr-models'
    cached = not os.environ.get('TESSDATA_PREFIX') and any((cache / f'{lang}.traineddata').is_file() for lang in ('spa', 'eng'))
    if not models.intersection({'spa', 'eng'}) and not cached:
        pytest.skip('Real OCR integration requires an English or Spanish model')


def test_real_scanned_pdf_ocr():
    require_real_tools()
    rows,kind=parse_public_document(scanned_pdf(),'application/pdf',URL,DNI)
    assert kind == 'pdf_ocr'
    assert rows[0]['dni'] == DNI
    assert rows[0]['page'] == 1
    assert rows[0]['ocr_word_confidence'] >= 85
    assert rows[0]['review_required']
    assert not rows[0].get('full_name')


@pytest.mark.asyncio
@respx.mock
async def test_real_ocr_in_public_document_pipeline(monkeypatch):
    require_real_tools()
    monkeypatch.setattr(settings,'dni_public_source_urls',[])
    respx.get(URL).respond(200,content=scanned_pdf(),headers={'content-type':'application/pdf'})
    context=TargetContext(dni=DNI,extra={'dni_source_urls':[URL]})
    findings=await DniLookupTool().execute(context)
    assert len(findings) == 1
    finding=findings[0]
    assert finding.evidence_urls == [URL]
    assert finding.metadata_info['verification_status'] == 'ocr_candidate'
    assert finding.metadata_info['page'] == 1
    assert finding.confidence == 0.35
    extract_and_apply_pivots(findings,context)
    assert context.discovered_names == []
    assert context.full_name is None
