import json
from typing import Any, Dict, List, Optional, Set
import httpx
from app.core.config import settings
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


# Domains that, if matched by a reverse-image search, strongly suggest a real
# social profile (not just a random page reusing the same stock/avatar image).
KNOWN_PROFILE_DOMAINS = {
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "twitter.com": "x_twitter",
    "x.com": "x_twitter",
    "linkedin.com": "linkedin",
    "tiktok.com": "tiktok",
    "vk.com": "vk",
    "github.com": "github",
    "reddit.com": "reddit",
    "pinterest.com": "pinterest",
    "t.me": "telegram",
}


class ReverseImageSearchTool(BaseTool):
    """
    Reverse image / avatar search across the open web, adapted on top of
    official, pluggable third-party engines instead of scraping Google/Yandex
    directly (which would violate their Terms of Service and break constantly).

    Consumes the `avatar_urls` pivot populated by `pivot_rules.py` whenever any
    other tool discovers a profile picture (Gravatar, GitHub, Keybase, social
    profiles verified via OpenGraph, etc.), and looks for other pages on the
    open web using that same image -- the strongest correlation signal that
    exists for linking accounts across platforms that this system's own
    modules don't (yet) cover directly.

    Two optional backends are supported, both gracefully disabled unless an
    API key is configured (same pattern as the LLM integration):
      - SerpApi (Google Lens engine): https://serpapi.com/google-lens-api
      - Bing Visual Search (Azure AI Vision): https://learn.microsoft.com/bing/search-apis/bing-visual-search/
    """

    name = "reverse_image_search"
    description = (
        "Busca en la web abierta otras páginas donde aparece el mismo avatar/foto de perfil ya "
        "descubierto, usando Google Lens (SerpApi) y/o Bing Visual Search como motores oficiales."
    )
    category = ToolCategory.IMAGE
    required_inputs = ["avatar_urls"]

    MAX_AVATARS_PER_RUN = 5
    MAX_MATCHES_PER_AVATAR = 6

    def can_run(self, context: TargetContext) -> bool:
        return bool(context.extra.get("avatar_urls")) and settings.reverse_image_enabled

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        if not settings.reverse_image_enabled:
            return []

        avatar_urls: List[str] = list(context.extra.get("avatar_urls", []))[: self.MAX_AVATARS_PER_RUN]
        if not avatar_urls:
            return []

        findings: List[ToolFinding] = []
        seen_matches: Set[str] = set()

        async with http_client.build_client(timeout=15.0) as client:
            for avatar_url in avatar_urls:
                if settings.serpapi_key:
                    findings.extend(
                        await self._search_serpapi_google_lens(client, avatar_url, seen_matches)
                    )
                if settings.bing_visual_search_key:
                    findings.extend(
                        await self._search_bing_visual(client, avatar_url, seen_matches)
                    )

        return findings

    def _detect_platform(self, url: str) -> str:
        low = url.lower()
        for domain, platform in KNOWN_PROFILE_DOMAINS.items():
            if domain in low:
                return platform
        return "web"

    def _build_finding(
        self,
        avatar_url: str,
        matched_url: str,
        title: str,
        engine: str,
        source_domain: Optional[str] = None,
    ) -> Optional[ToolFinding]:
        if not matched_url or not matched_url.startswith("http"):
            return None

        platform = self._detect_platform(matched_url)
        # Base confidence is intentionally moderate: a visual match only proves
        # the *image* is reused somewhere, not that it's the same person's
        # account. It is a strong pivot signal, not a verified identity by itself.
        confidence = 0.55 if platform != "web" else 0.35

        return ToolFinding(
            entity_type="image_match",
            platform=platform,
            value=matched_url,
            display_name=title[:90] if title else matched_url,
            confidence=confidence,
            metadata_info={
                "source_tool": "reverse_image_search",
                "engine": engine,
                "origin_avatar_url": avatar_url,
                "matched_title": title,
                "matched_source_domain": source_domain,
                "url": matched_url,
                "avatar_url": avatar_url,
            },
            evidence_urls=[matched_url],
        )

    async def _search_serpapi_google_lens(
        self, client: httpx.AsyncClient, avatar_url: str, seen_matches: Set[str]
    ) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        try:
            resp = await http_client.get(
                client,
                "https://serpapi.com/search.json",
                params={
                    "engine": "google_lens",
                    "url": avatar_url,
                    "api_key": settings.serpapi_key,
                },
            )
            if resp is None or resp.status_code != 200:
                return []

            data = resp.json()
            matches = data.get("visual_matches", []) or data.get("image_results", [])
            for match in matches[: self.MAX_MATCHES_PER_AVATAR]:
                link = match.get("link") or match.get("original")
                if not link or link in seen_matches:
                    continue
                seen_matches.add(link)
                finding = self._build_finding(
                    avatar_url=avatar_url,
                    matched_url=link,
                    title=match.get("title", ""),
                    engine="serpapi_google_lens",
                    source_domain=match.get("source"),
                )
                if finding:
                    findings.append(finding)
        except Exception:
            pass
        return findings

    async def _search_bing_visual(
        self, client: httpx.AsyncClient, avatar_url: str, seen_matches: Set[str]
    ) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        try:
            knowledge_request = json.dumps({"imageInfo": {"url": avatar_url}})
            resp = await http_client.post(
                client,
                "https://api.bing.microsoft.com/v7.0/images/visualsearch",
                headers={"Ocp-Apim-Subscription-Key": settings.bing_visual_search_key or ""},
                files={"knowledgeRequest": (None, knowledge_request, "application/json")},
            )
            if resp is None or resp.status_code != 200:
                return []

            data = resp.json()
            for host_page_url, title, domain in self._walk_bing_response(data):
                if host_page_url in seen_matches:
                    continue
                seen_matches.add(host_page_url)
                finding = self._build_finding(
                    avatar_url=avatar_url,
                    matched_url=host_page_url,
                    title=title,
                    engine="bing_visual_search",
                    source_domain=domain,
                )
                if finding:
                    findings.append(finding)
                if len(findings) >= self.MAX_MATCHES_PER_AVATAR:
                    break
        except Exception:
            pass
        return findings

    def _walk_bing_response(self, data: Dict[str, Any]):
        """
        Bing Visual Search nests results under tags -> actions -> data -> value.
        Walking defensively (instead of hardcoding one exact tag/action name)
        keeps this resilient to the minor schema variations Microsoft ships
        across API versions.
        """
        for tag in data.get("tags", []) or []:
            for action in tag.get("actions", []) or []:
                values = (action.get("data") or {}).get("value") or []
                for item in values:
                    host_page_url = item.get("hostPageUrl") or item.get("contentUrl")
                    if not host_page_url:
                        continue
                    title = item.get("name", "")
                    domain = item.get("hostPageDomainFriendlyName")
                    yield host_page_url, title, domain
