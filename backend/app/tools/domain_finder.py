"""
Infraestructura personal a través de Certificate Transparency (crt.sh).

Todo certificado TLS emitido queda registrado públicamente en los logs de
Certificate Transparency. Consultarlos revela los subdominios de un dominio
**sin tocar ese dominio**: es OSINT estrictamente pasivo.

Relevante para el público objetivo: un estudiante de ingeniería con su portfolio
en `juan.dev` suele tener ahí, sin saberlo, un `staging.juan.dev`, un
`grafana.juan.dev` o un `pruebas.juan.dev` que nunca pensó en publicar.

**Qué NO se consulta.** Un dominio institucional (`unmsm.edu.pe`) o el de un
proveedor de correo gratuito no es infraestructura de la persona: son de la
universidad o de Google. Meter sus subdominios en el expediente de alguien sería
el mismo error de categoría que atribuirle una cuenta ajena. Se filtran por tres
vías: proveedores conocidos, el catálogo de plataformas que ya mantiene
`dataset_adapter`, y un tope de subdominios por encima del cual el dominio es
evidentemente de una organización y no de una persona.

Fuente verificada en vivo el 2026-09-04. **Va y viene**: en una medición de la
mañana respondió 1 de cada 4 peticiones (HTTP 502) y por la tarde 6 de 6. De ahí
que use más reintentos que el resto de herramientas y que su fallo sea silencioso.
"""

import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from app.core.events import event_bus
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.dataset_adapter import platform_hosts

CRT_SH_URL = "https://crt.sh/"

# Proveedores de correo y de alojamiento gratuito: el dominio es del proveedor,
# no de la persona.
PUBLIC_PROVIDERS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "yahoo.es", "icloud.com", "me.com", "proton.me",
    "protonmail.com", "aol.com", "gmx.com", "mail.com", "zoho.com",
    "yandex.com", "tutanota.com", "hotmail.es", "outlook.es", "msn.com",
    "github.io", "gitlab.io", "vercel.app", "netlify.app", "herokuapp.com",
    "wordpress.com", "blogspot.com", "web.app", "firebaseapp.com", "pages.dev",
}

# Sufijos de dominios que pertenecen a instituciones, no a personas.
INSTITUTIONAL_SUFFIXES = (".edu", ".edu.pe", ".gob.pe", ".gov", ".ac.uk", ".edu.mx")

# Por encima de esto, el dominio es de una organización. Un portfolio personal
# tiene un puñado de subdominios; una universidad, cientos.
MAX_SUBDOMAINS_FOR_PERSONAL = 40

# Dominios consultados por investigación. Cada consulta a crt.sh es lenta.
MAX_DOMAINS_QUERIED = 4


class DomainFinderTool(BaseTool):
    name = "domain_finder"
    description = (
        "Descubre la infraestructura personal (dominio propio y sus subdominios) "
        "a partir de los registros públicos de Certificate Transparency vía crt.sh"
    )
    category = ToolCategory.DOCUMENT
    required_inputs = ["email", "candidate_urls"]

    def can_run(self, context: TargetContext) -> bool:
        """
        `candidate_urls` vive en `context.extra`, no como atributo, así que la
        comprobación por defecto de `BaseTool` no lo ve. Mismo patrón que
        `social_url_extractor`.

        Se exige además que haya algún dominio candidato de verdad: sin esto la
        herramienta se despacharía en cada ronda solo por tener un correo de
        Gmail, para no consultar nada.
        """
        return bool(self._candidate_domains(context))

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        candidates = self._candidate_domains(context)
        if not candidates:
            return []

        investigation_id = context.extra.get("investigation_id")
        findings: List[ToolFinding] = []

        # Más reintentos que el resto: crt.sh alterna rachas de 502 con rachas
        # de funcionamiento normal, y una sola pasada se lo pierde a menudo.
        async with http_client.build_client(
            timeout=30.0, rotate_ua=False, max_retries=4
        ) as client:
            for domain in candidates[:MAX_DOMAINS_QUERIED]:
                entries = await self._query(client, domain)
                if entries is None:
                    if investigation_id:
                        await event_bus.publish(investigation_id, {
                            "type": "log",
                            "phase": "source_degraded",
                            "tool": self.name,
                            "message": (
                                f"[{self.name}] crt.sh no respondió para '{domain}'. "
                                f"Es una fuente intermitente; el resto de la "
                                f"investigación no se ve afectado."
                            ),
                            "timestamp": time.time(),
                        })
                    continue

                subdomains = self._extract_subdomains(entries, domain)
                if not subdomains:
                    continue

                if len(subdomains) > MAX_SUBDOMAINS_FOR_PERSONAL:
                    # Es de una organización, no de la persona. Meter sus
                    # subdominios en el expediente sería atribuirle una
                    # infraestructura que no es suya.
                    if investigation_id:
                        await event_bus.publish(investigation_id, {
                            "type": "log",
                            "phase": "catalog_filter",
                            "tool": self.name,
                            "message": (
                                f"[{self.name}] '{domain}' tiene {len(subdomains)} "
                                f"subdominios: es infraestructura de una organización, "
                                f"no personal. Se descarta del expediente."
                            ),
                            "timestamp": time.time(),
                        })
                    continue

                findings.append(self._to_finding(domain, subdomains, entries))

        return findings

    # -- Interno -----------------------------------------------------------

    def _candidate_domains(self, context: TargetContext) -> List[str]:
        """
        Dominios que podrían ser de la persona.

        Se toman del correo y de las URLs candidatas que haya recogido el
        pivoteo, y se descarta todo lo que sea de un proveedor, de una
        institución o de una plataforma conocida.
        """
        known_platforms = platform_hosts()
        candidates: List[str] = []

        def consider(host: Optional[str]) -> None:
            if not host:
                return
            host = host.lower().strip().lstrip(".")
            host = host.split(":")[0]
            if host.startswith("www."):
                host = host[4:]
            if not host or "." not in host:
                return
            if host in PUBLIC_PROVIDERS or host in known_platforms:
                return
            if any(host.endswith(suffix) for suffix in INSTITUTIONAL_SUFFIXES):
                return
            if host not in candidates:
                candidates.append(host)

        for email in context.all_emails():
            if "@" in email:
                consider(email.split("@", 1)[1])

        for url in context.extra.get("candidate_urls", []) or []:
            try:
                consider(urlparse(str(url)).hostname)
            except Exception:
                continue

        return candidates

    async def _query(self, client: Any, domain: str) -> Optional[List[Dict[str, Any]]]:
        resp = await http_client.get(
            client, CRT_SH_URL, params={"q": domain, "output": "json"}
        )
        if resp is None or resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except Exception:
            return None
        return data if isinstance(data, list) else None

    def _extract_subdomains(
        self,
        entries: List[Dict[str, Any]],
        domain: str,
    ) -> List[str]:
        """
        Nombres distintos del certificado que cuelgan del dominio.

        `name_value` puede traer varios nombres separados por saltos de línea, y
        los comodines (`*.dominio`) no son un subdominio real que visitar.
        """
        found: Set[str] = set()
        for entry in entries:
            raw = str(entry.get("name_value") or "")
            for name in raw.splitlines():
                name = name.strip().lower().lstrip("*.")
                if not name or name == domain:
                    continue
                if name.endswith(f".{domain}"):
                    found.add(name)
        return sorted(found)

    def _to_finding(
        self,
        domain: str,
        subdomains: List[str],
        entries: List[Dict[str, Any]],
    ) -> ToolFinding:
        issuers = sorted({
            str(e.get("issuer_name") or "").split("O=")[-1].split(",")[0].strip('" ')
            for e in entries
            if e.get("issuer_name")
        })
        last_seen = max(
            (str(e.get("not_before") or "") for e in entries), default=""
        )

        return ToolFinding(
            entity_type="domain",
            platform="certificate_transparency",
            value=domain,
            display_name=f"Dominio propio: {domain} ({len(subdomains)} subdominios)",
            metadata_info={
                "domain": domain,
                "subdomains": subdomains[:MAX_SUBDOMAINS_FOR_PERSONAL],
                "subdomain_count": len(subdomains),
                "certificates": len(entries),
                "issuers": issuers[:5],
                "last_certificate": last_seen[:10],
                "source": "crt.sh",
                "source_tool": "domain_finder",
            },
            # Certeza de DETECCIÓN: el certificado existe en los logs públicos.
            # Que el dominio sea de la persona lo decide el modelo de identidad.
            confidence=0.95,
            evidence_urls=[f"https://crt.sh/?q={domain}"],
        )
