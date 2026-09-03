from typing import Any, Dict, List, Optional
import httpx
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class WikipediaEditsTool(BaseTool):
    """
    Wikipedia Edits OSINT Tool adapted from Spiderfoot's sfp_wikipediaedits.
    Searches the official MediaWiki API to identify edits and contributions
    made by a target username across Wikipedia articles, surfacing personal interests,
    hobbies, and geographical/academic affiliations.
    """

    name = "wikipedia_edits"
    description = "Historial de ediciones públicas en Wikipedia por alias (MediaWiki API)"
    category = ToolCategory.SOCIAL
    required_inputs = ["username"]

    API_URL = "https://en.wikipedia.org/w/api.php"

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        usernames = context.all_usernames()
        if not usernames:
            return findings

        headers = {
            "User-Agent": "PersonMap-OSINT-AcademicResearch/1.0 (https://github.com/xBiltTom/PersonMap; contact@example.com)",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers, verify=False) as client:
            for username in usernames:
                clean_user = username.strip()
                if len(clean_user) < 3:
                    continue

                params = {
                    "action": "query",
                    "list": "usercontribs",
                    "ucuser": clean_user,
                    "uclimit": 15,
                    "ucprop": "title|timestamp|comment|sizediff",
                    "format": "json",
                }

                try:
                    resp = await client.get(self.API_URL, params=params)
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    contribs = data.get("query", {}).get("usercontribs", [])
                    if not contribs:
                        continue

                    articles = list(dict.fromkeys(c.get("title") for c in contribs if c.get("title")))
                    latest_timestamp = contribs[0].get("timestamp")

                    profile_url = f"https://en.wikipedia.org/wiki/Special:Contributions/{clean_user}"
                    findings.append(
                        ToolFinding(
                            entity_type="social_account",
                            platform="wikipedia",
                            value=profile_url,
                            display_name=f"Wikipedia Editor: @{clean_user} ({len(contribs)} contribuciones)",
                            confidence=0.88,
                            metadata_info={
                                "source_tool": "wikipedia_edits",
                                "username": clean_user,
                                "contributions_count": len(contribs),
                                "edited_articles": articles[:8],
                                "latest_edit": latest_timestamp,
                                "url": profile_url,
                            },
                        )
                    )

                except Exception:
                    continue

        return findings
