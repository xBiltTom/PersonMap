from typing import List, Set
import httpx
from app.tools import http_client
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

        async with http_client.build_client(timeout=10.0, rotate_ua=False, headers=HEADERS) as client:
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

            # Inspect public events / commits for author emails and schedule analysis
            events_url = f"https://api.github.com/users/{username}/events/public"
            events_resp = await client.get(events_url)
            commit_hours = []
            commit_days = []
            active_repos = set()

            if events_resp.status_code == 200:
                events_data = events_resp.json()
                for event in events_data[:25]:
                    created_at = event.get("created_at")
                    if created_at:
                        try:
                            from datetime import datetime
                            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                            commit_hours.append(dt.hour)
                            commit_days.append(dt.strftime("%A"))
                        except Exception:
                            pass

                    if event.get("type") == "PushEvent":
                        repo_name = event.get("repo", {}).get("name")
                        if repo_name:
                            active_repos.add(repo_name)

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

            # Analyze active schedule if commits were found
            schedule_meta = {}
            if commit_hours:
                from collections import Counter
                hour_dist = Counter(commit_hours)
                peak_hour_utc = hour_dist.most_common(1)[0][0]
                # Inferred local timezone assuming typical peak programming between 19:00 - 23:00
                inferred_tz = f"UTC{peak_hour_utc - 21:+d}" if -12 <= (peak_hour_utc - 21) <= 14 else "UTC"
                schedule_meta = {
                    "peak_hour_utc": peak_hour_utc,
                    "hour_distribution": dict(sorted(hour_dist.items())),
                    "inferred_active_hours": f"{peak_hour_utc}:00 UTC",
                    "inferred_timezone_hint": inferred_tz,
                    "recent_active_repos": list(active_repos)[:5],
                }

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
                "schedule_analysis": schedule_meta,
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
