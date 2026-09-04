from typing import List
import httpx
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding


class DniLookupTool(BaseTool):
    name = "dni_lookup"
    description = (
        "Verifica y consulta información pública asociada a documentos de identidad "
        "(DNI Perú / RUC 10) en portales públicos gubernamentales."
    )
    category = ToolCategory.DOCUMENT
    required_inputs = ["dni"]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        if not context.dni or not context.dni.strip():
            return []

        dni = context.dni.strip()
        # Clean non-digits
        dni_clean = "".join(filter(str.isdigit, dni))
        if len(dni_clean) != 8:
            return []

        findings: List[ToolFinding] = []

        # Query public API for Peru DNI (SUNAT/RENIEC mirror)
        async with http_client.build_client(timeout=6.0) as client:
            try:
                # Direct check on public RUC portal (RUC persona natural = 10 + DNI + digit)
                ruc_prefix = f"10{dni_clean}"
                url = f"https://api.apis.net.pe/v1/dni?numero={dni_clean}"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    nombre = data.get("nombre") or data.get("nombres")
                    ape_pat = data.get("apellidoPaterno") or ""
                    ape_mat = data.get("apellidoMaterno") or ""
                    full_name = f"{nombre} {ape_pat} {ape_mat}".strip()

                    findings.append(
                        ToolFinding(
                            entity_type="document",
                            platform="reniec_peru",
                            value=f"DNI: {dni_clean}",
                            display_name=full_name or f"DNI {dni_clean}",
                            metadata_info={
                                "dni": dni_clean,
                                "full_name": full_name,
                                "source": "reniec_sunat_public",
                            },
                            confidence=0.99,
                            evidence_urls=[],
                        )
                    )
            except Exception:
                # Fallback: Record validated DNI entity
                findings.append(
                    ToolFinding(
                        entity_type="document",
                        platform="reniec_peru",
                        value=f"DNI: {dni_clean}",
                        display_name=f"DNI {dni_clean}",
                        metadata_info={"dni": dni_clean, "format_valid": True},
                        confidence=0.85,
                        evidence_urls=[],
                    )
                )

        return findings
