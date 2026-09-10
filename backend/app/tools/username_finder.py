"""
Rastreo de alias a través del catálogo unificado de plataformas.

El catálogo lo construye `app.tools.dataset_adapter` normalizando en memoria
WhatsMyName (CC BY-SA 4.0) y Maigret (MIT). Aquí solo se comprueba.

Lo que aporta la unificación no es sobre todo volumen, es **precisión**:

- `regexCheck` descarta un alias que un sitio no puede aceptar **sin gastar la
  petición** (QQ solo admite identificadores numéricos), lo que quita tráfico y
  quita falsos positivos a la vez.
- `absenceStrs` añade cadenas que delatan una página de "no existe" en sitios
  que responden 200 a cualquier cosa.
- `alexaRank` ordena por popularidad real, así que recortar el catálogo conserva
  los sitios donde una persona tiene cuentas de verdad.
- `protection` deja fuera los sitios inalcanzables sin `curl_cffi`, en vez de
  quemar reintentos contra ellos.
"""

import asyncio
import secrets
import string
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx

from app.core.config import settings
from app.core.events import event_bus
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.dataset_adapter import SiteCheck, build_catalog, catalog_stats

HTML_ACCEPT = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}


class UsernameFinderTool(BaseTool):
    """
    Motor de enumeración de alias con triple validación (código de estado,
    cadena de presencia y cadena de ausencia) más la comprobación previa del
    formato del alias.
    """

    name = "username_finder"
    description = (
        "Rastreo de alias en miles de plataformas con los catálogos de "
        "WhatsMyName y Maigret, validación por código/cadenas y descarte previo "
        "de sitios cuyo formato de alias no encaja"
    )
    category = ToolCategory.USERNAME
    required_inputs = ["username"]

    DATA_DIR = Path(__file__).parent / "data"
    GENERIC_USERS_FILE = DATA_DIR / "generic_usernames.txt"

    PROGRESS_EVERY = 25

    # Intentos de inventar un alias de control que el formato del sitio acepte.
    CONTROL_ATTEMPTS = 5

    def __init__(self) -> None:
        self._catalog: Optional[List[SiteCheck]] = None
        self._catalog_limit: Optional[int] = None
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
        limit = max(1, settings.username_scan_max_sites)
        if self._catalog is None or self._catalog_limit != limit:
            self._catalog = build_catalog(limit=limit)
            self._catalog_limit = limit
        return self._catalog

    def catalog_size(self) -> Dict[str, int]:
        """Tamaño del catálogo efectivo, para la huella de configuración."""
        available = len(build_catalog())
        return {"available": available, "scanned": len(self._load_sites())}

    def catalog_breakdown(self) -> Dict[str, Any]:
        """Composición del catálogo, para la interfaz y el artículo."""
        return catalog_stats(self._load_sites())

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        usernames = context.all_usernames()
        if not usernames:
            return findings

        sites = self._load_sites()
        if not sites:
            return findings

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
        scanned: Set[str] = context.extra.setdefault("username_finder_scanned", set())

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
        if remaining <= 0:
            if investigation_id and usernames:
                await event_bus.publish(investigation_id, {
                    "type": "log",
                    "phase": "catalog_filter",
                    "tool": self.name,
                    "message": (
                        f"[{self.name}] Tope de {settings.username_scan_max_aliases} "
                        f"alias por investigación alcanzado; no se barren más."
                    ),
                    "timestamp": time.time(),
                })
            return findings

        async with http_client.build_client(timeout=6.0) as client:
            for username in usernames:
                if remaining <= 0:
                    break
                clean_user = username.strip()
                if clean_user.lower() in self._generic_users or len(clean_user) < 3:
                    continue
                if clean_user.lower() in scanned:
                    continue
                scanned.add(clean_user.lower())
                remaining -= 1

                # El filtro previo por formato: no gasta red y quita ruido.
                applicable = [s for s in sites if s.accepts_username(clean_user)]
                skipped = len(sites) - len(applicable)
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
                tasks = [
                    self._check_site(
                        client,
                        clean_user,
                        site,
                        semaphore,
                        investigation_id,
                        progress_counter,
                        len(applicable),
                    )
                    for site in applicable
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                stats["checked"] += len(applicable)

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
                        findings.append(res)

        return findings

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
                metadata_info={
                    "username": username,
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

        if site.check_type == "response_url":
            # El sitio redirige a una página de error en vez de dar 404.
            if str(resp.url).rstrip("/") != site.build_url(username).rstrip("/"):
                return False
        elif resp.status_code != site.expected_code:
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
