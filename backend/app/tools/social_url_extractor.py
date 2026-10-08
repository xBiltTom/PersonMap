from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.social_profiles import parse_social_profile


class SocialUrlExtractorTool(BaseTool):
    name = "social_url_extractor"
    description = "Extracción pasiva de perfiles candidatos por dominio y ruta; no confirma existencia"
    category = ToolCategory.SOCIAL
    required_inputs = ["candidate_urls"]

    def can_run(self, context: TargetContext) -> bool:
        return bool(context.extra.get("candidate_urls"))

    async def execute(self, context: TargetContext) -> list[ToolFinding]:
        findings = []
        seen = set()
        for raw in context.extra.get("candidate_urls", []):
            if not isinstance(raw, str):
                continue
            if raw in context.extra.get("derived_profile_candidates", {}):
                continue  # A constructed URL is not an observed account.
            profile = parse_social_profile(raw)
            if not profile or profile.url in seen:
                continue
            seen.add(profile.url)
            findings.append(ToolFinding(
                entity_type="social_account",
                platform=profile.platform,
                value=profile.url,
                display_name=f"{profile.platform.capitalize()}: @{profile.username}",
                confidence=0.5,
                evidence_urls=[raw],
                metadata_info={
                    "source_tool": self.name,
                    "platform": profile.platform,
                    "username": profile.username,
                    "url": profile.url,
                    "usernames": [profile.username] if profile.resource_kind == "username" else [],
                    "resource_kind": profile.resource_kind,
                    "profile_url": profile.url,
                    "verification_status": "candidate",
                },
            ))
        return findings
