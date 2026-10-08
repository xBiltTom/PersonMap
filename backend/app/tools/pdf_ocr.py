"""Bounded local OCR for sparse PDF pages; observations are review candidates."""
import csv
import io
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from app.core.config import settings

MAX_OUTPUT_BYTES = 1000000


def _run(command: list[str], deadline: float, **kwargs):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(command, 0)
    return subprocess.run(command, timeout=remaining, check=True,
                          stderr=subprocess.DEVNULL, **kwargs)


def read_ocr_tsv(text: str, dni: str, page: int, language: str) -> list[dict]:
    """Accept a complete OCR word with a strong score, never repair digits."""
    from app.tools.dni_public import matches_dni
    lines = {}
    matches = []
    for row in csv.DictReader(io.StringIO(text[:MAX_OUTPUT_BYTES]), delimiter='\t'):
        if row.get('level') != '5' or not isinstance(row.get('text'), str) or not row['text'].strip():
            continue
        key = (row.get('block_num'), row.get('par_num'), row.get('line_num'))
        lines.setdefault(key, []).append(row)
    for words in lines.values():
        line = ' '.join(w['text'] for w in words)
        if not matches_dni(dni, line):
            continue
        for word in words:
            if not matches_dni(dni, word['text']):
                continue
            try:
                score = float(word['conf'])
                box = [int(word[k]) for k in ('left', 'top', 'width', 'height')]
            except (KeyError, ValueError, TypeError):
                continue
            if not 85 <= score <= 100 or any(n < 0 for n in box):
                continue
            offset = line.find(dni)
            matches.append({'dni': dni, 'excerpt': line[max(0, offset-100):offset+len(dni)+100],
                            'name_association': 'unverified', 'page': page,
                            'extraction_method': 'ocr', 'ocr_engine': 'tesseract',
                            'ocr_language': language, 'ocr_word_confidence': score,
                            'ocr_bbox_pixels': box, 'review_required': True})
            break
        if len(matches) >= 3:
            break
    return matches


def ocr_pdf(source: Path, directory: Path, native_pages: list[str], dni: str) -> tuple[list[dict], str]:
    if not settings.pdf_ocr_enabled:
        return [], 'pdf_ocr_disabled'
    limit = min(10, max(0, settings.pdf_ocr_max_pages))
    if not limit:
        return [], 'pdf_ocr_disabled'
    if not shutil.which('pdftoppm') or not shutil.which('tesseract'):
        return [], 'pdf_ocr_unavailable'
    deadline = time.monotonic() + min(60, max(1, settings.pdf_ocr_timeout_seconds))
    try:
        environment = {**os.environ, 'OMP_THREAD_LIMIT':'1'}
        info = _run(['tesseract', '--list-langs'], deadline, stdout=subprocess.PIPE, env=environment)
        installed = set(info.stdout.decode(errors='replace').splitlines()[1:])
        cache = Path(__file__).resolve().parents[2] / '.ocr-models'
        if not installed.intersection({'spa', 'eng'}) and not os.environ.get('TESSDATA_PREFIX') and cache.is_dir():
            environment['TESSDATA_PREFIX'] = str(cache)
            info = _run(['tesseract', '--list-langs'], deadline, stdout=subprocess.PIPE, env=environment)
            installed = set(info.stdout.decode(errors='replace').splitlines()[1:])
        requested = settings.pdf_ocr_languages
        if requested == 'auto':
            selected = [lang for lang in ('spa', 'eng') if lang in installed]
            language = '+'.join(selected)
        else:
            language = requested if re.fullmatch(r'[a-z]{3}(?:\+[a-z]{3})*', requested) and set(requested.split('+')) <= installed else ''
        if not language:
            return [], 'pdf_ocr_language_unavailable'
        scanned = 0
        # pdftotext keeps page breaks, allowing mixed text/image PDFs.
        for index, text in enumerate(native_pages[:limit], 1):
            if len(re.sub(r'\s', '', text)) >= 80:
                continue
            scanned += 1
            prefix = directory / f'page-{index}'
            _run(['pdftoppm', '-f', str(index), '-l', str(index), '-singlefile', '-scale-to', '2000',
                  '-gray', '-png', str(source), str(prefix)], deadline, stdout=subprocess.DEVNULL)
            image = prefix.with_suffix('.png')
            if not image.exists() or image.stat().st_size > 10000000:
                return [], 'pdf_ocr_render_error'
            output = directory / f'ocr-{index}'
            _run(['tesseract', str(image), str(output), '-l', language, '--psm', '3', '-c', 'tessedit_create_tsv=1'],
                 deadline, stdout=subprocess.DEVNULL, env=environment)
            tsv = output.with_suffix('.tsv')
            if not tsv.exists() or tsv.stat().st_size > MAX_OUTPUT_BYTES:
                return [], 'pdf_ocr_output_too_large'
            # The target is supplied by the caller, not guessed from arbitrary digits.
            rows = read_ocr_tsv(tsv.read_text(errors='replace'), dni, index, language)
            if rows:
                return rows, 'pdf_ocr'
        return [], 'pdf_ocr_no_match' if scanned else 'pdf'
    except subprocess.TimeoutExpired:
        return [], 'pdf_ocr_timeout'
    except (subprocess.CalledProcessError, OSError):
        return [], 'pdf_ocr_error'
