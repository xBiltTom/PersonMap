import re
from typing import List
from urllib.parse import quote_plus, unquote
from bs4 import BeautifulSoup
import httpx
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class SearchDorkerTool(BaseTool):
    name = "search_dorker"
    description = (
        "Genera y ejecuta dorks de búsqueda contextuales en la web pública "
        "(LinkedIn, Instagram, GitHub, repositorios) sin necesidad de API keys."
    )
    category = ToolCategory.SEARCH
    required_inputs = ["full_name", "username", "email", "dni"]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        queries = self._generate_queries(context)
        if not queries:
            return []

        findings: List[ToolFinding] = []

        async with http_client.build_client(timeout=12.0, headers=HEADERS) as client:
            for q in queries[:4]:  # Top 4 targeted queries to avoid aggressive rate limiting
                results = await self._search_duckduckgo(client, q)
                findings.extend(results)

        return findings

    def _generate_queries(self, context: TargetContext) -> List[str]:
        queries = []
        name = context.full_name.strip() if context.full_name else ""
        uni = context.university.strip() if context.university else ""
        username = context.username.strip() if context.username else ""
        email = context.email.strip() if context.email else ""
        dni = context.dni.strip() if context.dni else ""

        if name and uni:
            queries.append(f'"{name}" "{uni}"')
            queries.append(f'"{name}" site:linkedin.com/in/')
        elif name:
            queries.append(f'"{name}"')
            queries.append(f'"{name}" site:linkedin.com/in/')

        if username:
            queries.append(f'"{username}"')

        if email:
            queries.append(f'"{email}"')

        if dni:
            queries.append(f'"{dni}"')

        return queries

    async def _search_duckduckgo(self, client: httpx.AsyncClient, query: str) -> List[ToolFinding]:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        findings: List[ToolFinding] = []

        try:
            resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            results = soup.find_all("div", class_="result")

            for r in results[:5]:  # Top 5 per query
                title_tag = r.find("a", class_="result__a")
                snippet_tag = r.find("a", class_="result__snippet")
                if not title_tag:
                    continue

                raw_url = title_tag.get("href", "")
                # DuckDuckGo wraps URLs in uddg=...
                actual_url = raw_url
                if "uddg=" in raw_url:
                    match = re.search(r"uddg=([^&]+)", raw_url)
                    if match:
                        actual_url = unquote(match.group(1))

                title = title_tag.get_text(strip=True)
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

                # Platform detection
                platform = "web_search"
                if "linkedin.com" in actual_url:
                    platform = "linkedin"
                elif "github.com" in actual_url:
                    platform = "github"
                elif "instagram.com" in actual_url:
                    platform = "instagram"
                elif "facebook.com" in actual_url:
                    platform = "facebook"
                elif "twitter.com" in actual_url or "x.com" in actual_url:
                    platform = "x_twitter"

                findings.append(
                    ToolFinding(
                        entity_type="search_mention",
                        platform=platform,
                        value=actual_url,
                        display_name=title,
                        metadata_info={
                            "snippet": snippet,
                            "query": query,
                            "url": actual_url,
                        },
                        confidence=0.60,
                        evidence_urls=[actual_url],
                    )
                )
        except Exception:
            return []

        return findings
