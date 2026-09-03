import re
from typing import Any, Dict, List, Optional
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class SocialUrlExtractorTool(BaseTool):
    """
    Zero-network regex parsing tool adapted from Spiderfoot's sfp_social.
    Parses candidate URLs from web scraping/dorks to extract canonical platform usernames
    and feed them into the automated pivoting pipeline.
    """

    name = "social_url_extractor"
    description = "Extracción pasiva de alias y perfiles sociales a partir de URLs candidatas (regex de alta precisión)"
    category = ToolCategory.SOCIAL
    required_inputs = ["candidate_urls"]

    REGEX_PATTERNS: Dict[str, str] = {
        "linkedin": r"linkedin\.com/in/([a-zA-Z0-9_-]+)",
        "github": r"github\.com/([a-zA-Z0-9_-]+)(?:/|$)",
        "gitlab": r"gitlab\.com/([a-zA-Z0-9_.-]+)(?:/|$)",
        "bitbucket": r"bitbucket\.org/([a-zA-Z0-9_-]+)(?:/|$)",
        "twitter": r"(?:twitter|x)\.com/([a-zA-Z0-9_]{1,15})(?:/|$)",
        "instagram": r"instagram\.com/([a-zA-Z0-9_.]+)(?:/|$)",
        "facebook": r"facebook\.com/([a-zA-Z0-9_.]+)(?:/|$)",
        "telegram": r"t\.me/([a-zA-Z0-9_]{5,32})(?:/|$)",
        "reddit": r"reddit\.com/u(?:ser)?/([a-zA-Z0-9_-]+)",
        "medium": r"medium\.com/@([a-zA-Z0-9_.]+)",
        "youtube": r"youtube\.com/(?:@|c/|user/)([a-zA-Z0-9_-]+)",
        "tiktok": r"tiktok\.com/@([a-zA-Z0-9_.]+)",
        "steam": r"steamcommunity\.com/id/([a-zA-Z0-9_-]+)",
        "pinterest": r"pinterest\.com/([a-zA-Z0-9_]+)(?:/|$)",
        "soundcloud": r"soundcloud\.com/([a-zA-Z0-9_-]+)(?:/|$)",
        "twitch": r"twitch\.tv/([a-zA-Z0-9_]+)(?:/|$)",
        "devto": r"dev\.to/([a-zA-Z0-9_-]+)",
        "stackoverflow": r"stackoverflow\.com/users/\d+/([a-zA-Z0-9_-]+)",
    }

    def can_run(self, context: TargetContext) -> bool:
        candidate_urls = context.extra.get("candidate_urls", [])
        return len(candidate_urls) > 0

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        candidate_urls = context.extra.get("candidate_urls", [])

        for raw_url in candidate_urls:
            url = str(raw_url).strip()
            for platform, pattern in self.REGEX_PATTERNS.items():
                match = re.search(pattern, url, re.IGNORECASE)
                if match:
                    username = match.group(1).strip()
                    # Skip common false positives
                    if username.lower() in ["home", "login", "signup", "explore", "about", "terms", "privacy", "in"]:
                        continue

                    findings.append(
                        ToolFinding(
                            entity_type="social_account",
                            platform=platform,
                            value=url,
                            display_name=f"{platform.capitalize()}: @{username}",
                            confidence=0.88,
                            metadata_info={
                                "source_tool": "social_url_extractor",
                                "platform": platform,
                                "username": username,
                                "url": url,
                                "usernames": [username],  # Feeds into heuristic pivoting
                            },
                        )
                    )
                    break

        return findings
