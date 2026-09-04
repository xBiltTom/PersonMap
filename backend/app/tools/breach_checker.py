from typing import List
from app.tools import http_client
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

        # Migrated to the shared resilient HTTP layer (P0#5 — UA rotation, backoff,
        # global concurrency gate). rotate_ua=False: XposedOrNot is an API that
        # doesn't need browser UA impersonation.
        async with http_client.build_client(timeout=10.0, rotate_ua=False) as client:
            for email in emails:
                url = f"https://api.xposedornot.com/v1/check-email/{email}"
                resp = await http_client.get(client, url)
                if resp is None or resp.status_code != 200:
                    continue

                try:
                    data = resp.json()
                except Exception:
                    continue

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

        return findings
