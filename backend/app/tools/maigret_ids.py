"""Bounded identifier pivots and exact catalogue URL matching, without importing Maigret."""
import re
from functools import lru_cache
from urllib.parse import unquote

from pydantic import ValidationError

from app.schemas.identifiers import PublicIdentifier
from app.tools.maigret_catalog import native_recipes
from app.tools.social_profiles import normalize_web_url, parse_social_profile, social_host, PROFILE_ROUTES


def identifier_values(raw):
    """Normalize upstream value->type maps and API arrays using one contract."""
    items = ([{"value": value, "id_type": kind} for value, kind in raw.items()]
             if isinstance(raw, dict) else raw if isinstance(raw, list) else [])
    result = []
    for item in items[:100]:
        if isinstance(item, dict) and isinstance(item.get("value"), int) and not isinstance(item["value"], bool):
            item = {**item, "value": str(item["value"])}
        try:
            value = PublicIdentifier.model_validate(item).model_dump()
        except (ValidationError, TypeError):
            continue
        if value not in result:
            result.append(value)
    return result


@lru_cache(maxsize=1)
def _identifier_routes():
    routes = {}
    for site in native_recipes(id_type=None).values():
        for raw, is_probe in ((site.url, False), (site.probe_url, True)):
            if not raw:
                continue
            template = normalize_web_url(raw, keep_query=True)
            if template and "{username}" in template:
                pattern = re.escape(template).replace(re.escape("{username}"), r"([^/?&#]+)")
                routes.setdefault(social_host(template), []).append((re.compile(pattern, re.IGNORECASE), site, is_probe))
    return routes


def identifiers_from_url(raw):
    url = normalize_web_url(raw, keep_query=True)
    if not url:
        return []
    core = parse_social_profile(url)
    result = []
    routes = _identifier_routes().get(social_host(url), [])
    for pattern, site, is_probe in sorted(routes, key=lambda item: item[1].id_type == "username"):
        # Reserved routes on known providers may only be interpreted as typed IDs.
        if site.id_type == "username" and social_host(url) in PROFILE_ROUTES and not is_probe:
            continue
        match = pattern.fullmatch(url)
        if match:
            value = unquote(match[1])
            if site.accepts_username(value):
                for identifier in identifier_values([{ "value": value, "id_type": site.id_type}]):
                    if identifier not in result:
                        result.append(identifier)
    typed = [item for item in result if item["id_type"] != "username"]
    if typed:
        return typed
    if core and core.resource_kind == "username":
        return identifier_values([{"value": core.username, "id_type": "username"}])
    return result


def add_identifiers(context, raw, source_url=None, source_tool=None):
    """Keep distinct types and provenance; never promote an ID to an alias."""
    values = context.extra.setdefault("maigret_identifiers", [])
    provenance = context.extra.setdefault("maigret_identifier_sources", {})
    changed = False
    for item in identifier_values(raw):
        if item["id_type"] == "username":
            continue  # Username pivots keep their existing format/role filtering.
        if item not in values and len(values) < 100:
            values.append(item)
            changed = True
        if item in values and source_url:
            key = item["id_type"] + ":" + item["value"]
            entry = {"url": source_url, "tool": source_tool, "relationship": "observed_identifier"}
            sources = provenance.setdefault(key, [])
            if entry not in sources and len(sources) < 10:
                sources.append(entry)
    return changed


def apply_url_identifiers(context, source_url, raw):
    """Persist URL-derived candidates without manufacturing page observations."""
    from app.engine.pivot_rules import USERNAME_REGEX, IGNORE_USERNAMES
    identifiers = identifier_values(raw)
    context.extra.setdefault("maigret_url_identifiers", {})[source_url] = identifiers
    add_identifiers(context, identifiers, source_url, "maigret_enricher")
    known = {value.casefold() for value in context.all_usernames()}
    for item in identifiers:
        value = item["value"]
        if (item["id_type"] == "username" and USERNAME_REGEX.fullmatch(value)
                and value.casefold() not in IGNORE_USERNAMES and value.casefold() not in known
                and len(context.discovered_usernames) < 100):
            context.discovered_usernames.append(value)
            known.add(value.casefold())
