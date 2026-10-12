"""Public scholarly records, linked through explicit OpenAlex author identifiers."""
import re

import httpx

from app.core.config import settings
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.dni_public import public_source_url
from app.tools.search_dorker import _normalize, name_search_variants

HEADERS = {"User-Agent": "PersonMap/1.0 (public academic footprint research)", "Accept": "application/json"}


class AcademicFinderTool(BaseTool):
    name = "academic_finder"
    description = "Busca autores candidatos en OpenAlex y recupera sus publicaciones por ID documentado, con ORCID y enlaces de acceso abierto. Un homónimo no prueba identidad."
    category = ToolCategory.ACADEMIC
    required_inputs = ["full_name"]
    cache_prefix = "academic_"

    def _names(self, context):
        return list(dict.fromkeys(name.strip() for name in [context.full_name, *context.discovered_names]
                                  if isinstance(name, str) and name.strip()))[:3]

    def can_run(self, context):
        checked = context.extra.get("academic_checked_names", [])
        return any(name not in checked for name in self._names(context))

    async def _records(self, client, endpoint, params, diagnostics):
        if settings.openalex_api_key:
            params = {**params, "api_key": settings.openalex_api_key.get_secret_value()}
        try:
            response = await http_client.get(client, f"https://api.openalex.org/{endpoint}", params=params)
            if response is None or response.status_code != 200:
                diagnostics.append({"endpoint": endpoint, "status": f"http_{response.status_code}" if response is not None else "request_error"})
                return []
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                diagnostics.append({"endpoint": endpoint, "status": "invalid_payload"})
                return []
            diagnostics.append({"endpoint": endpoint, "status": "ok", "received": len(data["results"])})
            return [row for row in data["results"] if isinstance(row, dict)]
        except (httpx.HTTPError, ValueError, TypeError):
            diagnostics.append({"endpoint": endpoint, "status": "request_error"})
            return []

    async def execute(self, context: TargetContext) -> list[ToolFinding]:
        checked = context.extra.setdefault("academic_checked_names", [])
        diagnostics = context.extra.setdefault("academic_diagnostics", [])
        findings, seen = [], set()
        async with http_client.build_client(timeout=10, rotate_ua=False, max_retries=0,
                                            follow_redirects=False, headers=HEADERS) as client:
            for name in self._names(context):
                if name in checked:
                    continue
                checked.append(name)
                candidates = await self._records(client, "authors", {"search": name, "per_page": 10}, diagnostics)
                names = {_normalize(variant) for variant in name_search_variants(name)}
                authors = {}
                for author in candidates:
                    label = author.get("display_name")
                    identifier = author.get("id")
                    if not isinstance(label, str) or _normalize(label) not in names:
                        continue
                    if not isinstance(identifier, str) or not re.fullmatch(r"https://openalex\.org/A[0-9]+", identifier):
                        continue
                    institutions = []
                    for affiliation in author.get("affiliations") or []:
                        institution = affiliation.get("institution") if isinstance(affiliation, dict) else None
                        if isinstance(institution, dict) and isinstance(institution.get("display_name"), str):
                            institutions.append(institution["display_name"])
                    orcid = public_source_url(author.get("orcid"))
                    authors[identifier] = label
                    if identifier not in seen:
                        seen.add(identifier)
                        findings.append(ToolFinding(entity_type="academic", platform="openalex_author", value=identifier,
                            display_name=label, evidence_urls=[identifier], metadata_info={
                                "author_name": label, "query_name": name, "institutions": list(dict.fromkeys(institutions)),
                                "orcid": orcid, "linked_profiles": [orcid] if orcid else [],
                                "works_count": author.get("works_count"), "citations_count": author.get("cited_by_count"),
                                "profile_url": identifier, "ownership_status": "unverified",
                                "name_match": "full_name_variant", "source_tool": self.name}))
                    if len(authors) >= 3:
                        break
                if not authors:
                    continue
                works = await self._records(client, "works", {
                    "filter": "author.id:" + "|".join(identifier.rsplit("/", 1)[-1] for identifier in authors),
                    "per_page": 10}, diagnostics)
                for work in works:
                    identifier = work.get("id")
                    if not isinstance(identifier, str) or not re.fullmatch(r"https://openalex\.org/W[0-9]+", identifier) or identifier in seen:
                        continue
                    matched = [item["author"]["id"] for item in (work.get("authorships") or [])
                               if isinstance(item, dict) and isinstance(item.get("author"), dict) and item["author"].get("id") in authors]
                    if not matched:
                        continue
                    links, pdfs = [], []
                    locations = work.get("locations")
                    locations = locations if isinstance(locations, list) else []
                    for location in [work.get("primary_location"), work.get("best_oa_location"), *locations[:10]]:
                        if not isinstance(location, dict):
                            continue
                        link = public_source_url(location.get("landing_page_url"))
                        pdf = public_source_url(location.get("pdf_url")) if location.get("is_oa") else None
                        if link and link not in links:
                            links.append(link)
                        if pdf and pdf not in pdfs:
                            pdfs.append(pdf)
                    seen.add(identifier)
                    doi = public_source_url(work.get("doi"))
                    findings.append(ToolFinding(entity_type="academic", platform="research_paper", value=doi or identifier,
                        display_name=str(work.get("title") or "Sin título")[:200],
                        evidence_urls=list(dict.fromkeys([identifier, *links, *pdfs])), metadata_info={
                            "title": work.get("title"), "doi": doi, "openalex_id": identifier,
                            "publication_year": work.get("publication_year"), "work_type": work.get("type"),
                            "url": next(iter(links), identifier), "open_access_urls": pdfs,
                            "matched_author_ids": matched, "matched_author_names": [authors[key] for key in matched],
                            "ownership_status": "unverified", "authorship_evidence": "openalex_author_id",
                            "source_tool": self.name}))
        return findings
