"""Public YouTube discovery and observed Scholar profiles, complementary to GHunt."""
import asyncio
from collections import Counter
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.google_profiles import observe_scholar, scholar_url, youtube_initial_data
from app.tools.social_profiles import parse_social_profile

ENGINE_VERSION = 2


class GoogleAccountOSINTTool(BaseTool):
    name = "google_account_osint"
    description = (
        "Descubre canales candidatos de YouTube y busca autores en Google Scholar; "
        "lee perfiles Scholar públicos por URL/ID y recupera métricas del propio autor. "
        "La existencia del perfil no confirma que pertenezca al objetivo. GHunt consulta la cuenta Google."
    )
    category = ToolCategory.EMAIL
    required_inputs = ["email", "username", "full_name", "candidate_urls"]
    cache_prefix = "google_public_"

    def _query(self, context):
        return context.full_name or next(iter(context.all_usernames()), "") or next(
            (email.split("@", 1)[0] for email in context.all_emails() if "@" in email), "")

    def can_run(self, context):
        if context.extra.get("google_public_version") != ENGINE_VERSION:
            return bool(self._query(context) or any(scholar_url(url) for url in context.extra.get("candidate_urls", [])))
        profiles = context.extra.get("google_public_scholar_profiles", {})
        if len(profiles) < 3 and any(scholar_url(url) and scholar_url(url) not in profiles for url in context.extra.get("candidate_urls", [])):
            return True
        checked = context.extra.get("google_public_checked", [])
        scholar_key = "scholar:" + (context.full_name or "") + ":" + (context.university or "")
        searched = context.extra.get("google_public_youtube_queries", [])
        query = self._query(context)
        return bool((context.full_name and scholar_key not in checked and len(checked) < 3)
                    or (query and query not in searched and len(searched) < 3))

    def _record(self, context, endpoint, status, **values):
        context.extra.setdefault("google_public_diagnostics", []).append({"endpoint": endpoint, "status": status, **values})

    async def _get(self, client, url, context, endpoint):
        try:
            response = await client.get(url)
            code = response.status_code
            if code != 200:
                status = "blocked" if code in {401, 403, 429} else "not_found" if code in {404, 410} else "redirected" if 300 <= code < 400 else "upstream_error"
                self._record(context, endpoint, status, http_status=code)
                return None
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
            if any(marker in title for marker in ("captcha", "access denied", "just a moment", "sorry")) or "/sorry/" in str(response.url):
                self._record(context, endpoint, "blocked", http_status=code)
                return None
            return response
        except Exception as exc:
            self._record(context, endpoint, "request_error", error_type=type(exc).__name__)
            return None

    async def execute(self, context: TargetContext):
        if context.extra.get("google_public_version") != ENGINE_VERSION:
            for key in list(context.extra):
                if key.startswith(self.cache_prefix):
                    context.extra.pop(key)
            context.extra["google_public_version"] = ENGINE_VERSION
        findings = []
        async with http_client.build_client(timeout=10, public_only=True, follow_redirects=False,
                rotate_ua=False, max_retries=0, trust_env=False) as client:
            try:
                async with asyncio.timeout(60):
                    for raw in context.extra.get("candidate_urls", []):
                        url = scholar_url(raw)
                        if url:
                            observed = await self._scholar_profile(client, url, context)
                            if observed:
                                findings.append(observed)
                    checked = context.extra.setdefault("google_public_checked", [])
                    key = "scholar:" + (context.full_name or "") + ":" + (context.university or "")
                    if context.full_name and key not in checked and len(checked) < 3:
                        checked.append(key)
                        findings.extend(await self._search_scholar(client, context))
                    query = self._query(context)
                    searched = context.extra.setdefault("google_public_youtube_queries", [])
                    if query and query not in searched and len(searched) < 3:
                        searched.append(query)
                        findings.extend(await self._search_youtube_channel(client, query, context))
            except TimeoutError:
                self._record(context, "batch", "budget_exhausted")
        return findings

    async def _search_youtube_channel(self, client, username_part, context):
        query = context.full_name or username_part
        response = await self._get(client, "https://www.youtube.com/results?search_query=" + quote_plus(query) + "&sp=EgIQAg%3D%3D", context, "youtube_search")
        if response is None:
            return []
        data = youtube_initial_data(BeautifulSoup(response.text, "html.parser"))
        if not data:
            self._record(context, "youtube_search", "unexpected_response")
            return []
        sections = data
        for key in ("contents", "twoColumnSearchResultsRenderer", "primaryContents", "sectionListRenderer", "contents"):
            sections = sections.get(key) if isinstance(sections, dict) else None
        if not isinstance(sections, list):
            self._record(context, "youtube_search", "unexpected_response")
            return []
        findings, seen = [], set()
        for section in sections:
            renderer = section.get("itemSectionRenderer") if isinstance(section, dict) else None
            items = renderer.get("contents") if isinstance(renderer, dict) else None
            if not isinstance(items, list):
                continue
            for item in items:
                channel = item.get("channelRenderer") if isinstance(item, dict) else None
                if not isinstance(channel, dict):
                    continue
                profile = parse_social_profile("https://youtube.com/channel/" + str(channel.get("channelId", "")))
                if not profile or profile.url in seen or len(seen) >= 3:
                    continue
                title_data = channel.get("title", {})
                title_data = title_data if isinstance(title_data, dict) else {}
                title = title_data.get("simpleText")
                if not isinstance(title, str):
                    runs = title_data.get("runs", [])
                    title = "".join(run["text"] for run in runs if isinstance(run, dict) and isinstance(run.get("text"), str)) if isinstance(runs, list) else ""
                seen.add(profile.url)
                findings.append(ToolFinding(entity_type="social_account", platform="youtube", value=profile.url,
                    display_name=title or profile.username, confidence=0.4,
                    metadata_info={"source_tool": self.name, "technique": "youtube_channel_search", "query": query,
                        "channel_id": profile.username, "resource_kind": "channel_id", "url": profile.url,
                        "verification_status": "candidate", "ownership_status": "unverified"}, evidence_urls=[str(response.url)]))
        self._record(context, "youtube_search", "candidates" if findings else "no_candidates", count=len(findings))
        return findings

    async def _scholar_profile(self, client, url, context, fallback_name=None):
        checked = context.extra.setdefault("google_public_scholar_profiles", {})
        if url in checked or len(checked) >= 3:
            return None
        checked[url] = "pending"
        response = await self._get(client, url + "&hl=en", context, "scholar_profile")
        data = observe_scholar(response.text, url) if response is not None else {
            "status": context.extra.get("google_public_diagnostics", [{}])[-1].get("status", "request_failed")}
        checked[url] = data["status"]
        if response is not None:
            self._record(context, "scholar_profile", data["status"])
        if data["status"] != "observed" and not fallback_name:
            return None
        observed = data["status"] == "observed"
        metadata = {"source_tool": self.name, "url": url, "profile_url": url, "query_name": context.full_name,
            "technique": "scholar_author_profile" if observed else "scholar_author_search",
            "verification_status": "verified" if observed else "candidate", "ownership_status": "unverified",
            "profile_status": data.pop("status"), **(data if observed else {})}
        return ToolFinding(entity_type="academic_profile", platform="google_scholar", value=url,
            display_name=data.get("author_name") or fallback_name, confidence=0.6 if observed else 0.4,
            metadata_info=metadata, evidence_urls=[url])

    async def _search_scholar(self, client, context):
        query = context.full_name or ""
        if context.university:
            query += " " + context.university
        response = await self._get(client, "https://scholar.google.com/citations?view_op=search_authors&mauthors=" + quote_plus(query) + "&hl=en", context, "scholar_search")
        if response is None:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(".gs_ai_chpr, .gsc_1usr")
        findings, seen = [], set()
        for card in cards:
            anchor = card.select_one("h3 a[href], .gs_ai_name a[href]")
            url = scholar_url(urljoin("https://scholar.google.com", anchor.get("href", ""))) if anchor else None
            if not url or url in seen or len(seen) >= 2:
                continue
            seen.add(url)
            finding = await self._scholar_profile(client, url, context, anchor.get_text(" ", strip=True))
            if finding:
                findings.append(finding)
        self._record(context, "scholar_search", "candidates" if findings else "no_candidates" if cards else "unexpected_response", count=len(findings))
        return findings


def execution_summary(context):
    return {"engine_version": ENGINE_VERSION,
            "statuses": dict(Counter(item["status"] for item in context.extra.get("google_public_diagnostics", []))),
            "scholar_profiles": dict(context.extra.get("google_public_scholar_profiles", {}))}
