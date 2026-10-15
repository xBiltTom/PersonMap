"""Academic identifiers and author evidence; publication existence is not identity."""
import re
from urllib.parse import quote, unquote, urlsplit

from app.schemas.identifiers import TypedIdentifier
from app.tools.dni_public import public_source_url
from app.tools.search_dorker import _normalize, name_search_variants


def doi_url(raw):
    if not isinstance(raw, str) or len(raw) > 2048:
        return None
    value = raw.strip()
    if value.lower().startswith(("http://", "https://")):
        try:
            parsed = urlsplit(value)
            if (parsed.hostname not in {"doi.org", "dx.doi.org"} or parsed.username or parsed.password
                    or parsed.port not in {None, 80, 443}):
                return None
            value = unquote(parsed.path.lstrip("/"))
        except ValueError:
            return None
    elif value.lower().startswith("doi:"):
        value = value[4:].strip()
    if (not re.fullmatch(r"10\.[0-9]{4,9}/\S+", value, re.I)
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in {".", ".."} for part in value.split("/"))):
        return None
    return "https://doi.org/" + quote(value.lower(), safe="/:;()._-")


def orcid_url(raw):
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if value.lower().startswith(("http://", "https://")):
        try:
            parsed = urlsplit(value)
            if (parsed.hostname not in {"orcid.org", "www.orcid.org"} or parsed.username or parsed.password
                    or parsed.port not in {None, 80, 443} or parsed.query or parsed.fragment):
                return None
            value = parsed.path.strip("/")
        except ValueError:
            return None
    try:
        return "https://orcid.org/" + TypedIdentifier(value=value, id_type="orcid").value
    except ValueError:
        return None


def rows(value, limit=100):
    return [item for item in value[:limit] if isinstance(item, dict)] if isinstance(value, list) else []


def text(value, limit=500):
    return value.strip()[:limit] if isinstance(value, str) else ""


def first_text(value):
    return next((text(item) for item in value if text(item)), "") if isinstance(value, list) else text(value)


def name_key(value):
    return re.sub(r"[^\w\s]", " ", _normalize(value)).replace("_", " ").split()


def name_matches(observed, query):
    # Never expand initials or accept a substring of a longer person's name.
    return len(name_key(query)) >= 2 and name_key(observed) in [name_key(value) for value in name_search_variants(query)]


def affiliation_match(institutions, requested):
    if not requested or not institutions:
        return None
    wanted = " ".join(name_key(requested))
    return bool(wanted) and any(" " + wanted + " " in " " + " ".join(name_key(value)) + " " for value in institutions)


def crossref_authors(work):
    result = []
    for author in rows(work.get("author")):
        given, family = text(author.get("given")), text(author.get("family"))
        name = text(" ".join(part for part in (given, family) if part)) or text(author.get("name"))
        institutions = [text(item.get("name")) for item in rows(author.get("affiliation")) if text(item.get("name"))]
        result.append({"name": name, "family_first": " ".join(part for part in (family, given) if part),
            "orcid": orcid_url(author.get("ORCID")), "institutions": list(dict.fromkeys(institutions))[:5],
            "authenticated_orcid": author.get("authenticated-orcid") is True})
    return result


def openalex_authors(work):
    result = []
    for item in rows(work.get("authorships")):
        author = item.get("author")
        if not isinstance(author, dict):
            continue
        identifier = author.get("id")
        result.append({"name": text(author.get("display_name")), "orcid": orcid_url(author.get("orcid")),
            "openalex_id": identifier if isinstance(identifier, str) and re.fullmatch(r"https://openalex\.org/A[0-9]+", identifier) else None,
            "institutions": [text(inst.get("display_name")) for inst in rows(item.get("institutions")) if text(inst.get("display_name"))][:5]})
    return result


def matched_authors(authors, *, name=None, orcid=None, author_ids=()):
    if orcid:
        return [author for author in authors if author.get("orcid") == orcid]
    if author_ids:
        return [author for author in authors if author.get("openalex_id") in author_ids]
    return [author for author in authors if name and (name_matches(author["name"], name) or name_matches(author.get("family_first", ""), name))]


def openalex_links(work):
    links, pdfs = [], []
    for location in [work.get("primary_location"), work.get("best_oa_location"), *rows(work.get("locations"), 10)]:
        if not isinstance(location, dict):
            continue
        for field, target in (("landing_page_url", links), ("pdf_url", pdfs)):
            url = public_source_url(location.get(field))
            if url and (field != "pdf_url" or location.get("is_oa") is True) and url not in target:
                target.append(url)
    return links, pdfs


def publication_year(work):
    for field in ("published", "published-print", "published-online", "issued"):
        value = work.get(field)
        parts = value.get("date-parts") if isinstance(value, dict) else None
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            year = parts[0][0]
            if type(year) is int and 1000 <= year <= 3000:
                return year
    return None


def preserve_author_association(metadata):
    """A later DOI-only lookup must not erase previously observed author evidence."""
    priority = {"orcid": 3, "openalex_author_id": 2, "full_name_variant": 1, "explicit_doi": 0}
    records = [record for record in rows(metadata.get("academic_records"))
        if isinstance(record.get("match_basis"), str) and record["match_basis"] in priority]
    if not records:
        return
    matched = [record for record in records if rows(record.get("matched_authors"))]
    metadata["target_association_status"] = "unverified" if matched else "not_asserted"
    strongest = max(matched or records, key=lambda record: priority.get(record.get("match_basis"), -1))
    basis = strongest.get("match_basis")
    metadata["authorship_evidence"] = basis if basis in priority else "unknown"
    flags = [record.get("affiliation_match") for record in matched]
    metadata["affiliation_match"] = True if True in flags else False if False in flags else None


def merge_academic_findings(findings):
    """Merge provider observations without importing or initializing an engine."""
    result = {}
    for finding in findings:
        key = (finding.platform, doi_url(finding.value) or finding.value)
        prior = result.get(key)
        if prior is None:
            result[key] = finding
            continue
        for field, value in finding.metadata_info.items():
            old = prior.metadata_info.get(field)
            if isinstance(old, list) and isinstance(value, list):
                prior.metadata_info[field] = old + [item for item in value if item not in old]
            elif field == "citation_counts" and isinstance(old, dict) and isinstance(value, dict):
                prior.metadata_info[field] = {**old, **value}
            elif old is None or old == "":
                prior.metadata_info[field] = value
        prior.evidence_urls = list(dict.fromkeys([*prior.evidence_urls, *finding.evidence_urls]))
        prior.confidence = max(prior.confidence, finding.confidence)
    for finding in result.values():
        preserve_author_association(finding.metadata_info)
    return list(result.values())
