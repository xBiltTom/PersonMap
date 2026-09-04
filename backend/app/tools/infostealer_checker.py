"""
Registros de infostealer (Hudson Rock Cavalier).

Fuente: API pública gratuita y sin clave de Hudson Rock
(`cavalier.hudsonrock.com`), verificada en vivo el 2026-09-04. Uso conforme a
sus "free tools" para investigación y concientización.

**Qué aporta que no aporte `breach_checker`.** Una brecha de datos es un fallo
de un tercero: se filtró la base de un servicio y con ella un hash de tu
contraseña. Un infostealer es un fallo *del equipo de la persona*: un malware
se ejecutó en su máquina y se llevó las contraseñas guardadas en el navegador
**en texto claro**, junto con las cookies de sesión, que permiten saltarse
incluso el segundo factor. Por eso los dos coexisten en lugar de sustituirse, y
por eso el scorecard lo pondera muy por encima.

**Minimización de datos.** La respuesta de la API puede incluir contraseñas y
credenciales en claro. Aquí se copia una **lista blanca** de campos —el hecho
de la exposición, la fecha, el equipo, el sistema operativo, la ruta del
malware y el número de servicios afectados— y nunca una contraseña, un login ni
una cookie. Se usa lista blanca y no lista negra a propósito: si mañana la API
añade un campo sensible con otro nombre, una lista negra lo dejaría pasar.

**Consentimiento.** Consultar esta API envía a un tercero la identidad de a
quién se está investigando. La herramienta solo se ejecuta si la persona marcó
explícitamente que investiga su propia identidad; sin esa marca, `can_run`
devuelve False y el motor ni siquiera la despacha.
"""

from typing import Any, Dict, List, Optional

from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding

API_BASE = "https://cavalier.hudsonrock.com/api/json/v2/osint-tools"
API_HOST = "cavalier.hudsonrock.com"

# Límite publicado por Hudson Rock: 50 peticiones cada 10 s por host. Se declara
# aquí, junto al endpoint, para que viva al lado del motivo por el que existe.
http_client.register_host_rate_limit(API_HOST, max_requests=50, per_seconds=10.0)

# Campos que se persisten de cada registro. TODO lo demás se descarta.
#
# Comprobado contra respuestas reales (2026-09-04): la API devuelve también
# `top_passwords` (contraseñas enmascaradas) y `top_logins` (correos
# enmascarados). Ninguno entra:
#   - `top_passwords` es justo lo que la minimización prohíbe guardar.
#   - `top_logins` NO son servicios afectados, aunque el nombre lo sugiera; son
#     los logins hallados en el registro. Etiquetarlos como "servicios" habría
#     metido una afirmación falsa en el expediente de una persona, y no aportan
#     nada accionable que no diga ya `total_user_services`.
STEALER_FIELDS = (
    "date_compromised",
    "computer_name",
    "operating_system",
    "malware_path",
    "ip",
    "antiviruses",
    "stealer_family",
)

# La API rellena los campos que no conoce con la cadena "Not Found" en lugar de
# omitirlos. Guardarlas tal cual pondría "Ruta del malware: Not Found" en el
# informe, que parece un fallo del sistema en vez de un dato ausente.
PLACEHOLDER_VALUES = {"not found", "unknown", "n/a", ""}

MAX_LIST_ITEMS = 15


class InfostealerCheckerTool(BaseTool):
    name = "infostealer_checker"
    description = (
        "Comprueba si un correo o alias aparece en registros de malware tipo "
        "infostealer (equipos infectados cuyas credenciales guardadas fueron "
        "robadas en texto claro), vía la API pública de Hudson Rock."
    )
    category = ToolCategory.BREACH
    required_inputs = ["email", "username"]

    def can_run(self, context: TargetContext) -> bool:
        """
        Exige consentimiento explícito además de un identificador.

        Es la única herramienta del registro que se lo pide, porque es la única
        que manda a un tercero la identidad de la persona investigada a cambio
        de un dato sobre su equipo. Sin la marca no se ejecuta: falla cerrado,
        que en una herramienta de concientización es la única opción defendible.
        """
        if not context.extra.get("self_consent"):
            return False
        return super().can_run(context)

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        if not context.extra.get("self_consent"):
            return []

        findings: List[ToolFinding] = []
        seen: set[str] = set()

        # rotate_ua=False: es una API, no una web que haya que imitar con un
        # navegador. Mismo criterio que `breach_checker` con XposedOrNot.
        async with http_client.build_client(timeout=20.0, rotate_ua=False) as client:
            for email in context.all_emails():
                findings.extend(
                    await self._query(client, "search-by-email", "email", email, seen)
                )
            for username in context.all_usernames():
                findings.extend(
                    await self._query(
                        client, "search-by-username", "username", username, seen
                    )
                )

        return findings

    # -- Interno -----------------------------------------------------------

    async def _query(
        self,
        client: Any,
        endpoint: str,
        param: str,
        value: str,
        seen: set,
    ) -> List[ToolFinding]:
        resp = await http_client.get(
            client, f"{API_BASE}/{endpoint}", params={param: value}
        )
        if resp is None or resp.status_code != 200:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        stealers = data.get("stealers")
        if not isinstance(stealers, list) or not stealers:
            # Respuesta normal cuando no hay infección: `stealers: []` y un
            # `message` explicativo. No es un error ni merece un hallazgo.
            return []

        total_user = data.get("total_user_services")
        total_corp = data.get("total_corporate_services")

        findings: List[ToolFinding] = []
        for record in stealers:
            if not isinstance(record, dict):
                continue

            meta = self._safe_metadata(record)

            # La clave es la identidad de la MÁQUINA, no la del identificador
            # con el que se preguntó: el mismo equipo aparece al consultar por
            # correo y por alias, y si el identificador entrara en la clave el
            # expediente diría que la persona tiene dos equipos comprometidos.
            # Es además la misma identidad que usa `value`, así que coincide con
            # lo que deduplicará después `persist_findings`.
            key = self._value_for(meta, value)
            if key in seen:
                continue
            seen.add(key)

            meta[param] = value
            meta["queried_by"] = param
            # Los totales vienen tanto por registro como en la raíz. El del
            # registro es el del equipo concreto, que es lo que el informe
            # afirma; el de la raíz agrega todos y se usa solo como respaldo.
            meta["total_user_services"] = record.get("total_user_services", total_user)
            meta["total_corporate_services"] = record.get(
                "total_corporate_services", total_corp
            )
            meta["source"] = "hudson_rock_cavalier"
            meta["impact"] = "CRITICO"
            # El correo se expone también con la clave que lee el modelo de
            # identidad, para que la señal `email_match` pueda evaluarse: este
            # registro está atado al correo del objetivo, no a un alias suelto.
            if param == "email":
                meta["emails"] = [value]

            findings.append(
                ToolFinding(
                    entity_type="infostealer",
                    platform=meta.get("stealer_family") or "infostealer",
                    value=self._value_for(meta, value),
                    display_name=self._label(meta),
                    metadata_info=meta,
                    # Certeza de DETECCIÓN: el registro existe en la base de
                    # Hudson Rock. Que sea del objetivo lo decide el scorer.
                    confidence=0.97,
                    evidence_urls=["https://www.hudsonrock.com/free-tools"],
                )
            )

        return findings

    def _safe_metadata(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Copia SOLO los campos de la lista blanca, descartando los rellenos.

        Lista blanca y no lista negra a propósito: si mañana la API añade un
        campo sensible con un nombre que nadie previó, una lista negra lo
        dejaría pasar y acabaría persistido.
        """
        meta: Dict[str, Any] = {}
        for field in STEALER_FIELDS:
            if field not in record:
                continue
            raw = record[field]

            if isinstance(raw, str):
                if raw.strip().lower() in PLACEHOLDER_VALUES:
                    continue
                meta[field] = raw[:300]
            elif isinstance(raw, (int, float, bool)):
                meta[field] = raw
            elif isinstance(raw, list):
                items = [
                    str(item)[:120]
                    for item in raw[:MAX_LIST_ITEMS]
                    if str(item).strip().lower() not in PLACEHOLDER_VALUES
                ]
                if items:
                    meta[field] = items
        return meta

    def _label(self, meta: Dict[str, Any]) -> str:
        computer = meta.get("computer_name")
        date = str(meta.get("date_compromised") or "")[:10]
        parts = ["Equipo comprometido"]
        if computer:
            parts.append(str(computer))
        if date:
            parts.append(date)
        return " · ".join(parts)

    def _value_for(self, meta: Dict[str, Any], fallback: str) -> str:
        """
        Identificador estable del hallazgo, para que la deduplicación funcione.

        Un mismo equipo puede aparecer al consultar por correo y por alias; sin
        una clave estable saldrían dos entidades para una sola infección.
        """
        computer: Optional[str] = meta.get("computer_name")
        date = str(meta.get("date_compromised") or "")[:10]
        if computer or date:
            return f"infostealer:{computer or 'equipo'}:{date or 'sin-fecha'}"
        return f"infostealer:{fallback}"
