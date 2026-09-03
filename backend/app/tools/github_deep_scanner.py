from typing import List, Set
import httpx
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


HEADERS = {
    "User-Agent": "person-map-forensic-scanner/1.0",
    "Accept": "application/vnd.github.v3+json",
}


class GitHubDeepScannerTool(BaseTool):
    name = "github_deep_scanner"
    description = (
        "Inspecciona a fondo perfiles públicos de GitHub: analiza commits públicos para "
        "descubrir correos ocultos de autoría git, repositorios de tareas y lenguajes utilizados."
    )
    category = ToolCategory.SOCIAL
    required_inputs = ["username", "discovered_usernames"]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        usernames = context.all_usernames()
        if not usernames:
            return []

        findings: List[ToolFinding] = []

        async with httpx.AsyncClient(headers=HEADERS, timeout=10.0) as client:
            for username in usernames:
                result = await self._scan_github_profile(client, username)
                if result:
                    findings.append(result)

        return findings

    async def _scan_github_profile(
        self, client: httpx.AsyncClient, username: str
    ) -> ToolFinding | None:
        user_url = f"https://api.github.com/users/{username}"
        try:
            resp = await client.get(user_url)
            if resp.status_code != 200:
                return None

            user_data = resp.json()
            bio = user_data.get("bio") or ""
            name = user_data.get("name") or username
            public_repos = user_data.get("public_repos", 0)
            avatar_url = user_data.get("avatar_url")
            html_url = user_data.get("html_url")
            blog = user_data.get("blog") or ""
            company = user_data.get("company") or ""
            location = user_data.get("location") or ""

            discovered_emails: Set[str] = set()
            if user_data.get("email"):
                discovered_emails.add(user_data["email"].lower())

            # Inspect public events / commits for author emails
            events_url = f"https://api.github.com/users/{username}/events/public"
            events_resp = await client.get(events_url)
            if events_resp.status_code == 200:
                events_data = events_resp.json()
                for event in events_data[:15]:
                    if event.get("type") == "PushEvent":
                        commits = event.get("payload", {}).get("commits", [])
                        for commit in commits:
                            author_email = commit.get("author", {}).get("email", "")
                            if (
                                author_email
                                and "users.noreply.github.com" not in author_email
                                and "@" in author_email
                            ):
                                discovered_emails.add(author_email.lower())

            emails_list = list(discovered_emails)

            metadata = {
                "username": username,
                "name": name,
                "bio": bio,
                "location": location,
                "company_university": company,
                "website": blog,
                "public_repos": public_repos,
                "avatar_url": avatar_url,
                "emails": emails_list,
                "extracted_emails": emails_list,
                "profile_url": html_url,
            }

            return ToolFinding(
                entity_type="social_account",
                platform="github",
                value=html_url,
                display_name=f"{name} (@{username})",
                metadata_info=metadata,
                confidence=0.95,
                evidence_urls=[html_url],
            )
        except Exception:
            return None
