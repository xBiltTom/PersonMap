"""Maigret-backed enumeration with complementary WhatsMyName checks.

The public tool name, negative controls, coverage, budgets and evidence
contract remain stable. The isolated worker executes upstream site recipes
and extractors; only WMN-only platforms use the compact legacy checker.
"""

import asyncio
import base64
import ast
import hashlib
import json
import secrets
import string
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx
from bs4 import BeautifulSoup
from app.tools.telegram_profiles import observe_telegram_page

from app.core.config import settings
from app.core.events import event_bus
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.social_profiles import core_profile_candidates, parse_social_profile, social_host, TELEGRAM_HOSTS
from app.tools.dataset_adapter import SiteCheck, catalog_stats
from app.tools.maigret_catalog import build_scan_catalog as build_catalog, database_info, execution_config
from app.tools.maigret_runner import run_maigret, decoded_headers

HTML_ACCEPT = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}


class UsernameFinderTool(BaseTool):
    """Complete native search, preserving candidate/verified semantics."""

    name = "username_finder"
    description = (
        "Búsqueda con Maigret completo: detección, extracción de perfiles y "
        "enlaces, controles negativos y cobertura adicional de WhatsMyName"
    )
    category = ToolCategory.USERNAME
    required_inputs = ["username"]

    def can_run(self, context: TargetContext) -> bool:
        return bool(context.all_usernames() or context.extra.get("maigret_options", {}).get("permutation_parts"))

    DATA_DIR = Path(__file__).parent / "data"
    GENERIC_USERS_FILE = DATA_DIR / "generic_usernames.txt"

    PROGRESS_EVERY = 25

    # Intentos de inventar un alias de control que el formato del sitio acepte.
    CONTROL_ATTEMPTS = 5

    def __init__(self) -> None:
        self._catalog: Optional[List[SiteCheck]] = None
        self._catalog_limit: Optional[tuple] = None
        self._full_catalog = None
        self._generic_users: Set[str] = set()
        self._load_generic_users()

    def _load_generic_users(self) -> None:
        """Alias de rol genéricos, que producirían falsos positivos en masa."""
        if self.GENERIC_USERS_FILE.exists():
            try:
                content = self.GENERIC_USERS_FILE.read_text(encoding="utf-8")
                self._generic_users = {
                    line.strip().lower()
                    for line in content.splitlines()
                    if line.strip() and not line.startswith("#")
                }
            except Exception:
                pass
        if not self._generic_users:
            self._generic_users = {
                "admin", "root", "support", "billing", "info",
                "help", "contact", "sales", "test",
            }

    def _load_sites(self) -> List[SiteCheck]:
        """
        Catálogo efectivo, cacheado por tope configurado.

        La caché se invalida si cambia `username_scan_max_sites`, porque los
        tests y las mediciones lo ajustan en caliente y un catálogo cacheado con
        el tope anterior daría cifras que no corresponden a la configuración.
        """
        limit = max(0, settings.username_scan_max_sites)
        cache_key = (limit, tuple(settings.maigret_tags), tuple(settings.maigret_site_names),
                     tuple(settings.maigret_excluded_tags), bool(settings.maigret_tor_proxy),
                     bool(settings.maigret_i2p_proxy), settings.maigret_check_domains)
        if self._catalog is None or self._catalog_limit != cache_key:
            self._full_catalog = build_catalog(include_variants=True)
            self._catalog = self._full_catalog[:limit] if limit else self._full_catalog
            self._catalog_limit = cache_key
        return self._catalog

    def catalog_size(self) -> Dict[str, int]:
        """Tamaño del catálogo efectivo, para la huella de configuración."""
        available = len(build_catalog(include_variants=True))
        return {"available": available, "scanned": len(self._load_sites())}

    def catalog_breakdown(self) -> Dict[str, Any]:
        """Composición del catálogo, para la interfaz y el artículo."""
        return {**catalog_stats(self._load_sites()), "maigret_commit": None, **database_info()}

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        options = context.extra.get("maigret_options", {})
        parts = options.get("permutation_parts", [])
        if parts and settings.maigret_max_permutations:
            key = json.dumps(parts)
            permutations = context.extra.setdefault("username_finder_permutations", {})
            if key not in permutations:
                async def permuted(result):
                    permutations[key] = result["usernames"]
                await run_maigret("", [], {}, permuted, operation="permute", parts=parts,
                                 limit=settings.maigret_max_permutations)
            for alias in permutations.get(key, []):
                if alias.casefold() not in self._generic_users and alias not in context.all_usernames():
                    context.discovered_usernames.append(alias)
        usernames = context.all_usernames()
        if not usernames:
            return findings

        sites = self._load_sites()
        full_catalog = self._full_catalog or sites
        filters = {key: options[key] for key in ("tags", "names", "excluded") if key in options}
        if filters:
            full_catalog = build_catalog(include_variants=True, **filters)
            sites = full_catalog[:settings.username_scan_max_sites] if settings.username_scan_max_sites > 0 else full_catalog
        if context.extra.get("username_scan_mode") == "all":
            sites = full_catalog
        if not sites:
            return findings
        catalogue_id = hashlib.sha256(json.dumps({**database_info(), **execution_config(),
            "sites": [(s.name, getattr(s, "url", ""), getattr(s, "native_name", None)) for s in full_catalog],
            "options": options, "engine_version": 4}, sort_keys=True).encode()).hexdigest()
        if context.extra.get("username_finder_catalog_id") != catalogue_id:
            for field in ("username_finder_coverage", "username_finder_scanned", "username_finder_stats",
                          "username_finder_outcomes", "username_finder_diagnostics", "username_finder_checks"):
                context.extra.pop(field, None)
        context.extra["username_finder_catalog_id"] = catalogue_id
        fast = context.extra.get("username_scan_mode") == "fast"
        if fast:
            sites = sites[:max(1, settings.mcp_username_fast_sites)]

        investigation_id = context.extra.get("investigation_id")
        semaphore = asyncio.Semaphore(
            settings.tool_concurrency_budget(settings.username_scan_concurrency)
        )

        # Alias ya barridos en esta investigación.
        #
        # El motor re-ejecuta esta herramienta en cada ronda, porque su clave de
        # ejecución incluye la lista completa de alias y el pivoteo va añadiendo
        # los que descubre. Sin este registro, la ronda 2 volvía a comprobar el
        # alias de la ronda 1 y la ronda 3 los dos anteriores.
        #
        # Vive en `context.extra` y no en la instancia porque la herramienta es
        # un singleton del registry compartido por todas las investigaciones.
        scanned: Set[str] = set(context.extra.setdefault("username_finder_scanned", []))
        context.extra["username_finder_scanned"] = scanned
        # Coverage lets a later deep pass continue past the fast prefix.
        coverage = context.extra.setdefault("username_finder_coverage", {})

        # Contadores acumulados de la investigación, para que la interfaz pueda
        # decir cuántos sitios se descartaron sin gastar una petición.
        stats: Dict[str, int] = context.extra.setdefault(
            "username_finder_stats",
            {"checked": 0, "skipped_by_regex": 0, "rejected_by_control": 0},
        )

        # El tope de alias es lo que acota la duración de la investigación: cada
        # alias nuevo cuesta un barrido entero del catálogo. `all_usernames()`
        # devuelve primero el que aportó la persona y después los descubiertos,
        # así que recortar por el final descarta siempre lo más especulativo.
        remaining = max(0, settings.username_scan_max_aliases - len(scanned))
        processed = 0

        async with http_client.build_client(timeout=6.0, public_only=True) as client:
            for username in usernames:
                if fast and processed >= 1:
                    break
                clean_user = username.strip()
                if clean_user.lower() in self._generic_users or len(clean_user) < 3:
                    continue
                key = clean_user.lower()
                # Old contexts with only a scanned set already covered the configured catalogue.
                start = coverage.get(key, len(sites) if key in scanned else 0)
                if start >= len(sites) or (key not in scanned and remaining <= 0):
                    continue
                candidates = context.extra.setdefault("candidate_urls", [])
                provenance = context.extra.setdefault("derived_profile_candidates", {})
                for candidate in core_profile_candidates(clean_user):
                    if candidate not in candidates:
                        candidates.append(candidate)
                    provenance[candidate] = {"source_tool": self.name, "alias": clean_user, "status": "derived"}
                if key not in scanned:
                    scanned.add(key)
                    remaining -= 1
                coverage.setdefault(key, start)
                processed += 1

                # El filtro previo por formato: no gasta red y quita ruido.
                pending_sites = sites[start:]
                applicable = [s for s in pending_sites if s.accepts_username(clean_user)]
                skipped = len(pending_sites) - len(applicable)
                stats["skipped_by_regex"] += skipped

                if investigation_id and skipped:
                    await event_bus.publish(investigation_id, {
                        "type": "log",
                        "phase": "catalog_filter",
                        "tool": self.name,
                        "message": (
                            f"[{self.name}] '@{clean_user}': {skipped} de {len(sites)} "
                            f"plataformas descartadas por formato de alias sin gastar "
                            f"una sola petición."
                        ),
                        "timestamp": time.time(),
                    })

                progress_counter = {"checked": 0, "control_rejected": 0}
                native = [s for s in applicable if getattr(s, "native_name", None)]
                complementary = [s for s in applicable if not getattr(s, "native_name", None)]
                legacy_quota = asyncio.Semaphore(max(1, settings.tool_concurrency_budget(settings.username_scan_concurrency) // 2))
                async def complementary_check(site):
                    # Keep capacity available while the native worker starts;
                    # hundreds of fallback tasks must not fill its RPC queue.
                    async with legacy_quota:
                        return await self._check_site(client, clean_user, site, semaphore,
                            investigation_id, progress_counter, len(applicable))
                tasks = [
                    complementary_check(site)
                    for site in complementary
                ]
                async def collect_native():
                    native_findings = []
                    by_name = {s.native_name: s for s in native}
                    controls = {s.native_name: self._invented_alias(s, clean_user) for s in native}

                    async def collect(result):
                        site = by_name[result["site"]]
                        outcomes = context.extra.setdefault("username_finder_outcomes", {})
                        counts = outcomes.setdefault(clean_user, {})
                        state = result.get("status", "Unknown")
                        counts[state] = counts.get(state, 0) + 1
                        if state in {"Unknown", "Illegal"}:
                            diagnostics = context.extra.setdefault("username_finder_diagnostics", {}).setdefault(clean_user, {})
                            if len(diagnostics) < 1000:
                                diagnostics[result["site"]] = {"status": state, "error": result.get("error"),
                                                              "http_status": result.get("http_status")}
                        finding = self._native_finding(site, clean_user, result, progress_counter)
                        check = {"status": state, "error": result.get("error"), "http_status": result.get("http_status"),
                                 "url": result.get("url_user") or site.build_pretty_url(clean_user), "id_type": "username"}
                        if site.protocol == "dns":
                            check["url"] = site.build_pretty_url(clean_user)
                        if state == "Claimed" and finding is None:
                            check.update(status="Unknown", error="Detection rejected by profile or negative-control checks")
                        context.extra.setdefault("username_finder_checks", {}).setdefault(clean_user, {})[site.name] = check
                        progress_counter["checked"] += 1
                        if finding:
                            native_findings.append(finding)
                        if investigation_id and progress_counter["checked"] % self.PROGRESS_EVERY == 0:
                            await event_bus.publish(investigation_id, {
                                "type": "log", "phase": "progress", "tool": self.name,
                                "checked": progress_counter["checked"], "total": len(applicable),
                                "pct": round(progress_counter["checked"] / len(applicable) * 100, 1),
                                "subject": clean_user, "message": f"[username_finder] Maigret: {progress_counter['checked']}/{len(applicable)}",
                                "timestamp": time.time(),
                            })
                    async def progress(message):
                        checked = message["checked"]
                        if investigation_id and (checked % self.PROGRESS_EVERY == 0 or checked == len(native)):
                            await event_bus.publish(investigation_id, {
                                "type": "log", "phase": "maigret_detection", "tool": self.name,
                                "checked": checked, "total": len(native),
                                "pct": round(checked / len(native) * 100, 1), "subject": clean_user,
                                "message": f"[username_finder] Maigret: {checked}/{len(native)} consultas; validando controles negativos.",
                                "timestamp": time.time(),
                            })
                    if native:
                        await run_maigret(clean_user, native, controls, collect, progress,
                                         request_semaphore=semaphore, options=options)
                    return native_findings

                native_task = asyncio.create_task(collect_native())
                try:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    results.extend(await native_task)
                finally:
                    if not native_task.done():
                        native_task.cancel()
                    await asyncio.gather(native_task, return_exceptions=True)
                coverage[key] = len(sites)
                stats["checked"] += len(applicable)
                if investigation_id:
                    await event_bus.publish(investigation_id, {
                        "type": "log", "phase": "progress", "tool": self.name,
                        "checked": len(applicable), "total": len(applicable), "pct": 100.0,
                        "subject": clean_user, "message": f"[username_finder] Barrido y controles terminados para @{clean_user}.",
                        "timestamp": time.time(),
                    })

                rejected = progress_counter["control_rejected"]
                stats["rejected_by_control"] = stats.get("rejected_by_control", 0) + rejected
                if investigation_id and rejected:
                    await event_bus.publish(investigation_id, {
                        "type": "log",
                        "phase": "catalog_filter",
                        "tool": self.name,
                        "message": (
                            f"[{self.name}] '@{clean_user}': {rejected} "
                            f"{'plataforma descartada' if rejected == 1 else 'plataformas descartadas'} "
                            f"por control negativo: también «encontraban» un alias inventado."
                        ),
                        "timestamp": time.time(),
                    })

                for res in results:
                    if isinstance(res, ToolFinding):
                        res.metadata_info["scan_mode"] = context.extra.get("username_scan_mode", "deep")
                        res.metadata_info["catalogue_sites_covered"] = len(sites)
                        findings.append(res)

        return findings

    @staticmethod
    def _response(result):
        wire = result.get("response")
        if not wire:
            return None
        response = httpx.Response(wire["status"], headers=decoded_headers(wire.get("headers", {}).items()),
            content=base64.b64decode(wire["body"]), request=httpx.Request("GET", wire["url"]))
        response.encoding = wire.get("encoding") or "utf-8"
        return response

    def _native_finding(self, site, username, result, counter):
        if result.get("status") != "Claimed" or result.get("is_similar"):
            return None
        response = self._response(result)
        if response is None:
            return None
        title = BeautifulSoup(response.text, "html.parser").title if "html" in response.headers.get("content-type", "") else None
        if title and any(marker in title.get_text().lower() for marker in (
                "just a moment", "captcha", "access denied", "verify you are human", "log in", "sign in")):
            return None
        profile = parse_social_profile(result.get("url_user", ""))
        if profile and profile.platform == "telegram" and not self._matches(site, response, username):
            return None
        final_profile = parse_social_profile(str(response.url))
        if profile and final_profile and (profile.platform != final_profile.platform or
                                         profile.username.casefold() != final_profile.username.casefold()):
            return None
        controlled = result.get("control") or {}
        control_response = self._response(controlled)
        control = None
        if control_response is not None and controlled.get("status") in {"Claimed", "Available"}:
            blocked = (control_response.status_code in {401, 403, 429, 999} or control_response.status_code >= 500
                       or any(marker in control_response.text.lower() for marker in
                              ("just a moment", "verify you are human", "captcha", "access denied")))
            if not blocked:
                control = controlled["status"] == "Claimed"
                if profile and profile.platform == "telegram" and control_response.status_code == 200:
                    control = True if self._matches(site, control_response, controlled["username"]) else None
        if control is True:
            counter["control_rejected"] += 1
            return None
        data = result.get("ids_data") or {}
        from app.tools.maigret_ids import identifier_values
        def values(*keys):
            collected = []
            for key in keys:
                value = data.get(key)
                if isinstance(value, str) and value.startswith("["):
                    try:
                        value = ast.literal_eval(value)
                    except (ValueError, SyntaxError):
                        pass
                entries = value if isinstance(value, list) else [value]
                collected.extend(v for v in entries if isinstance(v, str) and v)
            return list(dict.fromkeys(collected))
        typed = result.get("ids_usernames") or {}
        users = [value for value, kind in typed.items() if kind == "username"]
        links = list(dict.fromkeys([link for link in [*result.get("ids_links", []),
            *values("links", "website", "blog", "blog_url", "url")] if isinstance(link, str) and link.startswith(("http://", "https://"))]))
        raw_url = result.get("url_user") or site.build_pretty_url(username)
        protocol = getattr(site, "protocol", "")
        if protocol == "dns" and not raw_url.startswith(("https://", "http://")):
            raw_url = "https://" + raw_url
        canonical = profile.url if profile else raw_url
        metadata = {
            "username": username, "url": canonical, "profile_url": canonical,
            "source_tool": self.name, "search_engine": "maigret", **database_info(),
            "verification_status": "candidate", "catalog_source": "maigret",
            "negative_control": "passed" if control is False else "untested",
            "checked_status": result.get("http_status"), "category": site.category,
            "sensitive_platform": site.sensitive, "maigret_status": result["status"],
            "maigret_data": data, "discovered_identifiers": typed,
            "extracted_identifiers": identifier_values(result.get("identifiers", typed)),
            "extracted_usernames": users, "extracted_emails": values("email", "emails"),
            "extracted_phones": values("phone", "phones", "phone_number"),
            "linked_profiles": links, "bio": next(iter(values("bio", "about", "description")), ""),
            "name": next(iter(values("fullname", "full_name", "name")), ""),
            "location": next(iter(values("location", "city", "country")), ""),
            "avatar_url": next(iter(values("image", "avatar", "avatar_url")), None),
            "site_rank": site.rank if site.rank < 5_000_000 else None,
            "keyword_match": result.get("keyword_match"),
            "id_type": getattr(site, "id_type", "username"), "protocol": protocol,
            "maigret_site": getattr(site, "native_name", None) or site.name,
            "maigret_recipes": [getattr(site, "native_name", None) or site.name],
            "maigret_queries": [{"value": username, "id_type": getattr(site, "id_type", "username"),
                                 "site": getattr(site, "native_name", None) or site.name}],
            "access_context": "configured_session" if settings.maigret_cookie_file else "anonymous",
        }
        if metadata["id_type"] != "username":
            metadata.pop("username", None)
            metadata["queried_identifier"] = {"value": username, "id_type": metadata["id_type"]}
        return ToolFinding(entity_type="domain" if protocol == "dns" else "sensitive_account" if site.sensitive else "social_account",
            platform=profile.platform if profile else site.name, value=canonical,
            display_name=f"{site.name}: @{username}", confidence=0.85 if control is False else 0.65,
            evidence_urls=list(dict.fromkeys([raw_url, result.get("url_probe") or raw_url])), metadata_info=metadata)

    async def _check_site(
        self,
        client: httpx.AsyncClient,
        username: str,
        site: SiteCheck,
        semaphore: asyncio.Semaphore,
        investigation_id: Optional[str],
        progress_counter: Dict[str, int],
        total_sites: int,
    ) -> Optional[ToolFinding]:
        url = site.build_url(username)
        pretty_url = site.build_pretty_url(username)

        try:
            async with semaphore:
                resp = await http_client.get(client, url, headers=HTML_ACCEPT)

            progress_counter["checked"] += 1
            if (
                investigation_id
                and progress_counter["checked"] % self.PROGRESS_EVERY == 0
            ):
                checked = progress_counter["checked"]
                await event_bus.publish(investigation_id, {
                    "type": "log",
                    "phase": "progress",
                    "tool": self.name,
                    # Cifras estructuradas, no solo una frase: sin `checked` y
                    # `total` no se puede dibujar una barra, y una consola muda
                    # durante minutos arruina la sustentación.
                    "checked": checked,
                    "total": total_sites,
                    "pct": round(checked / total_sites * 100, 1) if total_sites else 0.0,
                    "subject": username,
                    "message": (
                        f"[{self.name}] Progreso: {checked}/{total_sites} "
                        f"plataformas verificadas para '@{username}'..."
                    ),
                    "timestamp": time.time(),
                })

            if resp is None:
                return None

            if not self._matches(site, resp, username):
                return None

            # Control negativo: el mismo sitio con un alias inventado. Si también
            # "lo encuentra", el sitio responde igual a cualquier alias y el
            # resultado no prueba que la cuenta exista. Es lo que evita enseñar a
            # alguien una cuenta que no tiene. Medido con "JorgeWueder": los foros
            # de Southklad, Starsonice y Terminatorium lo "encontraban", y también
            # encuentran un alias inventado.
            control = await self._control_matches(client, site, username, semaphore)
            if control is True:
                progress_counter["control_rejected"] += 1
                return None

            # Con cadena de presencia la comprobación es específica del sitio;
            # sin ella solo se ha visto un código de estado, que es más débil.
            confidence = 0.90 if site.presence else 0.85
            if control is None:
                confidence = 0.65  # Inconclusive controls have lower priority.

            return ToolFinding(
                # Las plataformas de contenido adulto tienen tipo propio, no por
                # pudor sino porque el hallazgo es cualitativamente distinto:
                # necesita su propio icono, su propio filtro, su propio peso en
                # el scorecard y una recomendación que hable de extorsión, no de
                # privacidad genérica. Mezclarlo con las demás cuentas lo
                # enterraba entre cientos de filas.
                entity_type="sensitive_account" if site.sensitive else "social_account",
                platform=site.name,
                value=pretty_url,
                display_name=f"{site.name}: @{username}",
                confidence=confidence,
                evidence_urls=[url],
                metadata_info={
                    "username": username,
                    "verification_status": "candidate",
                    "telegram_peer_type": observe_telegram_page(BeautifulSoup(resp.text, "html.parser"), username).peer_type
                    if (parsed_profile := parse_social_profile(pretty_url)) and parsed_profile.platform == "telegram" else None,
                    "platform": site.name,
                    "category": site.category or "social",
                    "sensitive_platform": site.sensitive,
                    "url": pretty_url,
                    "source_tool": "username_finder",
                    "checked_status": resp.status_code,
                    # "untested" si no se pudo inventar un alias válido para el
                    # formato del sitio o la petición de control falló.
                    "negative_control": "passed" if control is False else "untested",
                    # Procedencia del dato del catálogo. Es lo que permite decir
                    # en el expediente de dónde salió la comprobación, y medir
                    # en el artículo qué aportó cada dataset.
                    "catalog_source": site.source,
                    "catalog_enriched_by": site.enriched_by,
                    "site_rank": site.rank if site.rank < 5_000_000 else None,
                },
            )
        except Exception:
            return None

    def _invented_alias(self, site: SiteCheck, username: str) -> Optional[str]:
        """
        Alias con la forma del real que casi con seguridad no ha registrado nadie.

        Conserva el tipo de cada carácter (letra, dígito, separador) para que el
        sitio lo acepte igual que el real, y lo alarga hasta 12 caracteres si el
        formato lo permite: un alias corto inventado sí puede existir por azar.
        """

        def shaped(template: str) -> str:
            return "".join(
                secrets.choice(string.ascii_lowercase)
                if ch.isalpha()
                else secrets.choice(string.digits)
                if ch.isdigit()
                else ch
                for ch in template
            )

        for _ in range(self.CONTROL_ATTEMPTS):
            for template in (username.ljust(12, "x"), username):
                candidate = shaped(template)
                if candidate.lower() != username.lower() and site.accepts_username(candidate):
                    return candidate
        return None

    async def _control_matches(
        self,
        client: httpx.AsyncClient,
        site: SiteCheck,
        username: str,
        semaphore: asyncio.Semaphore,
    ) -> Optional[bool]:
        """
        ¿El sitio también "encuentra" un alias inventado?

        `None` si no se pudo comprobar. En ese caso el hallazgo se conserva: sin
        control no hay prueba de que el sitio falle, y descartarlo perdería
        cuentas reales por un fallo de red.
        """
        control = self._invented_alias(site, username)
        if control is None:
            return None
        try:
            async with semaphore:
                resp = await http_client.get(client, site.build_url(control), headers=HTML_ACCEPT)
        except Exception:
            return None
        if resp is None:
            return None
        # A blocked or unavailable control does not demonstrate absence.
        if resp.status_code in {401, 403, 429, 999} or resp.status_code >= 500:
            return None
        title = resp.text.lower()
        if any(marker in title for marker in ("just a moment", "verify you are human", "captcha", "access denied")):
            return None
        if social_host(site.build_url(control)) in TELEGRAM_HOSTS and resp.status_code == 200:
            return True if self._matches(site, resp, control) else None
        return self._matches(site, resp, control)

    def _matches(
        self,
        site: SiteCheck,
        resp: httpx.Response,
        username: str,
    ) -> bool:
        """
        Triple validación más la heurística de Spiderfoot.

        El orden importa: primero lo barato (código de estado), después las
        cadenas y por último la comprobación de que el alias aparece de verdad
        en la respuesta, que es la que atrapa las páginas de aterrizaje
        genéricas que responden 200 a cualquier cosa.
        """
        body = resp.text
        host = resp.url.host
        profile = parse_social_profile(str(resp.url))
        if social_host(site.build_url(username)) in TELEGRAM_HOSTS:
            return (resp.status_code == 200 and profile is not None and profile.platform == "telegram" and profile.username.lower() == username.lower()
                    and observe_telegram_page(BeautifulSoup(body, "html.parser"), username).status == "verified")
        if resp.status_code == 200 and host in {"api.x.com", "api.twitter.com"}:
            try:
                return resp.json().get("reason") == "taken"
            except (ValueError, AttributeError):
                return False
        if host in {"www.tiktok.com", "tiktok.com"} and resp.url.path == "/oembed":
            try:
                author = parse_social_profile(resp.json().get("author_url", ""))
                return resp.status_code == 200 and author is not None and author.platform == "tiktok" and author.username.lower() == username.lower()
            except (ValueError, AttributeError, TypeError):
                return False

        if resp.status_code != site.expected_code:
            return False
        if site.check_type == "response_url":
            # El sitio redirige a una página de error en vez de dar 404.
            if str(resp.url).rstrip("/") != site.build_url(username).rstrip("/"):
                return False

        # Cadenas que delatan que el perfil NO existe.
        if any(marker in body for marker in site.absence):
            return False

        # Cadenas que deben estar si el perfil existe.
        if site.presence and not any(marker in body for marker in site.presence):
            return False

        is_json = resp.headers.get("content-type", "").startswith("application/json")
        if is_json:
            # Una API no tiene por qué devolver el alias en el cuerpo.
            return True

        lowered = username.lower()
        in_body = lowered in body.lower()
        in_final_url = lowered in resp.url.path.lower()

        if not site.presence and not site.absence:
            # Sitio sin ninguna validación de contenido: su único criterio es el
            # código de estado, y muchos devuelven 200 a cualquier URL de perfil.
            #
            # Aquí estaba la tautología: el criterio anterior aceptaba si el
            # alias aparecía en el cuerpo **o en la URL final**, y la URL la
            # construimos nosotros con el alias, así que pasaba siempre. Medido
            # sobre un alias sintético inexistente: 255 "cuentas" encontradas,
            # todas falsas. Para estos sitios se exige que el alias aparezca en
            # el CUERPO, que es lo que hace una página de perfil de verdad.
            return in_body

        # Con validación de contenido basta la heurística de Spiderfoot: si el
        # alias no aparece ni en el cuerpo ni en la URL final, nos redirigieron
        # a una página genérica.
        return in_body or in_final_url
