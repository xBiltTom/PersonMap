import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import httpx
from app.core.config import settings
from app.core.events import event_bus
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class UsernameFinderTool(BaseTool):
    """
    Advanced Username OSINT Engine powered by the official WhatsMyName database
    and Spiderfoot verification mechanics (triple verification: e_code, e_string, m_string,
    musthavename checks, and generic role filtering).
    """

    name = "username_finder"
    description = "Rastreo avanzado de alias en 500+ plataformas con firmas WhatsMyName y triple validación"
    category = ToolCategory.USERNAME
    required_inputs = ["username"]

    DATA_DIR = Path(__file__).parent / "data"
    WMN_FILE = DATA_DIR / "wmn-data.json"
    GENERIC_USERS_FILE = DATA_DIR / "generic_usernames.txt"

    # How many sites from the bundled WhatsMyName dataset to actually check.
    # Configurable via PERSON_MAP_USERNAME_SCAN_MAX_SITES / .env; the dataset
    # itself carries 700+ entries, so this used to be an artificial bottleneck.
    #
    # La concurrencia ya no es una constante aquí: era de 30 sobre un
    # presupuesto global de 40, es decir, esta sola herramienta se quedaba con
    # el 75 % del proceso y dejaba 10 ranuras para las otras diecisiete de la
    # ronda. Ahora sale de la configuración y queda acotada por la cuota de
    # `settings.tool_concurrency_budget()`.
    PROGRESS_EVERY = 25

    PRIORITY_PLATFORMS = {
        "github", "gitlab", "reddit", "twitter", "x", "instagram", "telegram",
        "steam", "spotify", "twitch", "pinterest", "medium", "devto", "hackerrank",
        "leetcode", "codeforces", "chess", "soundcloud", "duolingo", "behance",
        "keybase", "kaggle", "youtube", "tiktok", "flickr", "vimeo", "patreon",
        "discord", "dockerhub", "npm", "pypi", "bitbucket", "deviantart", "wattpad",
        "goodreads", "snapchat", "kick", "linktree", "buy me a coffee", "sublime text",
        "pastebin", "strava", "roblox", "speedrun", "crunchyroll", "trello",
    }

    def __init__(self) -> None:
        self._sites_cache: Optional[List[Dict[str, Any]]] = None
        self._generic_users: Set[str] = set()
        self._load_generic_users()

    def _load_generic_users(self) -> None:
        """Loads generic role usernames to prevent false-positive queries."""
        if self.GENERIC_USERS_FILE.exists():
            try:
                content = self.GENERIC_USERS_FILE.read_text(encoding="utf-8")
                self._generic_users = {
                    line.strip().lower() for line in content.splitlines() if line.strip() and not line.startswith("#")
                }
            except Exception:
                pass
        if not self._generic_users:
            self._generic_users = {"admin", "root", "support", "billing", "info", "help", "contact", "sales", "test"}

    def _load_sites(self) -> List[Dict[str, Any]]:
        """Loads and sorts the top sites from the WhatsMyName database."""
        if self._sites_cache is not None:
            return self._sites_cache

        sites: List[Dict[str, Any]] = []
        if self.WMN_FILE.exists():
            try:
                data = json.loads(self.WMN_FILE.read_text(encoding="utf-8"))
                raw_sites = data.get("sites", [])

                excluded_cats = {"xx NSFW xx", "archived"}
                priority_cats = {"social", "coding", "tech", "gaming", "music", "art", "blog", "video", "images", "business", "forum"}

                valid_sites = [
                    s for s in raw_sites
                    if s.get("valid", True) is not False
                    and s.get("cat") not in excluded_cats
                    and "uri_check" in s
                ]

                # Sort priority platforms first, then priority categories
                def site_priority(s: Dict[str, Any]) -> int:
                    s_name = s.get("name", "").lower()
                    if any(p in s_name for p in self.PRIORITY_PLATFORMS):
                        return 0
                    if s.get("cat") in priority_cats:
                        return 1
                    return 2

                sorted_sites = sorted(valid_sites, key=site_priority)
                max_sites = max(1, settings.username_scan_max_sites)
                sites = sorted_sites[:max_sites]
            except Exception:
                pass

        self._sites_cache = sites
        return sites

    def catalog_size(self) -> Dict[str, int]:
        """
        Tamaño del catálogo efectivo, para la huella de configuración.

        Sin este dato en las métricas, las investigaciones medidas antes y
        después de ampliar el catálogo son incomparables **y nada permite
        detectarlo**: `scorer_version` protege el modelo de identidad, pero el
        número de sitios escaneados no lo protegía nadie.
        """
        available = 0
        if self.WMN_FILE.exists():
            try:
                data = json.loads(self.WMN_FILE.read_text(encoding="utf-8"))
                available = sum(
                    1
                    for site in data.get("sites", [])
                    if site.get("valid", True) is not False
                    and site.get("cat") not in {"xx NSFW xx", "archived"}
                    and "uri_check" in site
                )
            except Exception:
                available = 0
        return {"available": available, "scanned": len(self._load_sites())}

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
        progress_counter = {"checked": 0}

        # Alias ya barridos en esta investigación.
        #
        # El motor re-ejecuta esta herramienta en cada ronda, porque su clave de
        # ejecución incluye la lista completa de alias y el pivoteo va añadiendo
        # los que descubre. El efecto medido era que la ronda 2 volvía a
        # comprobar el alias de la ronda 1, y la ronda 3 los dos anteriores:
        # 23 s + 45 s + 68 s, con casi la mitad del trabajo repetido.
        #
        # El registro vive en `context.extra` y no en la instancia, porque la
        # herramienta es un singleton del registry compartido por todas las
        # investigaciones: guardarlo aquí lo haría crecer sin límite y, peor,
        # una investigación silenciaría el barrido de la siguiente.
        scanned: Set[str] = context.extra.setdefault("username_finder_scanned", set())

        async with http_client.build_client(timeout=6.0) as client:
            for username in usernames:
                clean_user = username.strip()
                if clean_user.lower() in self._generic_users or len(clean_user) < 3:
                    continue
                if clean_user.lower() in scanned:
                    continue
                scanned.add(clean_user.lower())

                progress_counter["checked"] = 0
                tasks = [
                    self._check_site(client, clean_user, site, semaphore, investigation_id, progress_counter, len(sites))
                    for site in sites
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for res in results:
                    if isinstance(res, ToolFinding):
                        findings.append(res)

        return findings

    async def _check_site(
        self,
        client: httpx.AsyncClient,
        username: str,
        site: Dict[str, Any],
        semaphore: asyncio.Semaphore,
        investigation_id: Optional[str],
        progress_counter: Dict[str, int],
        total_sites: int,
    ) -> Optional[ToolFinding]:
        site_name = site.get("name", "Unknown")
        uri_check = site.get("uri_check", "")
        if not uri_check:
            return None

        url = uri_check.format(account=username)
        uri_pretty = site.get("uri_pretty", url)
        pretty_url = uri_pretty.format(account=username) if uri_pretty else url

        e_code = site.get("e_code", 200)
        e_string = site.get("e_string")
        m_string = site.get("m_string")
        cat = site.get("cat", "social")

        try:
            async with semaphore:
                resp = await http_client.get(
                    client,
                    url,
                    headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"},
                )

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
                    # Cifras estructuradas, no solo una frase. El evento ya se
                    # emitía y la interfaz lo desperdiciaba como una línea de log
                    # más: sin `checked`/`total` no se puede dibujar una barra, y
                    # una consola muda durante minutos arruina la sustentación.
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

            body = resp.text

            # 1. HTTP Status Code validation
            if resp.status_code != e_code:
                return None

            # 2. Absence string validation (must NOT be present)
            if m_string and m_string in body:
                return None

            # 3. Existence string validation (MUST be present if specified)
            if e_string and e_string not in body:
                return None

            # 4. Spiderfoot musthavename heuristic (avoids generic 200 soft landing pages)
            is_json_resp = resp.headers.get("content-type", "").startswith("application/json")
            if not is_json_resp:
                if username.lower() not in body.lower() and username.lower() not in resp.url.path.lower():
                    return None

            confidence = 0.90 if e_string else 0.85

            return ToolFinding(
                entity_type="social_account",
                platform=site_name,
                value=pretty_url,
                display_name=f"{site_name}: @{username}",
                confidence=confidence,
                metadata_info={
                    "username": username,
                    "platform": site_name,
                    "category": cat,
                    "url": pretty_url,
                    "source_tool": "username_finder",
                    "checked_status": resp.status_code,
                },
            )
        except Exception:
            return None
