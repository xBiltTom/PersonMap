"""
Dorking sobre la web pública con motores intercambiables.

Motor principal: **Tavily** (https://tavily.com), un buscador diseñado para
agentes. Frente al scraping de HTML que usaba este módulo, aporta:

  - JSON estructurado, sin parseo de HTML que se rompe cuando el buscador
    cambia su maquetación (era el eslabón más frágil del pipeline);
  - `exact_match`, que respeta las comillas de un dork en lugar de tratarlas
    como texto suelto -- es justo lo que distingue un dork de una búsqueda;
  - `include_domains`, equivalente nativo del operador `site:`;
  - un `score` de relevancia por resultado, que se traduce a confianza en vez
    de asignar la misma a todos los hallazgos;
  - sesgo por país, útil dado que el público objetivo es peruano.

Motor de respaldo: scraping de DuckDuckGo, el comportamiento anterior. Se usa
automáticamente si no hay `TAVILY_API_KEY`, de modo que el sistema sigue
funcionando al 100% sin configurar nada.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# Dominio -> plataforma normalizada, para clasificar cada resultado.
PLATFORM_DOMAINS: Dict[str, str] = {
    "linkedin.com": "linkedin",
    "github.com": "github",
    "gitlab.com": "gitlab",
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "twitter.com": "x_twitter",
    "x.com": "x_twitter",
    "tiktok.com": "tiktok",
    "youtube.com": "youtube",
    "reddit.com": "reddit",
    "t.me": "telegram",
    "medium.com": "medium",
    "scholar.google.com": "google_scholar",
    "researchgate.net": "researchgate",
    "orcid.org": "orcid",
    "slideshare.net": "slideshare",
    "scribd.com": "scribd",
}

# Dominios donde suele acabar el perfil profesional/social de un estudiante.
PROFILE_DOMAINS = [
    "linkedin.com",
    "github.com",
    "instagram.com",
    "facebook.com",
    "x.com",
    "tiktok.com",
]


QUOTED_TERM_RE = re.compile(r'"([^"]+)"')


def _normalize(text: str) -> str:
    """Minúsculas y espacios colapsados, para comparar sin depender del formato."""
    return re.sub(r"\s+", " ", text or "").lower().strip()


def _matches_literally(dork: "Dork", title: str, snippet: str, url: str) -> bool:
    """
    ¿Aparecen realmente en el resultado los términos entrecomillados del dork?

    Sustituye al parámetro `exact_match` de Tavily, que está documentado pero
    devuelve cero resultados en la práctica. Sin esta comprobación el dorking
    degenera en búsqueda semántica y contamina el expediente con homónimos y
    páginas apenas relacionadas.

    La condición es **conjuntiva**: un dork `"Juan Perez" "Universidad X"` pide
    ambas cosas a la vez. Aceptarlo porque solo coincide la universidad
    devolvería la web del centro para cualquier alumno.

    Un dork sin comillas no impone restricción: se acepta el resultado.
    """
    terms = QUOTED_TERM_RE.findall(dork.query)
    if not terms:
        return True

    haystack = _normalize(f"{title} {snippet} {url}")
    # Las URLs suelen unir el nombre con guiones o puntos ("juan-perez"), así
    # que se compara también una versión sin separadores.
    collapsed = re.sub(r"[^a-z0-9]", "", haystack)

    for term in terms:
        needle = _normalize(term)
        compact = re.sub(r"[^a-z0-9]", "", needle)
        if needle and needle in haystack:
            continue
        if compact and compact in collapsed:
            continue
        return False
    return True


@dataclass
class Dork:
    """
    Un dork independiente del motor.

    `include_domains` se expresa como dato y no como el operador `site:` dentro
    de la cadena porque Tavily tiene un parámetro nativo para ello; el respaldo
    de DuckDuckGo lo renderiza a `site:` al construir su consulta.
    """

    query: str
    rationale: str
    include_domains: List[str] = field(default_factory=list)

    def as_text_query(self) -> str:
        """Consulta en texto plano, para motores sin filtro de dominio nativo."""
        if not self.include_domains:
            return self.query
        sites = " OR ".join(f"site:{d}" for d in self.include_domains)
        return f"{self.query} ({sites})"


@dataclass(frozen=True)
class SearchBackend:
    """
    Un motor de búsqueda enchufable.

    `is_available` decide si el motor puede usarse ahora mismo (una clave
    configurada, por ejemplo) y `build_client` construye su cliente HTTP, que
    no es el mismo para todos: Tavily es una API y quiere un User-Agent
    estable, mientras que el raspado de DuckDuckGo necesita cabeceras de
    navegador.
    """

    name: str
    is_available: Callable[[], bool]
    build_client: Callable[[], Any]
    search: Callable[..., Awaitable[List[ToolFinding]]]


class SearchDorkerTool(BaseTool):
    name = "search_dorker"
    description = (
        "Genera y ejecuta dorks de búsqueda contextuales sobre la web pública "
        "(LinkedIn, GitHub, redes sociales, repositorios académicos) usando Tavily, "
        "con DuckDuckGo como motor de respaldo."
    )
    category = ToolCategory.SEARCH
    required_inputs = ["full_name", "username", "email", "dni"]

    def _backends(self) -> List["SearchBackend"]:
        """
        Motores en orden de preferencia.

        Estructura de tabla en lugar de un `if/else`: añadir un motor nuevo es
        una entrada más, no una rama nueva dentro de `execute`. La caída de uno
        al siguiente es la misma que antes.

        Sobre SearXNG, que el plan contemplaba: no se añade porque no funciona.
        Las instancias públicas traen la salida JSON desactivada, y una
        auto-hospedada recibe CAPTCHA de Google/Brave/Startpage desde una sola
        IP. Queda como entrada futura de esta tabla si algún día cambia.
        """
        return [
            SearchBackend(
                name="tavily",
                is_available=lambda: settings.tavily_enabled,
                build_client=lambda: http_client.build_client(
                    timeout=20.0, rotate_ua=False
                ),
                search=self._search_tavily,
            ),
            SearchBackend(
                name="duckduckgo",
                is_available=lambda: True,
                build_client=lambda: http_client.build_client(
                    timeout=12.0, headers=HEADERS
                ),
                search=self._search_duckduckgo,
            ),
        ]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        dorks = self._generate_dorks(context)
        if not dorks:
            return []

        max_queries = max(1, settings.tavily_max_queries)
        dorks = dorks[:max_queries]

        findings: List[ToolFinding] = []
        seen_urls: set[str] = set()

        for backend in self._backends():
            if not backend.is_available():
                continue

            async with backend.build_client() as client:
                for dork in dorks:
                    findings.extend(await backend.search(client, dork, seen_urls))

            # Si un motor no devolvió nada (clave inválida, cuota agotada,
            # caída), se pasa al siguiente en lugar de quedarse sin resultados.
            if findings:
                return findings

        return findings

    # -- Generación de dorks ---------------------------------------------

    def _generate_dorks(self, context: TargetContext) -> List[Dork]:
        """
        Dorks ordenados de mayor a menor poder discriminante, porque el tope de
        consultas recorta por el final.
        """
        dorks: List[Dork] = []
        name = (context.full_name or "").strip()
        uni = (context.university or "").strip()
        username = (context.username or "").strip()
        email = (context.email or "").strip()
        dni = (context.dni or "").strip()

        # El correo es el identificador más discriminante: quien lo publica
        # suele estar hablando de la persona concreta, no de un homónimo.
        if email:
            dorks.append(Dork(f'"{email}"', "Menciones públicas del correo"))

        if dni:
            dorks.append(Dork(f'"{dni}"', "Aparición del DNI en documentos públicos"))

        if name and uni:
            dorks.append(
                Dork(f'"{name}" "{uni}"', "Nombre junto a su afiliación institucional")
            )
        elif name:
            dorks.append(Dork(f'"{name}"', "Menciones del nombre completo"))

        if name:
            dorks.append(
                Dork(
                    f'"{name}"',
                    "Perfiles sociales y profesionales del nombre",
                    include_domains=PROFILE_DOMAINS,
                )
            )

        if username:
            dorks.append(Dork(f'"{username}"', "Menciones del alias"))

        return dorks

    # -- Motor principal: Tavily ------------------------------------------

    async def _search_tavily(
        self, client: httpx.AsyncClient, dork: Dork, seen_urls: set
    ) -> List[ToolFinding]:
        payload: Dict[str, Any] = {
            "query": dork.query,
            "search_depth": settings.tavily_search_depth,
            "max_results": settings.tavily_max_results,
        }
        # NO se envía `exact_match`. Está documentado, pero verificado contra la
        # API real devuelve CERO resultados en todos los casos (con y sin
        # comillas), dejando el dorking mudo sin ningún error visible. Las
        # comillas dentro de la propia consulta sí se respetan, así que la
        # exactitud se impone después, del lado del cliente, en
        # `_matches_literally`.
        if dork.include_domains:
            payload["include_domains"] = dork.include_domains
        if settings.tavily_country:
            payload["country"] = settings.tavily_country

        resp = await http_client.post(
            client,
            TAVILY_SEARCH_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.tavily_api_key}",
                "Content-Type": "application/json",
            },
        )
        if resp is None or resp.status_code != 200:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

        findings: List[ToolFinding] = []
        for item in data.get("results", []) or []:
            url = item.get("url")
            if not url or url in seen_urls:
                continue

            title = item.get("title") or url
            snippet = item.get("content") or ""
            literal = _matches_literally(dork, title, snippet, url)

            # Tavily busca por relevancia semántica, no por coincidencia literal:
            # un dork del correo "jperez@untumbes.edu.pe" (inexistente) devuelve
            # la portada de untumbes.edu.pe. En OSINT ese falso positivo es peor
            # que no obtener nada, porque acaba en el expediente de una persona.
            if not literal and settings.tavily_require_literal_match:
                continue

            seen_urls.add(url)
            finding = self._build_finding(
                url=url,
                title=title,
                snippet=snippet,
                dork=dork,
                engine="tavily",
                relevance=item.get("score"),
                literal=literal,
            )
            if finding:
                findings.append(finding)

        return findings

    # -- Motor de respaldo: DuckDuckGo ------------------------------------

    async def _search_duckduckgo(
        self, client: httpx.AsyncClient, dork: Dork, seen_urls: set
    ) -> List[ToolFinding]:
        findings: List[ToolFinding] = []
        try:
            resp = await client.post(
                "https://html.duckduckgo.com/html/", data={"q": dork.as_text_query()}
            )
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            for r in soup.find_all("div", class_="result")[:5]:
                title_tag = r.find("a", class_="result__a")
                if not title_tag:
                    continue

                raw_url = title_tag.get("href", "")
                actual_url = raw_url
                # DuckDuckGo envuelve las URLs reales en un redirector `uddg=`.
                if "uddg=" in raw_url:
                    match = re.search(r"uddg=([^&]+)", raw_url)
                    if match:
                        actual_url = unquote(match.group(1))

                if not actual_url or actual_url in seen_urls:
                    continue
                seen_urls.add(actual_url)

                snippet_tag = r.find("a", class_="result__snippet")
                finding = self._build_finding(
                    url=actual_url,
                    title=title_tag.get_text(strip=True),
                    snippet=snippet_tag.get_text(strip=True) if snippet_tag else "",
                    dork=dork,
                    engine="duckduckgo",
                    relevance=None,
                )
                if finding:
                    findings.append(finding)
        except Exception:
            return []

        return findings

    # -- Común ------------------------------------------------------------

    def _detect_platform(self, url: str) -> str:
        low = url.lower()
        for domain, platform in PLATFORM_DOMAINS.items():
            if domain in low:
                return platform
        return "web_search"

    def _build_finding(
        self,
        *,
        url: str,
        title: str,
        snippet: str,
        dork: Dork,
        engine: str,
        relevance: Optional[float],
        literal: bool = True,
    ) -> Optional[ToolFinding]:
        if not url.startswith("http"):
            return None

        platform = self._detect_platform(url)

        # Tavily puntúa la relevancia de cada resultado; se traslada a la
        # confianza en lugar de asignar 0.60 plano a todo. Aun así se acota:
        # que un resultado sea relevante para la consulta no prueba que la
        # persona mencionada sea el objetivo y no un homónimo.
        if relevance is not None:
            confidence = round(min(0.75, max(0.35, 0.35 + float(relevance) * 0.40)), 2)
        else:
            confidence = 0.60
        # Un resultado en una plataforma de perfiles es más accionable que una
        # página suelta de la web.
        if platform != "web_search":
            confidence = round(min(0.80, confidence + 0.05), 2)
        # Un resultado que no contiene literalmente el término buscado es, como
        # mucho, una pista contextual.
        if not literal:
            confidence = min(confidence, 0.35)

        return ToolFinding(
            entity_type="search_mention",
            platform=platform,
            value=url,
            display_name=title[:200],
            metadata_info={
                "snippet": snippet,
                "query": dork.query,
                "rationale": dork.rationale,
                "engine": engine,
                "relevance_score": relevance,
                "literal_match": literal,
                "url": url,
                "source_tool": "search_dorker",
            },
            confidence=confidence,
            evidence_urls=[url],
        )
