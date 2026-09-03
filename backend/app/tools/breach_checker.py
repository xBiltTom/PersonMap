from typing import List
import httpx
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class BreachCheckerTool(BaseTool):
    name = "breach_checker"
    description = (
        "Verifica si una dirección de correo electrónico ha sido comprometida en "
        "filtraciones públicas masivas de datos (Data Breaches) vía XposedOrNot API."
    )
    category = ToolCategory.BREACH
    required_inputs = ["email", "discovered_emails"]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        emails = context.all_emails()
        if not emails:
            return []

        findings: List[ToolFinding] = []

        async with httpx.AsyncClient(timeout=10.0) as client:
            for email in emails:
                url = f"https://api.xposedornot.com/v1/check-email/{email}"
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        breaches_found = []
                        # XposedOrNot returns breaches as a list of lists or dict
                        raw_breaches = data.get("breaches", [])
                        if isinstance(raw_breaches, list):
                            for b in raw_breaches:
                                if isinstance(b, list):
                                    breaches_found.extend(b)
                                elif isinstance(b, str):
                                    breaches_found.append(b)

                        if breaches_found:
                            findings.append(
                                ToolFinding(
                                    entity_type="breach",
                                    platform="data_leak",
                                    value=email,
                                    display_name=f"Compromiso en {len(breaches_found)} brecha(s) de datos",
                                    metadata_info={
                                        "email": email,
                                        "breaches": breaches_found,
                                        "breaches_count": len(breaches_found),
                                        "impact": "CRITICO",
                                    },
                                    confidence=1.0,
                                    evidence_urls=[f"https://xposedornot.com/email/{email}"],
                                )
                            )
                except Exception:
                    continue

        return findings
