"""
Consulta de DNI/RUC Perú (RENIEC/SUNAT) con tres capas de fallback.

El ecosistema de mirrors del padrón RENIEC es inestable por diseño: los
proveedores rotan sus endpoints, añaden autenticación y deprecan versiones sin
aviso. Una sola URL deja la herramienta muda ante cualquier cambio.

Estrategia de intento encadenado:
  1. apis.net.pe **v2** con Bearer token (más estable, más campos) si
     `APIS_NET_PE_TOKEN` está configurado.
  2. apis.net.pe **v1** pública (sin token, puede exigir autenticación en
     algún momento).
  3. apisperu.com (mirror independiente, sin key, responde un esquema similar).

Si todos los intentos fallan, se registra el DNI con formato válido y
confianza 0.85 para que el expediente no quede vacío y la procedencia quede
documentada.
"""

from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding

# Límite publicado por apis.net.pe para el plan gratuito: 30 req/min.
# Se declara junto al endpoint para que el motivo viva al lado del número.
_APIS_NET_PE_HOST = "api.apis.net.pe"
http_client.register_host_rate_limit(_APIS_NET_PE_HOST, max_requests=25, per_seconds=60.0)

_APISPERU_HOST = "dniruc.apisperu.com"
http_client.register_host_rate_limit(_APISPERU_HOST, max_requests=20, per_seconds=60.0)

# Campos que se consideran «nombre» en las distintas respuestas de los mirrors.
_NOMBRE_KEYS = ("nombre", "nombres", "primerNombre", "segundoNombre")
_APE_PAT_KEYS = ("apellidoPaterno", "ape_paterno")
_APE_MAT_KEYS = ("apellidoMaterno", "ape_materno")


def _extract_full_name(data: Dict[str, Any]) -> str:
    """Construye nombre completo a partir de las claves presentes."""
    nombre = next((data.get(k) for k in _NOMBRE_KEYS if data.get(k)), "")
    ape_pat = next((data.get(k) for k in _APE_PAT_KEYS if data.get(k)), "")
    ape_mat = next((data.get(k) for k in _APE_MAT_KEYS if data.get(k)), "")
    return f"{nombre} {ape_pat} {ape_mat}".strip()


class DniLookupTool(BaseTool):
    name = "dni_lookup"
    description = (
        "Verifica y consulta información pública asociada a documentos de identidad "
        "(DNI Perú / RUC 10) en portales públicos gubernamentales."
    )
    category = ToolCategory.DOCUMENT
    required_inputs = ["dni"]

    def can_run(self, context: TargetContext) -> bool:
        if not super().can_run(context):
            return False
        dni_clean = "".join(filter(str.isdigit, context.dni or ""))
        return len(dni_clean) == 8

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        if not context.dni or not context.dni.strip():
            return []

        dni = context.dni.strip()
        dni_clean = "".join(filter(str.isdigit, dni))
        if len(dni_clean) != 8:
            return []

        full_name: Optional[str] = None
        source_used: Optional[str] = None

        async with http_client.build_client(timeout=8.0, rotate_ua=False) as client:
            full_name, source_used = await self._try_apis_net_pe(client, dni_clean)
            if full_name is None:
                full_name, source_used = await self._try_apisperu(client, dni_clean)

        return [self._build_finding(dni_clean, full_name, source_used)]

    # ------------------------------------------------------------------
    # Intentos individuales
    # ------------------------------------------------------------------

    async def _try_apis_net_pe(
        self, client: Any, dni: str
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Intenta apis.net.pe. Usa v2 con Bearer si hay token configurado,
        o v1 pública si no.
        """
        token = settings.apis_net_pe_token
        if token:
            url = f"https://{_APIS_NET_PE_HOST}/v2/reniec/dni?numero={dni}"
            headers = {"Authorization": f"Bearer {token}"}
            source = "apis_net_pe_v2"
        else:
            url = f"https://{_APIS_NET_PE_HOST}/v1/dni?numero={dni}"
            headers = {}
            source = "apis_net_pe_v1"

        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                name = _extract_full_name(data)
                if name:
                    return name, source
            # 401/403 con v1 es una señal clara de que ahora requiere token:
            # no reintentamos para no bloquear el presupuesto de concurrencia.
        except Exception:
            pass
        return None, None

    async def _try_apisperu(
        self, client: Any, dni: str
    ) -> tuple[Optional[str], Optional[str]]:
        """Mirror secundario independiente (apisperu.com)."""
        url = f"https://{_APISPERU_HOST}/api/dni/{dni}"
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                name = _extract_full_name(data)
                if name:
                    return name, "apisperu_com"
        except Exception:
            pass
        return None, None

    # ------------------------------------------------------------------
    # Constructor de hallazgo
    # ------------------------------------------------------------------

    def _build_finding(
        self,
        dni: str,
        full_name: Optional[str],
        source: Optional[str],
    ) -> ToolFinding:
        metadata: Dict[str, Any] = {
            "dni": dni,
            "source": source or "format_validated",
        }
        if full_name:
            metadata["full_name"] = full_name

        return ToolFinding(
            entity_type="document",
            platform="reniec_peru",
            value=f"DNI: {dni}",
            display_name=full_name or f"DNI {dni}",
            metadata_info=metadata,
            # Confianza alta si obtuvimos nombre real; menor si solo validamos formato.
            confidence=0.99 if full_name else 0.85,
            evidence_urls=[],
        )
