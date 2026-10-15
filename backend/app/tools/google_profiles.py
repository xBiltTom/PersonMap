"""Public Google profile observations, separated from target ownership."""
import json
import re
from urllib.parse import parse_qs, urlsplit, urljoin

from bs4 import BeautifulSoup

from app.tools.dni_public import public_source_url


def youtube_initial_data(soup):
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        match = re.search(r'(?:var\s+ytInitialData\s*=|window\["ytInitialData"\]\s*=)\s*', text)
        if match:
            try:
                value, _ = json.JSONDecoder().raw_decode(text[match.end():])
                if isinstance(value, dict):
                    return value
            except ValueError:
                pass
    return None


def youtube_metadata(soup):
    data = youtube_initial_data(soup)
    container = data.get("metadata") if data else None
    metadata = container.get("channelMetadataRenderer") if isinstance(container, dict) else None
    if not isinstance(metadata, dict) or not re.fullmatch(r"UC[A-Za-z0-9_-]{22}", str(metadata.get("externalId", ""))):
        return None
    return metadata


def scholar_url(raw):
    if not isinstance(raw, str):
        return None
    try:
        url = urlsplit(raw)
        query = parse_qs(url.query)
        ids = query.get("user", [])
        if (url.scheme != "https" or url.hostname != "scholar.google.com" or url.path != "/citations"
                or url.username or url.password or url.port not in {None, 443} or len(ids) != 1
                or not re.fullmatch(r"[A-Za-z0-9_-]{6,30}", ids[0])
                or "citation_for_view" in query or query.get("view_op", [""])[0] not in {"", "list_works"}):
            return None
        return "https://scholar.google.com/citations?user=" + ids[0]
    except ValueError:
        return None


def observe_scholar(body, requested):
    soup = BeautifulSoup(body, "html.parser")
    title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    if any(word in title for word in ("captcha", "sorry", "access denied", "sign in", "iniciar sesión")):
        return {"status": "blocked"}
    name = soup.select_one("#gsc_prf_in")
    if name is None or not name.get_text(" ", strip=True):
        return {"status": "unexpected_response"}
    canonical = soup.find("link", rel="canonical")
    if canonical and scholar_url(urljoin(requested, canonical.get("href", ""))) != scholar_url(requested):
        return {"status": "identity_mismatch"}
    affiliations, domain = [], None
    for item in soup.select("#gsc_prf_i .gsc_prf_il"):
        value = item.get_text(" ", strip=True)
        email = re.search(r"(?:verified email at|correo verificado de|correo verificado en)\s+([A-Za-z0-9.-]+)", value, re.I)
        if email:
            domain = email[1].rstrip(".")
        elif value and not item.select("a.gsc_prf_inta") and "no verified email" not in value.lower():
            affiliations.append(value[:500])
    metrics = {}
    for row in soup.select("#gsc_rsb_st tr"):
        cells = row.select("td")
        if len(cells) < 2:
            continue
        field = {"citations": "citations", "citas": "citations", "h-index": "h_index", "i10-index": "i10_index"}.get(cells[0].get_text(" ", strip=True).lower())
        number = cells[1].get_text(strip=True).replace(",", "").replace(".", "").replace("\xa0", "")
        if field and number.isdigit():
            metrics[field] = int(number)
    links = []
    for anchor in soup.select("#gsc_prf_i a[href]"):
        link = public_source_url(anchor.get("href", ""))
        if link and urlsplit(link).hostname in {"orcid.org", "www.orcid.org"}:
            from app.schemas.identifiers import TypedIdentifier
            try:
                identifier = TypedIdentifier(value=urlsplit(link).path.strip("/"), id_type="orcid")
                canonical = "https://orcid.org/" + identifier.value
                if canonical not in links:
                    links.append(canonical)
            except ValueError:
                pass
    return {"status": "observed", "author_name": name.get_text(" ", strip=True)[:500],
            "institutions": affiliations[:5], "verified_email_domain": domain,
            "linked_profiles": links[:5], **metrics}
