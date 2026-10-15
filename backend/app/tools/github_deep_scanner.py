from typing import Dict, List, Set
import re
import httpx
from app.core.config import settings
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
    cache_prefix = "github_"

    # Repositorios propios cuyos commits se leen para sacar el correo de autoría.
    # Sin token la API permite 60 peticiones por hora: con 3 repos cada perfil
    # cuesta 6 (usuario, eventos, repos y 3 listados de commits).
    MAX_REPOS_FOR_EMAILS = 3

    def _pending_usernames(self, context):
        checked = set(context.extra.get("github_checked_usernames", []))
        if len(checked) >= max(0, settings.username_scan_max_aliases):
            return []
        return list(dict.fromkeys(username for username in context.all_usernames()
                                 if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", username)
                                 and username.casefold() not in checked))[:settings.username_scan_max_aliases]

    def can_run(self, context: TargetContext) -> bool:
        return bool(self._pending_usernames(context))

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        usernames = self._pending_usernames(context)
        if not usernames:
            return []

        findings: List[ToolFinding] = []

        headers = {**HEADERS, "X-GitHub-Api-Version": "2022-11-28"}
        if settings.github_api_token:
            headers["Authorization"] = f"Bearer {settings.github_api_token.get_secret_value()}"
        checked = context.extra.setdefault("github_checked_usernames", [])
        async with http_client.build_client(timeout=10.0, rotate_ua=False, max_retries=0,
                                            follow_redirects=False, headers=headers) as client:
            for username in usernames:
                if username.casefold() in checked or len(checked) >= max(0, settings.username_scan_max_aliases):
                    continue
                checked.append(username.casefold())
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
            # Vacío si el perfil no declara nombre. Antes se rellenaba con el
            # login, y el modelo de identidad lo leía como un nombre que no
            # coincidía con el de la persona.
            name = user_data.get("name") or ""
            public_repos = user_data.get("public_repos", 0)
            avatar_url = user_data.get("avatar_url")
            html_url = user_data.get("html_url")
            blog = user_data.get("blog") or ""
            company = user_data.get("company") or ""
            location = user_data.get("location") or ""

            discovered_emails: Set[str] = set()
            if user_data.get("email"):
                discovered_emails.add(user_data["email"].lower())

            email_evidence = await self._commit_author_emails(client, username)
            discovered_emails.update(email_evidence)

            # Eventos públicos: horario de actividad y repositorios recientes.
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

            emails_list = list(discovered_emails)

            # Analyze active schedule if commits were found
            schedule_meta = {}
            if commit_hours:
                from collections import Counter
                hour_dist = Counter(commit_hours)
                peak_hour_utc = hour_dist.most_common(1)[0][0]
                schedule_meta = {
                    "peak_hour_utc": peak_hour_utc,
                    "hour_distribution": dict(sorted(hour_dist.items())),
                    "inferred_active_hours": f"{peak_hour_utc}:00 UTC",
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
                "profile_email": user_data.get("email"),
                "extracted_emails": emails_list,
                # Un commit concreto por correo: es la prueba que se puede abrir
                # delante de la persona si dice "esa cuenta no es mía".
                "email_evidence": list(email_evidence.values()),
                "profile_url": html_url,
                "schedule_analysis": schedule_meta,
            }

            return ToolFinding(
                entity_type="social_account",
                platform="github",
                value=html_url,
                display_name=f"{name} (@{username})" if name else f"@{username}",
                metadata_info=metadata,
                confidence=0.95,
                evidence_urls=[html_url, *(ev["commit_url"] for ev in email_evidence.values())],
            )
        except Exception:
            return None

    async def _commit_author_emails(
        self, client: httpx.AsyncClient, username: str
    ) -> Dict[str, Dict[str, str]]:
        """
        Correos con los que la persona firma sus commits, cada uno con el primer
        commit que lo muestra.

        Antes se leían de `payload.commits` en los eventos públicos, pero GitHub
        ya no incluye los commits en esa API: medido sobre un perfil real con 4
        PushEvent, ninguno los traía y el escáner nunca encontraba un correo. Los
        commits de sus propios repositorios, filtrados por autor, sí lo traen.
        Es la evidencia más fuerte que da GitHub: el correo de autoría git lo
        configura la propia persona.
        """
        evidence: Dict[str, Dict[str, str]] = {}
        repos_resp = await client.get(
            f"https://api.github.com/users/{username}/repos",
            params={"per_page": 30, "sort": "pushed", "type": "owner"},
        )
        if repos_resp.status_code != 200:
            return evidence

        own_repos = [
            repo["full_name"]
            for repo in repos_resp.json()
            if isinstance(repo, dict) and repo.get("full_name") and not repo.get("fork") and not repo.get("private")
        ]
        for full_name in own_repos[: self.MAX_REPOS_FOR_EMAILS]:
            resp = await client.get(
                f"https://api.github.com/repos/{full_name}/commits",
                params={"author": username, "per_page": 20},
            )
            # 409 = repositorio vacío; 403 = límite de peticiones agotado.
            if resp.status_code != 200:
                continue
            for commit in resp.json():
                author = (commit.get("commit") or {}).get("author") or {}
                email = str(author.get("email") or "").lower()
                if "@" not in email or "users.noreply.github.com" in email:
                    continue
                evidence.setdefault(email, {
                    "email": email,
                    "repo": full_name,
                    "commit_url": str(commit.get("html_url") or f"https://github.com/{full_name}"),
                })
        return evidence
