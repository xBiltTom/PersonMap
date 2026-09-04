import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class GoogleAccountOSINTTool(BaseTool):
    """
    Passive Google ecosystem intelligence for Gmail/Google Workspace targets.

    Adapted from the GHunt methodology (github.com/mxrch/GHunt) but restricted
    to endpoints that work WITHOUT session cookies or paid API keys.
    GHunt's most powerful features (Maps reviews, Calendar, Play Games) require
    a live Google session token that expires every few hours — making them
    unsuitable for an unattended backend server.

    What this module does without credentials (P0#3 from ANALISIS_OSINT_MUNDIAL.md):
    1. Gmail existence validation — silent check via password-reset flow initial step,
       same technique used by Holehe gmail module. No email sent, no alert to target.
    2. YouTube channel search — public /results endpoint, no API key.
    3. Google Scholar profile — public author search, returns citations and h-index.
    """

    name = "google_account_osint"
    description = (
        "OSINT pasivo del ecosistema Google para cuentas Gmail/Workspace: detecta "
        "existencia de cuenta, nombre real de Google, canal de YouTube "
        "y perfil de Google Scholar sin cookies ni API keys."
    )
    category = ToolCategory.EMAIL
    required_inputs = ["email"]

    GOOGLE_DOMAINS = {"gmail.com", "googlemail.com", "google.com"}

    def can_run(self, context: TargetContext) -> bool:
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
            for email in emails:
                if "@" not in email:
                    continue
                domain = email.split("@", 1)[1].lower()
                is_google = (
                    domain in self.GOOGLE_DOMAINS
                    or domain.endswith(".edu")
                    or domain.endswith(".edu.pe")
                )
                if not is_google:
                    continue

                username_part = email.split("@")[0]

                # 1. Gmail existence check (silent — no email sent to target)
                exists_f = await self._check_gmail_existence(client, email)
                if exists_f:
                    findings.append(exists_f)

                # 2. YouTube channel search by username/name
                yt_findings = await self._search_youtube_channel(client, username_part, context)
                findings.extend(yt_findings)

                # 3. Google Scholar profile (if name available)
                if context.full_name:
                    scholar_findings = await self._search_scholar(client, context)
                    findings.extend(scholar_findings)

        return findings

    async def _check_gmail_existence(
        self, client: Any, email: str
    ) -> Optional[ToolFinding]:
        """
        Silent Gmail account existence check via the password recovery flow.
        Technique is identical to Holehe's gmail probe: POST to Google's account
        lookup endpoint — it returns a distinct response for existing vs. non-existing
        accounts without sending any email or alerting the target.
        """
        try:
            resp = await http_client.post(
                client,
                "https://accounts.google.com/_/signin/sl/lookup",
                data={
                    "f.req": f'["{email}",null,true]',
                    "flowName": "GlifWebSignIn",
                    "flowEntry": "ServiceLogin",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp is None:
                return None

            body = resp.text
            account_exists = (
                resp.status_code == 200
                and "identifierError" not in body
                and '"gf.aeh"' not in body
                and len(body) > 200
            )

            if not account_exists:
                return None

            # Google sometimes returns the display name in the lookup response
            display_name: Optional[str] = None
            name_match = re.search(r'\["([A-Z][a-zA-Z ]{2,50})",', body)
            if name_match:
                display_name = name_match.group(1)

            return ToolFinding(
                entity_type="google_account",
                platform="google",
                value=f"https://accounts.google.com/?email={email}",
                display_name=display_name or f"Cuenta Google activa: {email}",
                confidence=0.85,
                metadata_info={
                    "email": email,
                    "account_exists": True,
                    "google_display_name": display_name,
                    "name": display_name,
                    "source_tool": "google_account_osint",
                    "technique": "silent_existence_check",
                },
                evidence_urls=[],
            )
        except Exception:
            return None

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

            body = resp.text
            channel_handles = re.findall(r'"url":"(/@[a-zA-Z0-9_.-]+)"', body)
            seen: set = set()
            for handle in channel_handles[:3]:
                full_url = f"https://www.youtube.com{handle}"
                if full_url in seen:
                    continue
                seen.add(full_url)
                handle_name = handle.lstrip("/@")
                conf = 0.65 if username_part.lower() in handle_name.lower() else 0.40
                findings.append(ToolFinding(
                    entity_type="social_account",
                    platform="youtube",
                    value=full_url,
                    display_name=f"YouTube: {handle}",
                    confidence=conf,
                    metadata_info={
                        "source_tool": "google_account_osint",
                        "technique": "youtube_channel_search",
                        "query": query,
                        "username": handle_name,
                        "url": full_url,
                    },
                    evidence_urls=[full_url],
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
                }
                if citations:
                    meta["citations"] = int(citations)
                if context.university:
                    meta["institutions"] = [context.university]

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
