import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import httpx
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class UsernameFinderTool(BaseTool):
    """
    Advanced Username OSINT Engine powered by the official WhatsMyName database
    and Spiderfoot verification mechanics (triple verification: e_code, e_string, m_string,
    musthavename checks, and generic role filtering).
    """

    name = "username_finder"
    description = "Rastreo avanzado de alias en 160+ plataformas con firmas WhatsMyName y triple validación"
    category = ToolCategory.USERNAME
    required_inputs = ["username"]

    DATA_DIR = Path(__file__).parent / "data"
    WMN_FILE = DATA_DIR / "wmn-data.json"
    GENERIC_USERS_FILE = DATA_DIR / "generic_usernames.txt"

    MAX_SITES = 160
    CONCURRENCY_LIMIT = 20

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
                sites = sorted_sites[: self.MAX_SITES]
            except Exception:
                pass

        self._sites_cache = sites
        return sites

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        usernames = context.all_usernames()
        if not usernames:
            return findings

        sites = self._load_sites()
        if not sites:
            return findings

        semaphore = asyncio.Semaphore(self.CONCURRENCY_LIMIT)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }

        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True, headers=headers, verify=False) as client:
            for username in usernames:
                clean_user = username.strip()
                if clean_user.lower() in self._generic_users or len(clean_user) < 3:
                    continue

                tasks = [
                    self._check_site(client, clean_user, site, semaphore)
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

        async with semaphore:
            try:
                resp = await client.get(url)
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
