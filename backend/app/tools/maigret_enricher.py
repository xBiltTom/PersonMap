"""Maigret's URL extraction and typed recursive searches within shared budgets."""
import asyncio
import hashlib
import json
import secrets
import string

from app.core.config import settings
from app.tools.base import BaseTool, TargetContext, ToolCategory
from app.tools.maigret_catalog import build_identifier_catalog, database_info, execution_config
from app.tools.maigret_ids import add_identifiers, identifier_values, identifiers_from_url, apply_url_identifiers
from app.tools.maigret_runner import run_maigret
from app.tools.username_finder import UsernameFinderTool


def identifier_control(site, identifier):
    value, kind = identifier["value"], identifier["id_type"]
    if kind == "orcid":
        digits = "".join(secrets.choice(string.digits) for _ in range(15))
        total = 0
        for digit in digits:
            total = (total + int(digit)) * 2
        checksum = (12 - total % 11) % 11
        raw = digits + ("X" if checksum == 10 else str(checksum))
        candidate = "-".join(raw[i:i+4] for i in range(0, 16, 4))
    elif kind == "steam_id":
        candidate = str(76561197960265728 + secrets.randbelow(2**32))
    else:
        candidate = "".join(secrets.choice(string.digits if ch.isdigit() else string.ascii_lowercase)
                            if ch.isalnum() else ch for ch in value)
    return candidate if candidate != value and site.accepts_username(candidate) else None


class MaigretEnricherTool(BaseTool):
    name = "maigret_enricher"
    description = ("Extrae datos y alias desde URLs públicas mediante Maigret y busca identificadores "
                   "tipados (ORCID, Steam, GAIA, VK, etc.) con controles negativos; no confirma propiedad")
    category = ToolCategory.SOCIAL
    required_inputs = ["candidate_urls", "identifiers"]

    @staticmethod
    def signature(context):
        return hashlib.sha256(json.dumps({**database_info(), **execution_config(),
            "options": context.extra.get("maigret_options", {}), "tags": settings.maigret_tags,
            "names": settings.maigret_site_names, "excluded": settings.maigret_excluded_tags,
            "version": 1}, sort_keys=True).encode()).hexdigest()

    def can_run(self, context: TargetContext):
        parsed = context.extra.get("maigret_enricher_parsed", [])
        attempted = context.extra.get("maigret_enricher_url_attempts", [])
        scanned = context.extra.get("maigret_enricher_scanned", [])
        if context.extra.get("maigret_enricher_catalog_id") not in {None, self.signature(context)}:
            parsed, scanned, attempted = [], [], []
        ids = identifier_values(context.extra.get("maigret_identifiers", []))
        pending_ids = any(item["id_type"] != "username" and item["id_type"] + ":" + item["value"] not in scanned for item in ids)
        return ((pending_ids and len(scanned) < settings.maigret_max_identifiers)
                or (len(attempted) < settings.maigret_max_parse_urls
                    and any(url not in parsed for url in context.extra.get("candidate_urls", []))))

    async def execute(self, context: TargetContext):
        helper = UsernameFinderTool()
        findings = []
        parsed = context.extra.setdefault("maigret_enricher_parsed", [])
        attempted = context.extra.setdefault("maigret_enricher_url_attempts", [])
        scanned = context.extra.setdefault("maigret_enricher_scanned", [])
        options = context.extra.get("maigret_options", {})
        signature = self.signature(context)
        if context.extra.get("maigret_enricher_catalog_id") not in {None, signature}:
            scanned.clear()
            parsed.clear()
            attempted.clear()
        context.extra["maigret_enricher_catalog_id"] = signature
        quota = asyncio.Semaphore(settings.tool_concurrency_budget(settings.username_scan_concurrency))
        diagnostics = context.extra.setdefault("maigret_enricher_diagnostics", {})
        urls = list(dict.fromkeys(context.extra.get("candidate_urls", [])))
        urls = [url for url in urls if url not in parsed][:max(0, settings.maigret_max_parse_urls - len(attempted))]

        async def extracted(result):
            url = result["url_user"]
            url_ids = identifiers_from_url(url)
            apply_url_identifiers(context, url, url_ids)
            response = helper._response(result)
            diagnostics[url] = {"status": "extracted" if result.get("ids_data") else "no_data",
                                "http_status": response.status_code if response else None,
                                "error": result.get("error")}
            if response is not None and response.status_code == 200 and result.get("ids_data"):
                synthetic = {**result, "status": "Claimed", "control": {}}
                # Extraction is evidence about page content; no existence or
                # ownership claim is manufactured from a matching URL template.
                site = type("ExtractionSite", (), {"name": "Maigret URL", "category": None,
                        "sensitive": False, "rank": 5_000_000, "protocol": "", "id_type": "username"})()
                finding = helper._native_finding(site, "", synthetic, {"control_rejected": 0})
                if finding:
                    finding.metadata_info.pop("username", None)
                    finding.metadata_info.update({"source_tool": self.name, "source_kind": "maigret_url_extraction",
                        "acquisition_scope": "page_content", "ownership_status": "unverified"})
                    finding.entity_type = "search_mention"
                    finding.display_name = "Datos extraídos por Maigret"
                    finding.confidence = 0.5
                    findings.append(finding)
                    add_identifiers(context, result.get("identifiers", result.get("ids_usernames", {})), url, self.name)
                    for link in result.get("ids_links", []):
                        add_identifiers(context, identifiers_from_url(link), url, self.name)
            if url not in parsed:
                parsed.append(url)
            if url not in attempted:
                attempted.append(url)

        if urls:
            await run_maigret("", [], {}, extracted, operation="extract", urls=urls,
                             request_semaphore=quota, options=options)
        identifiers = identifier_values(context.extra.get("maigret_identifiers", []))
        for item in identifiers:
            if item["id_type"] == "username":
                continue
            key = item["id_type"] + ":" + item["value"]
            if key in scanned or len(scanned) >= settings.maigret_max_identifiers:
                continue
            filters = {key: options[key] for key in ("tags", "names", "excluded") if key in options}
            sites = [site for site in build_identifier_catalog(item["id_type"], **filters) if site.accepts_username(item["value"])]
            by_name = {site.name: site for site in sites}
            stats = {"control_rejected": 0}
            async def collected(result):
                site = by_name[result["site"]]
                before = stats["control_rejected"]
                finding = helper._native_finding(site, item["value"], result, stats)
                diagnostics[key + ":" + site.name] = {"status": result["status"], "error": result.get("error"),
                    "http_status": result.get("http_status"), "control_rejected": stats["control_rejected"] > before}
                check = {"status": result["status"], "error": result.get("error"), "http_status": result.get("http_status"),
                         "url": result.get("url_user") or site.build_pretty_url(item["value"]), "id_type": item["id_type"]}
                if result["status"] == "Claimed" and finding is None:
                    check.update(status="Unknown", error="Detection rejected by profile or negative-control checks")
                context.extra.setdefault("maigret_enricher_checks", {}).setdefault(key, {})[site.name] = check
                if finding:
                    finding.metadata_info.pop("username", None)
                    finding.metadata_info.update({"source_tool": self.name, "queried_identifier": item,
                        "identifier_sources": context.extra.get("maigret_identifier_sources", {}).get(key, []),
                        "ownership_status": "unverified"})
                    findings.append(finding)
            if sites:
                await run_maigret(item["value"], sites, {site.name: identifier_control(site, item) for site in sites},
                                 collected, id_type=item["id_type"], request_semaphore=quota, options=options)
            scanned.append(key)
        return findings
