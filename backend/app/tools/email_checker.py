import hashlib
import json
from typing import List
import httpx
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


class EmailCheckerTool(BaseTool):
    name = "email_checker"
    description = (
        "Verifica registros pasivos asociados a direcciones de correo electrónico "
        "(Gravatar, GitHub, perfiles públicos y servicios web)."
    )
    category = ToolCategory.EMAIL
    required_inputs = ["email", "discovered_emails"]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        emails = context.all_emails()
        if not emails:
            return []

        findings: List[ToolFinding] = []

        async with httpx.AsyncClient(headers=HEADERS, timeout=8.0, follow_redirects=True) as client:
            for email in emails:
                # 1. Check Gravatar
                gravatar_finding = await self._check_gravatar(client, email)
                if gravatar_finding:
                    findings.append(gravatar_finding)

                # 2. Check GitHub API for email commit attribution
                gh_finding = await self._check_github_email(client, email)
                if gh_finding:
                    findings.append(gh_finding)

                # 3. Add base email entity finding
                domain = email.split("@")[-1] if "@" in email else ""
                is_academic = any(d in domain.lower() for d in [".edu", ".ac.", "uni.", "unmsm.", "pucp.", "unt.", "utp."])
                findings.append(
                    ToolFinding(
                        entity_type="email",
                        platform="mail_provider",
                        value=email,
                        display_name=email,
                        metadata_info={
                            "domain": domain,
                            "is_academic": is_academic,
                            "email": email,
                        },
                        confidence=1.0,
                        evidence_urls=[f"mailto:{email}"],
                    )
                )

        return findings

    async def _check_gravatar(self, client: httpx.AsyncClient, email: str) -> ToolFinding | None:
        email_hash = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
        url = f"https://en.gravatar.com/{email_hash}.json"
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                entry = data.get("entry", [{}])[0]
                display_name = entry.get("displayName") or entry.get("preferredUsername")
                preferred_username = entry.get("preferredUsername")
                avatar = entry.get("thumbnailUrl")
                about_me = entry.get("aboutMe")

                # Extract linked accounts
                verified_accounts = entry.get("verifiedAccounts", [])
                links = [acc.get("url") for acc in verified_accounts if acc.get("url")]

                metadata = {
                    "gravatar_profile": f"https://gravatar.com/{preferred_username or email_hash}",
                    "avatar_url": avatar,
                    "bio": about_me,
                    "usernames": [preferred_username] if preferred_username else [],
                    "linked_profiles": links,
                    "email_matched": email,
                }

                return ToolFinding(
                    entity_type="social_account",
                    platform="gravatar",
                    value=metadata["gravatar_profile"],
                    display_name=display_name or email,
                    metadata_info=metadata,
                    confidence=0.95,
                    evidence_urls=[url],
                )
        except Exception:
            return None
        return None

    async def _check_github_email(self, client: httpx.AsyncClient, email: str) -> ToolFinding | None:
        url = f"https://api.github.com/search/users?q={email}+in:email"
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("total_count", 0) > 0:
                    user = data["items"][0]
                    login = user.get("login")
                    profile_url = user.get("html_url")
                    avatar_url = user.get("avatar_url")
                    return ToolFinding(
                        entity_type="social_account",
                        platform="github",
                        value=profile_url,
                        display_name=login,
                        metadata_info={
                            "username": login,
                            "avatar_url": avatar_url,
                            "profile_url": profile_url,
                            "emails": [email],
                            "usernames": [login],
                        },
                        confidence=0.90,
                        evidence_urls=[profile_url],
                    )
        except Exception:
            return None
        return None
