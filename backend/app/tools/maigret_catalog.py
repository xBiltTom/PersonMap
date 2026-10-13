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

from app.core.config import settings
from app.tools.dataset_adapter import (
    SiteCheck, KNOWN_STALE_CHECKS, NO_RANK, SENSITIVE_TAGS,
    _as_tuple, _platform_key, load_whatsmyname, _sort_key,
)


def database_path():
    return distribution("maigret").locate_file("maigret/resources/data.json")


@lru_cache(maxsize=1)
def database_info():
    content = database_path().read_bytes()
    return {"maigret_version": distribution("maigret").version,
            "maigret_catalog_sha256": hashlib.sha256(content).hexdigest()}


@lru_cache(maxsize=1)
def database_document():
    return json.loads(database_path().read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def native_recipes():
    data = database_document()
    recipes = {}
    for name, raw in data["sites"].items():
        merged = dict(data.get("engines", {}).get(raw.get("engine"), {}).get("site", {}))
        merged.update(raw)
        if merged.get("disabled") or name in KNOWN_STALE_CHECKS:
            continue
        if merged.get("type", "username") != "username":
            continue
        # Tor/I2P need a configured gateway; DNS checks belong to domain_finder.
        if merged.get("protocol", ""):
            continue
        url = merged.get("url", "").replace("{urlMain}", merged.get("urlMain", "").rstrip("/"))
        url = url.replace("{urlSubpath}", merged.get("urlSubpath", ""))
        if name == "Disqus":
            # Upstream's API probe works, but its public display URL omits /by/.
            url = "https://disqus.com/by/{username}/"
        if not url.startswith(("https://", "http://")) or "{username}" not in url:
            continue
        tags = _as_tuple(merged.get("tags"))
        rank = merged.get("alexaRank") or NO_RANK
        recipes[name] = SiteCheck(
            name=name, url=url, check_type=merged.get("checkType", "status_code"),
            presence=_as_tuple(merged.get("presenseStrs")), absence=_as_tuple(merged.get("absenceStrs")),
            regex_check=merged.get("regexCheck"), rank=rank, tags=tags,
            category=tags[0] if tags else None, source="maigret", native_name=name,
            sensitive=bool(set(tags) & SENSITIVE_TAGS),
        )
    return recipes


def build_scan_catalog(limit=None, *, apply_filters=True):
    native = native_recipes()
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
    if not apply_filters:
        return catalog[:limit] if limit else catalog
    tags, excluded = set(settings.maigret_tags), set(settings.maigret_excluded_tags)
    names = {name.casefold() for name in settings.maigret_site_names}
    def effective_tags(site):
        # WMN-only entries use categories rather than Maigret tag arrays.
        values = set(site.tags) | ({site.category} if site.category else set())
        return values | SENSITIVE_TAGS if site.sensitive else values
    catalog = [site for site in catalog
               if (not tags or tags.intersection(effective_tags(site)))
               and not excluded.intersection(effective_tags(site))
               and (not names or site.name.casefold() in names)]
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
    return build_scan_catalog(apply_filters=False)
