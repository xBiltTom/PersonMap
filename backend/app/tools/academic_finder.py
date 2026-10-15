"""Bounded OpenAlex/Crossref discovery with explicit author and DOI evidence."""
import asyncio
from collections import Counter
import hashlib
import json
import re
from urllib.parse import quote, unquote, urlsplit
from weakref import WeakKeyDictionary

import httpx

from app.core.config import settings
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.academic_metadata import (affiliation_match, crossref_authors, doi_url,
    first_text, matched_authors, merge_academic_findings, name_matches, openalex_authors, openalex_links,
    orcid_url, publication_year, rows, text)

ENGINE_VERSION = 3
HEADERS = {"User-Agent": "PersonMap/1.0 (public academic footprint research)", "Accept": "application/json"}
# Public Crossref requests: one at a time per event loop/process, at most 5/s.
# The shared transport also enforces the application's global/per-host budgets.
_CROSSREF_GATES = WeakKeyDictionary()
http_client.register_host_rate_limit("api.crossref.org", max_requests=5, per_seconds=1)


def capabilities():
    return {"engine_version": ENGINE_VERSION, "providers": ["openalex", *(["crossref"] if settings.crossref_enabled else [])],
        "max_names": max(0, min(3, settings.academic_max_names)),
        "max_orcids": max(0, min(3, settings.academic_max_orcids)),
        "max_dois": max(0, min(5, settings.academic_max_dois)),
        "max_requests": max(0, min(40, settings.academic_max_requests)),
        "results_per_query": max(1, min(20, settings.academic_results_per_query)),
        "request_timeout": max(1, min(20, settings.academic_request_timeout)),
        "batch_timeout": max(1, min(120, settings.academic_batch_timeout)),
        "openalex_key_configured": bool(settings.openalex_api_key),
        "crossref_contact_configured": bool(settings.crossref_mailto),
        "identity_policy": "candidate_authorship_not_target_ownership"}


def config_id():
    return hashlib.sha256(json.dumps(capabilities(), sort_keys=True).encode()).hexdigest()


def execution_summary(context):
    return {"engine_version": ENGINE_VERSION, "config_id": config_id(),
        "requests": context.extra.get("academic_requests", 0),
        "counts": dict(Counter(item["status"] for item in context.extra.get("academic_diagnostics", []))),
        "queries": len(context.extra.get("academic_queries", {})),
        "disabled_providers": list(context.extra.get("academic_disabled_providers", []))}


def select_call_inputs(context, inputs):
    """An explicit MCP/agent subsearch does not expand to every inherited pivot."""
    if inputs.get("full_name") or inputs.get("identifiers") or inputs.get("candidate_urls"):
        selected = TargetContext(full_name=inputs.get("full_name"), extra={
            "maigret_identifiers": inputs.get("identifiers", []), "candidate_urls": inputs.get("candidate_urls", [])})
        context.extra["academic_selection"] = AcademicFinderTool()._inputs(selected)


class AcademicFinderTool(BaseTool):
    name = "academic_finder"
    description = ("Busca publicaciones en Crossref y autores/trabajos en OpenAlex por nombre completo, ORCID o URLs DOI. "
        "Contrasta el autor de cada obra, conserva afiliaciones y procedencia y unifica por DOI. "
        "Los homónimos son candidatos; una publicación no confirma identidad.")
    category = ToolCategory.ACADEMIC
    required_inputs = ["full_name", "identifiers", "candidate_urls"]
    cache_prefix = "academic_"

    @staticmethod
    def capabilities():
        return capabilities()

    def _inputs(self, context):
        if isinstance(context.extra.get("academic_selection"), dict):
            return context.extra["academic_selection"]
        names = list(dict.fromkeys(value.strip() for value in [context.full_name, *context.discovered_names]
            if isinstance(value, str) and len(value.split()) >= 2))
        orcids = []
        for item in context.extra.get("maigret_identifiers", []):
            value = orcid_url(item.get("value")) if isinstance(item, dict) and item.get("id_type") == "orcid" else None
            if value and value not in orcids:
                orcids.append(value)
        dois = []
        for raw in context.extra.get("candidate_urls", [])[:100]:
            orcid, doi = orcid_url(raw), doi_url(raw)
            if orcid and orcid not in orcids:
                orcids.append(orcid)
            if doi and doi not in dois:
                dois.append(doi)
        return {"doi": dois, "orcid": orcids, "name": names}

    def _pending(self, context):
        current = context.extra.get("academic_config_id") == config_id()
        checked = context.extra.get("academic_queries", {}) if current else {}
        config = capabilities()
        if current and context.extra.get("academic_requests", 0) >= config["max_requests"]:
            return []
        if current and set(config["providers"]) <= set(context.extra.get("academic_disabled_providers", [])):
            return []
        pending = []
        for kind, values in self._inputs(context).items():
            limit = config[{"name": "max_names", "orcid": "max_orcids", "doi": "max_dois"}[kind]]
            used = sum(item["kind"] == kind for item in checked.values())
            for value in values:
                key = json.dumps([kind, value, context.university if kind == "name" else None], ensure_ascii=False)
                if key not in checked and used < limit:
                    pending.append((key, kind, value))
                    used += 1
        return pending if config["max_requests"] else []

    def can_run(self, context):
        return bool(self._pending(context))

    def _record(self, context, provider, endpoint, status, **details):
        context.extra.setdefault("academic_diagnostics", []).append({
            "provider": provider, "endpoint": endpoint, "status": status, **details})

    async def _request(self, client, provider, endpoint, params, context, *, single=False):
        config = capabilities()
        if provider not in config["providers"] or provider in context.extra["academic_disabled_providers"]:
            return None
        if context.extra["academic_requests"] >= config["max_requests"]:
            self._record(context, provider, "works" if single else endpoint, "budget_exhausted")
            return None
        context.extra["academic_requests"] += 1
        request_params = dict(params)
        if provider == "openalex" and settings.openalex_api_key:
            request_params["api_key"] = settings.openalex_api_key.get_secret_value()
        if provider == "crossref" and settings.crossref_mailto:
            # A configured operator contact; never the target or an inferred address.
            request_params["mailto"] = settings.crossref_mailto
        safe_endpoint = "works" if single else endpoint
        async def fetch():
            return await client.get(f"https://api.{provider}.org/{endpoint}", params=request_params)
        try:
            async with asyncio.timeout(config["request_timeout"]):
                if provider == "crossref":
                    gate = _CROSSREF_GATES.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(1))
                    async with gate:
                        response = await fetch()
                else:
                    response = await fetch()
            code = response.status_code
            if code != 200:
                status = "rate_limited" if code == 429 else "blocked" if code in {401, 403} else "not_found" if code in {404, 410} else "redirected" if 300 <= code < 400 else "upstream_error"
                self._record(context, provider, safe_endpoint, status, http_status=code)
                if code in {401, 403, 429}:
                    context.extra["academic_disabled_providers"].append(provider)
                return None
            data = response.json()
            if provider == "crossref":
                data = data.get("message") if isinstance(data, dict) and data.get("status") == "ok" else None
                records = [data] if single and isinstance(data, dict) else data.get("items") if isinstance(data, dict) else None
            else:
                records = data.get("results") if isinstance(data, dict) else None
            if not isinstance(records, list):
                self._record(context, provider, safe_endpoint, "invalid_payload")
                return None
            records = rows(records, config["results_per_query"])
            self._record(context, provider, safe_endpoint, "ok" if records else "no_results", received=len(records), http_status=code)
            return records
        except (httpx.HTTPError, ValueError, TypeError, TimeoutError) as exc:
            self._record(context, provider, safe_endpoint, "timeout" if isinstance(exc, TimeoutError) else "request_error", error_type=type(exc).__name__)
            return None

    async def execute(self, context: TargetContext):
        if context.extra.get("academic_config_id") != config_id():
            for key in list(context.extra):
                if key.startswith(self.cache_prefix) and key != "academic_selection":
                    context.extra.pop(key)
            context.extra.update(academic_config_id=config_id(), academic_queries={}, academic_requests=0,
                academic_checked_names=[], academic_diagnostics=[], academic_disabled_providers=[])
        pending = self._pending(context)
        findings = []
        current = None
        async with http_client.build_client(timeout=capabilities()["request_timeout"], rotate_ua=False, max_retries=0,
                public_only=True, follow_redirects=False, trust_env=False, headers=HEADERS) as client:
            try:
                async with asyncio.timeout(capabilities()["batch_timeout"]):
                    for key, kind, value in pending:
                        if context.extra["academic_requests"] >= capabilities()["max_requests"]:
                            break
                        current = {"kind": kind, "value": value, "status": "running"}
                        context.extra["academic_queries"][key] = current
                        if kind == "name":
                            context.extra["academic_checked_names"].append(value)
                            await self._name(client, value, context, findings)
                        elif kind == "orcid":
                            await self._orcid(client, value, context, findings)
                        else:
                            await self._doi(client, value, context, findings)
                        current["status"] = "attempted"
            except TimeoutError:
                if current:
                    current["status"] = "budget_exhausted"
                self._record(context, "batch", "batch", "budget_exhausted")
        return merge_academic_findings(findings)

    def _profile(self, author, context, findings, *, name=None, orcid=None):
        identifier, label = author.get("id"), text(author.get("display_name"))
        observed_orcid = orcid_url(author.get("orcid"))
        if (not isinstance(identifier, str) or not re.fullmatch(r"https://openalex\.org/A[0-9]+", identifier)
                or not label or (orcid and observed_orcid != orcid) or (name and not name_matches(label, name))):
            return None
        institutions = [text(item["institution"].get("display_name")) for item in rows(author.get("affiliations"))
            if isinstance(item.get("institution"), dict) and text(item["institution"].get("display_name"))]
        institutions = list(dict.fromkeys(institutions))[:10]
        findings.append(ToolFinding(entity_type="academic", platform="openalex_author", value=identifier,
            display_name=label, confidence=0.5, evidence_urls=[identifier], metadata_info={
                "author_name": label, "query_name": name, "institutions": institutions,
                "affiliation_match": affiliation_match(institutions, context.university),
                "orcid": observed_orcid, "linked_profiles": [observed_orcid] if observed_orcid else [],
                "works_count": author.get("works_count") if type(author.get("works_count")) is int else None,
                "citations_count": author.get("cited_by_count") if type(author.get("cited_by_count")) is int else None,
                "profile_url": identifier, "ownership_status": "unverified", "academic_sources": ["openalex"],
                "name_match": "full_name_variant" if name else None, "match_basis": "orcid" if orcid else "full_name_variant",
                "source_tool": self.name}))
        return identifier

    def _paper(self, provider, work, context, findings, *, name=None, orcid=None, author_ids=(), expected_doi=None):
        doi = doi_url(work.get("DOI") if provider == "crossref" else work.get("doi"))
        identifier = work.get("id") if provider == "openalex" else None
        if provider == "openalex" and (not isinstance(identifier, str) or not re.fullmatch(r"https://openalex\.org/W[0-9]+", identifier)):
            return False
        if (provider == "crossref" and not doi) or (expected_doi and doi != expected_doi):
            return False
        title = first_text(work.get("title"))
        if not title:
            return False
        authors = crossref_authors(work) if provider == "crossref" else openalex_authors(work)
        matched = matched_authors(authors, name=name, orcid=orcid, author_ids=author_ids)
        # Some OpenAlex authorship entries omit their ORCID; a previously checked
        # author ID supports that relationship, but a contradictory ORCID does not.
        if orcid and author_ids:
            matched = [a for a in authors if a.get("openalex_id") in author_ids and a.get("orcid") in {None, orcid}]
        if not expected_doi and not matched:
            return False
        links, pdfs = openalex_links(work) if provider == "openalex" else ([], [])
        source = identifier if provider == "openalex" else "https://api.crossref.org/works/" + quote(unquote(urlsplit(doi).path.lstrip("/")), safe="/")
        institutions = list(dict.fromkeys(inst for author in matched for inst in author["institutions"]))
        matched_orcids = list(dict.fromkeys(a["orcid"] for a in matched if a.get("orcid")))
        basis = "explicit_doi" if expected_doi else "orcid" if orcid else "openalex_author_id" if author_ids else "full_name_variant"
        citations = work.get("cited_by_count" if provider == "openalex" else "is-referenced-by-count")
        record = {"provider": provider, "source_url": source, "title": title, "authors": authors,
            "matched_authors": matched, "match_basis": basis, "affiliation_match": affiliation_match(institutions, context.university)}
        metadata = {"title": title, "doi": doi, "openalex_id": identifier,
            "publication_year": work.get("publication_year") if provider == "openalex" else publication_year(work),
            "work_type": text(work.get("type")), "url": doi or identifier, "open_access_urls": pdfs,
            "academic_sources": [provider], "academic_records": [record], "authors": authors,
            "matched_author_ids": [a["openalex_id"] for a in matched if a.get("openalex_id")],
            "matched_author_names": [a["name"] for a in matched if a["name"]],
            "institutions": institutions, "affiliation_match": record["affiliation_match"],
            "linked_profiles": matched_orcids, "ownership_status": "unverified",
            "authorship_evidence": basis, "target_association_status": "unverified" if matched else "not_asserted",
            "source_dependency": "crossref_openalex_metadata_overlap", "independent_identity_confirmations": 0,
            "source_tool": self.name}
        if type(citations) is int and citations >= 0:
            metadata["citation_counts"] = {provider: citations}
        if provider == "openalex" and type(work.get("is_retracted")) is bool:
            metadata["openalex_is_retracted"] = work["is_retracted"]
        if provider == "crossref":
            metadata["publisher"] = text(work.get("publisher"))
            metadata["venue"] = first_text(work.get("container-title"))
            metadata["full_text_links"] = list(dict.fromkeys(url for item in rows(work.get("link"), 5)
                if (url := public_url(item.get("URL")))))
            metadata["publication_updates"] = [{"doi": doi_url(item.get("DOI")), "type": text(item.get("type"))}
                for item in rows(work.get("update-to"), 5) if doi_url(item.get("DOI"))]
        findings.append(ToolFinding(entity_type="academic", platform="research_paper", value=doi or identifier,
            display_name=title[:200], confidence=0.6 if matched else 0.4,
            evidence_urls=list(dict.fromkeys([source, *links, *pdfs])), metadata_info=metadata))
        return True

    async def _name(self, client, name, context, findings):
        params = {"query.author": name, "rows": capabilities()["results_per_query"]}
        if context.university:
            params["query.affiliation"] = context.university
        records = await self._request(client, "crossref", "works", params, context)
        accepted = sum(self._paper("crossref", work, context, findings, name=name) for work in records or [])
        if not accepted and context.university and records is not None:
            params.pop("query.affiliation")
            records = await self._request(client, "crossref", "works", params, context)
            for work in records or []:
                self._paper("crossref", work, context, findings, name=name)
        candidates = await self._request(client, "openalex", "authors", {"search": name, "per_page": capabilities()["results_per_query"]}, context)
        authors = []
        for author in candidates or []:
            identifier = self._profile(author, context, findings, name=name)
            if identifier and identifier not in authors:
                authors.append(identifier)
            if len(authors) >= 3:
                break
        await self._author_works(client, authors, context, findings)

    async def _orcid(self, client, orcid, context, findings):
        records = await self._request(client, "crossref", "works", {"filter": "orcid:" + orcid.rsplit("/", 1)[-1],
            "rows": capabilities()["results_per_query"]}, context)
        for work in records or []:
            self._paper("crossref", work, context, findings, orcid=orcid)
        candidates = await self._request(client, "openalex", "authors", {"filter": "orcid:" + orcid,
            "per_page": capabilities()["results_per_query"]}, context)
        authors = []
        for author in candidates or []:
            identifier = self._profile(author, context, findings, orcid=orcid)
            if identifier and identifier not in authors:
                authors.append(identifier)
            if len(authors) >= 3:
                break
        await self._author_works(client, authors, context, findings, orcid=orcid)

    async def _author_works(self, client, authors, context, findings, *, orcid=None):
        if not authors:
            return
        records = await self._request(client, "openalex", "works", {"filter": "author.id:" + "|".join(identifier.rsplit("/", 1)[-1] for identifier in authors),
            "per_page": capabilities()["results_per_query"]}, context)
        for work in records or []:
            self._paper("openalex", work, context, findings, author_ids=authors, orcid=orcid)

    async def _doi(self, client, doi, context, findings):
        endpoint = "works/" + quote(unquote(urlsplit(doi).path.lstrip("/")), safe="/")
        records = await self._request(client, "crossref", endpoint, {}, context, single=True)
        for work in records or []:
            self._paper("crossref", work, context, findings, expected_doi=doi)
        records = await self._request(client, "openalex", "works", {"filter": "doi:" + doi,
            "per_page": capabilities()["results_per_query"]}, context)
        for work in records or []:
            self._paper("openalex", work, context, findings, expected_doi=doi)


def public_url(raw):
    from app.tools.dni_public import public_source_url
    return public_source_url(raw)
