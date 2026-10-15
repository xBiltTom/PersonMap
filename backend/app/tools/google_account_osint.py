import re
import json
from bs4 import BeautifulSoup
from app.tools.social_profiles import parse_social_profile
from typing import Any, Dict, List
from urllib.parse import quote_plus

from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class GoogleAccountOSINTTool(BaseTool):
    """Public YouTube/Scholar discovery, complementary to native GHunt.

    The former account-lookup heuristic was removed: a generic login HTML
    response must never become proof of account existence. Authentication and
    exact Google lookups belong to the isolated GHuntTool.
    """

    name = "google_account_osint"
    description = (
        "Busca canales candidatos de YouTube por nombre o alias, sin API keys; "
        "también busca perfiles candidatos de Scholar por nombre. GHunt realiza las consultas de cuenta."
    )
    category = ToolCategory.EMAIL
    required_inputs = ["email", "username", "full_name"]
    cache_prefix = "google_public_"

    GOOGLE_DOMAINS = {"gmail.com", "googlemail.com", "google.com"}

    def can_run(self, context: TargetContext) -> bool:
        if context.full_name or context.all_usernames():
            return True
        for email in context.all_emails():
            if "@" not in email:
                continue
            domain = email.split("@", 1)[1].lower()
            if domain in self.GOOGLE_DOMAINS or domain.endswith(".edu") or domain.endswith(".edu.pe"):
                return True
        return False

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        emails = context.all_emails()
        async with http_client.build_client(timeout=10.0) as client:
            # Scholar depends on a name, not the presence or number of Gmail
            # addresses. Preserve its independent public discovery role.
            scholar_key = "scholar:" + (context.full_name or "") + ":" + (context.university or "")
            checked = context.extra.setdefault("google_public_checked", [])
            if context.full_name and scholar_key not in checked:
                checked.append(scholar_key)
                findings.extend(await self._search_scholar(client, context))

            query = context.full_name or next(iter(context.all_usernames()), "")
            if not query and emails:
                query = emails[0].split("@", 1)[0]
            searched = context.extra.setdefault("google_public_youtube_queries", [])
            if query and query not in searched and len(searched) < 3:
                searched.append(query)
                findings.extend(await self._search_youtube_channel(client, query, context))
        return findings

    async def _search_youtube_channel(
        self, client: Any, username_part: str, context: TargetContext
    ) -> List[ToolFinding]:
        """
        Searches public YouTube /results for channels matching the target.
        Uses the Channel-type filter (sp=EgIQAg==). No API key required.
        """
        findings: List[ToolFinding] = []
        query = context.full_name or username_part
        try:
            resp = await http_client.get(
                client,
                f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=EgIQAg%3D%3D",
                headers={"Accept-Language": "es-ES,es;q=0.9"},
            )
            if resp is None or resp.status_code != 200:
                return []

            # Parse actual channel-result renderers, not URLs from navigation or ads.
            soup = BeautifulSoup(resp.text, "html.parser")
            data = None
            for script in soup.find_all("script"):
                text = script.string or script.get_text()
                match = re.search(r"(?:var\s+ytInitialData\s*=|window\[\"ytInitialData\"\]\s*=)\s*", text)
                if match:
                    try:
                        data, _ = json.JSONDecoder().raw_decode(text[match.end():])
                        break
                    except ValueError:
                        continue
            if not isinstance(data, dict):
                return []
            sections = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {}).get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
            seen = set()
            for section in sections:
                for item in section.get("itemSectionRenderer", {}).get("contents", []):
                    channel = item.get("channelRenderer", {})
                    channel_id = channel.get("channelId", "")
                    profile = parse_social_profile(f"https://youtube.com/channel/{channel_id}")
                    if not profile or profile.url in seen or len(seen) >= 3:
                        continue
                    title_data = channel.get("title", {})
                    title = title_data.get("simpleText") or "".join(run.get("text", "") for run in title_data.get("runs", []))
                    seen.add(profile.url)
                    findings.append(ToolFinding(
                        entity_type="social_account", platform="youtube", value=profile.url,
                        display_name=title or channel_id, confidence=0.4,
                        metadata_info={"source_tool": self.name, "technique": "youtube_channel_search",
                                       "query": query, "channel_id": channel_id, "resource_kind": "channel_id",
                                       "url": profile.url, "verification_status": "candidate"},
                        evidence_urls=[str(resp.url)],
                    ))
        except Exception:
            pass
        return findings

    async def _search_scholar(
        self, client: Any, context: TargetContext
    ) -> List[ToolFinding]:
        """
        Searches Google Scholar for the target's academic profile.
        Returns citation count, institution and profile URL.
        Uses the public Scholar author search (no API key required).
        """
        findings: List[ToolFinding] = []
        name = context.full_name or ""
        if not name:
            return []

        query_parts = [f'"{name}"']
        if context.university:
            query_parts.append(context.university)
        query = " ".join(query_parts)

        try:
            resp = await http_client.get(
                client,
                f"https://scholar.google.com/scholar?q={quote_plus(query)}&hl=es",
                headers={"Accept": "text/html", "Accept-Language": "es-ES,es;q=0.9"},
            )
            if resp is None or resp.status_code != 200:
                return []

            body = resp.text
            profile_urls = re.findall(
                r'href="(/citations[?](?:hl=es&amp;)?user=[A-Za-z0-9_-]+[^"]*)"', body
            )
            cite_matches = re.findall(r'Citado por (\d+)', body)

            for i, raw_path in enumerate(profile_urls[:2]):
                clean_path = raw_path.replace("&amp;", "&")
                full_url = f"https://scholar.google.com{clean_path}"
                citations = cite_matches[i] if i < len(cite_matches) else None
                meta: Dict[str, Any] = {
                    "source_tool": "google_account_osint",
                    "technique": "scholar_author_search",
                    "query": query,
                    "url": full_url,
                    "verification_status": "candidate",
                    "ownership_status": "unverified",
                }
                if citations:
                    meta["citations"] = int(citations)

                findings.append(ToolFinding(
                    entity_type="academic_profile",
                    platform="google_scholar",
                    value=full_url,
                    display_name=f"Google Scholar: {name}" + (f" ({citations} citas)" if citations else ""),
                    confidence=0.70,
                    metadata_info=meta,
                    evidence_urls=[full_url],
                ))
        except Exception:
            pass
        return findings
