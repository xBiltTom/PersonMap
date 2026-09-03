import asyncio
from typing import Dict, List
import httpx
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


# Curated high-value platforms (WhatsMyName / Sherlock inspired)
PLATFORMS: Dict[str, Dict[str, str]] = {
    "github": {
        "url": "https://github.com/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "gitlab": {
        "url": "https://gitlab.com/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "reddit": {
        "url": "https://www.reddit.com/user/{username}/about.json",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "telegram": {
        "url": "https://t.me/{username}",
        "check_type": "content_check",
        "missing_string": "If you have <strong>Telegram</strong>, you can contact",
    },
    "devto": {
        "url": "https://dev.to/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "medium": {
        "url": "https://medium.com/@{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "pinterest": {
        "url": "https://www.pinterest.com/{username}/",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "steam": {
        "url": "https://steamcommunity.com/id/{username}",
        "check_type": "content_check",
        "missing_string": "The specified profile could not be found",
    },
    "twitch": {
        "url": "https://www.twitch.tv/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "spotify": {
        "url": "https://open.spotify.com/user/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "hackerrank": {
        "url": "https://www.hackerrank.com/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "leetcode": {
        "url": "https://leetcode.com/{username}/",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "chess_com": {
        "url": "https://api.chess.com/pub/player/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "instagram": {
        "url": "https://www.instagram.com/{username}/",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "x_twitter": {
        "url": "https://x.com/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "tiktok": {
        "url": "https://www.tiktok.com/@{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "behance": {
        "url": "https://www.behance.net/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "soundcloud": {
        "url": "https://soundcloud.com/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "duolingo": {
        "url": "https://www.duolingo.com/profile/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
    "codeforces": {
        "url": "https://codeforces.com/profile/{username}",
        "check_type": "status_code",
        "valid_code": 200,
    },
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


class UsernameFinderTool(BaseTool):
    name = "username_finder"
    description = (
        "Busca perfiles y cuentas asociadas a un nombre de usuario / alias "
        "en más de 20 plataformas sociales, de desarrollo y académicas."
    )
    category = ToolCategory.USERNAME
    required_inputs = ["username", "discovered_usernames"]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        usernames = context.all_usernames()
        if not usernames:
            return []

        findings: List[ToolFinding] = []
        semaphore = asyncio.Semaphore(10)

        async with httpx.AsyncClient(headers=HEADERS, timeout=8.0, follow_redirects=True) as client:
            tasks = []
            for u in usernames:
                for platform, config in PLATFORMS.items():
                    tasks.append(self._check_platform(client, semaphore, u, platform, config))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, ToolFinding):
                    findings.append(res)

        return findings

    async def _check_platform(
        self,
        client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
        username: str,
        platform: str,
        config: Dict[str, str],
    ) -> ToolFinding | None:
        url = config["url"].format(username=username)
        async with semaphore:
            try:
                resp = await client.get(url)
                check_type = config.get("check_type", "status_code")

                if check_type == "status_code":
                    if resp.status_code == config.get("valid_code", 200):
                        return ToolFinding(
                            entity_type="social_account",
                            platform=platform,
                            value=url,
                            display_name=username,
                            metadata_info={"username": username, "status_code": resp.status_code, "profile_url": url},
                            confidence=0.65,
                            evidence_urls=[url],
                        )
                elif check_type == "content_check":
                    missing = config.get("missing_string", "")
                    if resp.status_code == 200 and missing not in resp.text:
                        return ToolFinding(
                            entity_type="social_account",
                            platform=platform,
                            value=url,
                            display_name=username,
                            metadata_info={"username": username, "profile_url": url},
                            confidence=0.65,
                            evidence_urls=[url],
                        )
            except Exception:
                return None
        return None
