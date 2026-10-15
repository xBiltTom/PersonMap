"""Versioned upstream recipes and complementary WhatsMyName coverage.

Reading package resources through metadata avoids importing Maigret (and its
CLI dependencies) into the API process. Native objects live only in the worker.
The existing dataset_adapter remains available for old measurements.
"""
import hashlib
import json
from functools import lru_cache
from importlib.metadata import distribution
from dataclasses import replace
from pathlib import Path

from app.core.config import settings
from app.tools.dataset_adapter import (
    SiteCheck, KNOWN_STALE_CHECKS, NO_RANK, SENSITIVE_TAGS,
    _as_tuple, _platform_key, load_whatsmyname, _sort_key,
)


def database_path():
    if settings.maigret_database_file:
        return Path(settings.maigret_database_file).resolve()
    return distribution("maigret").locate_file("maigret/resources/data.json")


@lru_cache(maxsize=1)
def database_info():
    content = database_path().read_bytes()
    return {"maigret_version": distribution("maigret").version,
            "maigret_catalog_sha256": hashlib.sha256(content).hexdigest()}


@lru_cache(maxsize=1)
def database_document():
    return json.loads(database_path().read_text(encoding="utf-8"))


def execution_config():
    """Reproducible capabilities, without exposing credentials or file paths."""
    cookie_hash = None
    if settings.maigret_cookie_file:
        try:
            cookie_hash = hashlib.sha256(Path(settings.maigret_cookie_file).read_bytes()).hexdigest()
        except OSError:
            cookie_hash = "unreadable"
    transports = {key: getattr(settings, "maigret_" + key).get_secret_value() if getattr(settings, "maigret_" + key) else None
                  for key in ("proxy", "tor_proxy", "i2p_proxy")}
    transports["solver"] = settings.maigret_solver_url
    return {"maigret_parse": settings.maigret_parse, "maigret_enrich": settings.maigret_enrich,
            "maigret_retries": settings.maigret_retries, "maigret_keywords": settings.maigret_keywords,
            "maigret_check_domains": settings.maigret_check_domains,
            "maigret_cookie_sha256": cookie_hash,
            "maigret_transport_sha256": hashlib.sha256(json.dumps(transports, sort_keys=True).encode()).hexdigest(),
            "maigret_tor_configured": bool(settings.maigret_tor_proxy),
            "maigret_i2p_configured": bool(settings.maigret_i2p_proxy),
            "maigret_proxy_configured": bool(settings.maigret_proxy),
            "maigret_solver_configured": bool(settings.maigret_solver_url),
            "maigret_max_identifiers": settings.maigret_max_identifiers,
            "maigret_max_parse_urls": settings.maigret_max_parse_urls,
            "maigret_max_permutations": settings.maigret_max_permutations,
            "maigret_request_timeout": settings.maigret_request_timeout,
            "maigret_worker_timeout": settings.maigret_worker_timeout,
            "maigret_tool_timeout": settings.maigret_tool_timeout,
            "maigret_queue_grace": settings.maigret_queue_grace,
            "maigret_solver_timeout": settings.maigret_solver_timeout,
            "maigret_solver_concurrency": settings.maigret_solver_concurrency}


def capabilities():
    from collections import Counter
    from importlib.util import find_spec
    recipes = native_recipes(id_type=None, protocols=("", "tor", "i2p", "dns"))
    return {**database_info(), **execution_config(), "username_engine_version": 4, "enricher_version": 1,
            "identifier_types": dict(Counter(site.id_type for site in recipes.values())),
            "protocol_recipes": dict(Counter(site.protocol or "web" for site in recipes.values())),
            "catalogue_platforms": len(build_scan_catalog()),
            "catalogue_with_variants": len(build_scan_catalog(include_variants=True)),
            "scan_modes": ["fast", "deep", "all"],
            "report_formats": ["json", "ndjson", "csv", "txt", "markdown", "html", "xmind", "graph", "neo4j"] + (["pdf"] if find_spec("xhtml2pdf") else []),
            "pdf_extra_installed": bool(find_spec("xhtml2pdf")), "custom_catalogue": bool(settings.maigret_database_file)}


@lru_cache(maxsize=32)
def native_recipes(id_type="username", protocols=("",)):
    data = database_document()
    recipes = {}
    for name, raw in data["sites"].items():
        merged = dict(data.get("engines", {}).get(raw.get("engine"), {}).get("site", {}))
        merged.update(raw)
        if merged.get("disabled") or name in KNOWN_STALE_CHECKS:
            continue
        if id_type is not None and merged.get("type", "username") != id_type:
            continue
        # Tor/I2P need a configured gateway; DNS checks belong to domain_finder.
        if merged.get("protocol", "") not in protocols:
            continue
        url = merged.get("url", "").replace("{urlMain}", merged.get("urlMain", "").rstrip("/"))
        url = url.replace("{urlSubpath}", merged.get("urlSubpath", ""))
        if name == "Disqus":
            # Upstream's API probe works, but its public display URL omits /by/.
            url = "https://disqus.com/by/{username}/"
        if merged.get("protocol") == "dns":
            url = "https://" + url
        if not url.startswith(("https://", "http://")) or "{username}" not in url:
            continue
        tags = _as_tuple(merged.get("tags"))
        rank = merged.get("alexaRank") or NO_RANK
        probe = merged.get("urlProbe")
        if probe:
            probe = probe.replace("{urlMain}", merged.get("urlMain", "").rstrip("/"))
            probe = probe.replace("{urlSubpath}", merged.get("urlSubpath", ""))
        recipes[name] = SiteCheck(
            name=name, url=url, check_type=merged.get("checkType", "status_code"),
            presence=_as_tuple(merged.get("presenseStrs")), absence=_as_tuple(merged.get("absenceStrs")),
            regex_check=merged.get("regexCheck"), rank=rank, tags=tags,
            category=tags[0] if tags else None, source="maigret", native_name=name,
            sensitive=bool(set(tags) & SENSITIVE_TAGS),
            id_type=merged.get("type", "username"), protocol=merged.get("protocol", ""),
            probe_url=probe,
        )
    return recipes


def configured_protocols():
    return ("", *(["tor"] if settings.maigret_tor_proxy else []),
            *(["i2p"] if settings.maigret_i2p_proxy else []),
            *(["dns"] if settings.maigret_check_domains else []))


def filter_sites(sites, *, tags=None, names=None, excluded=None):
    tags = set(settings.maigret_tags if tags is None else tags)
    excluded = set(settings.maigret_excluded_tags if excluded is None else excluded)
    names = {name.casefold() for name in (settings.maigret_site_names if names is None else names)}
    def effective_tags(site):
        values = set(site.tags) | ({site.category} if site.category else set())
        return values | SENSITIVE_TAGS if site.sensitive else values
    return [site for site in sites if (not tags or tags.intersection(effective_tags(site)))
            and not excluded.intersection(effective_tags(site))
            and (not names or site.name.casefold() in names)]


def build_identifier_catalog(id_type, **filters):
    return filter_sites(sorted(native_recipes(id_type, configured_protocols()).values(),
                              key=lambda site: (site.rank, site.name.casefold())), **filters)


def build_scan_catalog(limit=None, *, apply_filters=True, include_variants=False, **filters):
    native = native_recipes(protocols=configured_protocols())
    # An explicitly selected recipe must survive host deduplication.
    selected_names = filters.get("names", settings.maigret_site_names)
    if apply_filters and selected_names:
        selected = {name.casefold() for name in selected_names}
        native = {name: site for name, site in native.items() if name.casefold() in selected}
    by_host = {}
    for site in sorted(native.values(), key=lambda s: (s.rank, s.name.casefold())):
        by_host.setdefault(_platform_key(site.url), site)
    catalog, used = [], set()
    # Preserve the priority of established platforms while using their complete
    # native recipe. WMN is consulted only when there is no native counterpart.
    for site in sorted(load_whatsmyname(), key=_sort_key):
        host = _platform_key(site.pretty_url or site.url)
        if host in used:
            continue
        twin = by_host.get(host)
        catalog.append(replace(twin, sensitive=twin.sensitive or site.sensitive) if twin else site)
        used.add(host)
    for site in sorted(native.values(), key=lambda s: (s.rank, s.name.casefold())):
        host = _platform_key(site.url)
        if host not in used:
            catalog.append(site)
            used.add(host)
    if include_variants:
        used_names = {site.name for site in catalog}
        catalog.extend(site for site in sorted(native.values(), key=lambda s: (s.rank, s.name.casefold()))
                       if site.name not in used_names)
    if not apply_filters:
        return catalog[:limit] if limit else catalog
    catalog = filter_sites(catalog, **filters)
    return catalog[:limit] if limit else catalog


def platform_hosts():
    # Filtering a scan must never make an excluded provider a personal domain.
    hosts = {_platform_key(site.pretty_url or site.url) for site in load_whatsmyname()}
    for raw in database_document()["sites"].values():
        url = raw.get("urlMain") or raw.get("url", "")
        if url.startswith(("http://", "https://")):
            hosts.add(_platform_key(url))
    return hosts


def build_profile_catalog():
    """URL verification is independent of the selected username scan filters."""
    public = sorted(native_recipes(id_type=None).values(), key=lambda site: site.id_type == "username")
    known = {site.name for site in public}
    return public + [site for site in load_whatsmyname() if site.name not in known]
