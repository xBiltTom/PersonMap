"""Exact DNI observations in public documents; names require the same record."""
import csv
import io
import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup


def normalize_dni(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if re.fullmatch(r'[0-9]{8}', value) else None


def matches_dni(dni: str, text: str) -> bool:
    if text.strip().startswith(('http://', 'https://')) and ' ' not in text.strip():
        return False
    return bool(normalize_dni(dni) and re.search(r'(?<![\w])' + re.escape(dni) + r'(?![\w])', text))


def public_source_url(value: str) -> str | None:
    try:
        url = urlsplit(value)
        if (url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password
                or url.port not in {None, 80, 443} or any(c.isspace() or ord(c) < 32 for c in value)):
            return None
        if any(key.lower() in {'token', 'api_key', 'access_token', 'authorization', 'password', 'x-amz-signature'} for key in parse_qs(url.query)):
            return None
        # Third-party lookup routes are not publication sources.
        host = url.hostname.lower().rstrip('.')
        if host in {'api.apis.net.pe', 'dniruc.apisperu.com', 'api.decolecta.com'}:
            return None
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            return None
        import ipaddress
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value.split('#', 1)[0]
    except (ValueError, TypeError):
        return None


def publisher(url: str) -> str:
    host = (urlsplit(url).hostname or '').lower().rstrip('.')
    return 'reniec_public' if host == 'reniec.gob.pe' or host.endswith('.reniec.gob.pe') else host


def _key(value) -> str:
    text = unicodedata.normalize('NFKD', str(value))
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in text.lower() if not unicodedata.combining(c)))


DOCUMENT_KEYS = {'dni', 'numerodocumento', 'documento', 'ndocumento', 'numerodni'}
NAME_KEYS = ('nombrecompleto', 'apellidosynombres', 'nombresyapellidos', 'nombreyapellidos', 'fullname')


def _name(row: dict) -> str | None:
    values = {_key(k): v.strip() for k, v in row.items() if isinstance(v, str)}
    complete = next((values[k] for k in NAME_KEYS if values.get(k)), None)
    if not complete:
        given = values.get('nombres') or values.get('nombre') or ' '.join(filter(None, [values.get('primernombre'), values.get('segundonombre')]))
        surnames = values.get('apellidos') or ' '.join(filter(None, [values.get('apellidopaterno'), values.get('apellidomaterno')]))
        complete = ' '.join(filter(None, [given, surnames])) if given and surnames else None
    if complete and len(complete) <= 160 and len(complete.split()) >= 2 and not any(c.isdigit() for c in complete):
        return complete
    return None


def _records(rows, dni: str) -> list[dict]:
    matches = []
    for index, row in enumerate(rows):
        if index >= 20000:
            break
        if not isinstance(row, dict):
            continue
        ids = [str(v).strip() for k, v in row.items() if _key(k) in DOCUMENT_KEYS]
        if dni not in ids or any(value != dni for value in ids):
            continue
        # Only the matching record is retained, never the full dataset.
        matches.append({'dni': dni, 'full_name': _name(row), 'record_index': index + 1,
                        'excerpt': f'DNI: {dni}' + (f'; Nombre: {_name(row)}' if _name(row) else ''),
                        'name_association': 'structured_same_record'})
        if len(matches) >= 3:
            break
    return matches


def _text_matches(text: str, dni: str) -> list[dict]:
    for line in text[:500000].splitlines():
        if matches_dni(dni, line):
            match = re.search(re.escape(dni), line)
            # A free-text mention is evidence, but surrounding names are ambiguous.
            return [{'dni': dni, 'excerpt': line[max(0, match.start() - 100):match.end() + 100],
                     'name_association': 'unverified'}]
    return []


def parse_public_document(body: bytes, content_type: str, url: str, dni: str) -> tuple[list[dict], str]:
    media = content_type.split(';', 1)[0].lower()
    suffix = Path(urlsplit(url).path).suffix.lower()
    if media == 'application/pdf' or suffix == '.pdf' or body.startswith(b'%PDF-'):
        if not shutil.which('pdftotext'):
            return [], 'pdf_reader_unavailable'
        with tempfile.TemporaryDirectory(prefix='person-map-dni-') as directory:
            source = Path(directory) / 'source.pdf'
            result = Path(directory) / 'text.txt'
            source.write_bytes(body)
            try:
                subprocess.run(['pdftotext', '-f', '1', '-l', '30', '-layout', str(source), str(result)],
                               timeout=5, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if result.stat().st_size > 1000000:
                    return [], 'text_too_large'
                return _text_matches(result.read_text(errors='replace'), dni), 'pdf'
            except (subprocess.SubprocessError, OSError):
                return [], 'pdf_parse_error'
    text = body.decode('utf-8-sig', errors='replace')
    if media == 'application/json' or suffix == '.json':
        try:
            data = json.loads(text)
            rows = data if isinstance(data, list) else data.get('records', data.get('data', [])) if isinstance(data, dict) else []
            return _records(rows if isinstance(rows, list) else [], dni), 'json'
        except ValueError:
            return [], 'invalid_json'
    if media in {'text/csv', 'application/csv'} or suffix == '.csv':
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
            return _records(csv.DictReader(io.StringIO(text), dialect=dialect), dni), 'csv'
        except csv.Error:
            return [], 'invalid_csv'
    if media in {'text/html', 'application/xhtml+xml'} or suffix in {'.html', '.htm'}:
        soup = BeautifulSoup(text, 'html.parser')
        for tag in soup(['script', 'style', 'noscript']):
            tag.decompose()
        records = []
        for table_index, table in enumerate(soup.find_all('table')[:20], 1):
            rows = table.find_all('tr')[:20001]
            if not rows:
                continue
            headers = [cell.get_text(' ', strip=True) for cell in rows[0].find_all(['th', 'td'])]
            observed = _records((dict(zip(headers, [c.get_text(' ', strip=True) for c in row.find_all(['td', 'th'])])) for row in rows[1:]), dni)
            for record in observed:
                record['record_index'] = f"table-{table_index}-row-{record['record_index']}"
            records.extend(observed)
        return records[:3] or _text_matches(soup.get_text('\n', strip=True), dni), 'html'
    if media == 'text/plain' or suffix == '.txt':
        return _text_matches(text, dni), 'text'
    return [], 'unsupported_format'
