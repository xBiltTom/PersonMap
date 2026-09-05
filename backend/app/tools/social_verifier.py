import re
from typing import Dict, List
from bs4 import BeautifulSoup
import httpx
from thefuzz import fuzz
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class SocialVerifierTool(BaseTool):
    name = "social_verifier"
    description = (
        "Comprueba y verifica perfiles sociales encontrados extrayendo metadatos OpenGraph "
        "(título, biografía, foto, enlaces) y calculando un score de certeza contra el objetivo."
    )
    category = ToolCategory.SOCIAL
    required_inputs = ["username", "discovered_usernames"]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        # This tool can verify known candidate URLs from context.extra
        candidate_urls: List[str] = context.extra.get("candidate_urls", [])
        if not candidate_urls:
            return []

        verified_findings: List[ToolFinding] = []

        async with http_client.build_client(timeout=10.0, headers=HEADERS) as client:
            for url in candidate_urls:
                finding = await self.verify_url(client, url, context)
                if finding:
                    verified_findings.append(finding)

        return verified_findings

    async def verify_url(
        self, client: httpx.AsyncClient, url: str, context: TargetContext
    ) -> ToolFinding | None:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract OpenGraph tags
            og_title = self._get_meta(soup, "og:title") or (soup.title.string if soup.title else "")
            og_desc = self._get_meta(soup, "og:description") or ""
            og_image = self._get_meta(soup, "og:image") or ""
            og_url = self._get_meta(soup, "og:url") or url

            # Extract @usernames and links from bio
            extracted_usernames = re.findall(r"@([A-Za-z0-9_.-]+)", og_desc)
            extracted_emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", og_desc)

            # Compute Confidence Score
            score, breakdown = self._compute_verification_score(
                title=og_title,
                bio=og_desc,
                target_name=context.full_name,
                target_university=context.university,
                target_email=context.email,
            )

            # Detect platform
            platform = "web_profile"
            for p in ["github", "instagram", "twitter", "x.com", "linkedin", "tiktok", "steam", "reddit", "medium"]:
                if p in url.lower():
                    platform = p.replace(".com", "")
                    break

            metadata = {
                "og_title": og_title,
                "bio": og_desc,
                # `og:image` NO es un avatar, aunque lo parezca: es la imagen
                # de vista previa social de la PÁGINA, y en la mayoría de sitios
                # es su logo, idéntico en todas sus URLs. Guardarla como
                # `avatar_url` hacía que el correlador visual comparase logos:
                # medido sobre una investigación real, el de Imgur, el de
                # Pastebin y el de PayPal entraban como "fotos de perfil" y uno
                # llegó a correlacionar a distancia 0, es decir, afirmando que
                # dos cuentas usaban la misma foto.
                #
                # Se conserva porque es útil para mostrar una miniatura del
                # enlace, pero con un nombre que dice lo que es.
                "og_image": og_image,
                "canonical_url": og_url,
                "extracted_usernames": extracted_usernames,
                "extracted_emails": extracted_emails,
                "verification_breakdown": breakdown,
            }

            return ToolFinding(
                entity_type="social_account",
                platform=platform,
                value=og_url,
                display_name=og_title or url,
                metadata_info=metadata,
                confidence=score,
                evidence_urls=[url],
            )
        except Exception:
            return None

    def _get_meta(self, soup: BeautifulSoup, property_name: str) -> str | None:
        tag = soup.find("meta", property=property_name) or soup.find("meta", attrs={"name": property_name})
        if tag and tag.get("content"):
            return tag["content"].strip()
        return None

    def _compute_verification_score(
        self,
        title: str,
        bio: str,
        target_name: str | None,
        target_university: str | None,
        target_email: str | None,
    ) -> tuple[float, Dict[str, float]]:
        score = 0.5  # Base profile existence
        breakdown = {"base": 0.5}

        # Check full name similarity in title or bio
        if target_name and (title or bio):
            combined_text = f"{title} {bio}"
            name_ratio = fuzz.partial_ratio(target_name.lower(), combined_text.lower()) / 100.0
            breakdown["name_match_ratio"] = name_ratio
            if name_ratio > 0.85:
                score += 0.25
            elif name_ratio > 0.65:
                score += 0.15

        # Check university in bio
        if target_university and bio:
            uni_ratio = fuzz.partial_ratio(target_university.lower(), bio.lower()) / 100.0
            breakdown["university_match_ratio"] = uni_ratio
            if uni_ratio > 0.75:
                score += 0.20

        # Check email domain or exact email in bio
        if target_email and bio:
            if target_email.lower() in bio.lower():
                score += 0.25
                breakdown["email_in_bio"] = 1.0

        score = min(max(score, 0.1), 0.99)
        return score, breakdown
