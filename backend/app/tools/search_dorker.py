"""Búsqueda pública con validación local y respaldo por consulta."""

import re
import math
import asyncio
import unicodedata
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import unquote, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.tools import http_client
from app.tools.dni_public import normalize_dni, matches_dni, public_source_url
from app.tools.phone_numbers import analyze_phone, matches_phone_text, extract_phone_observations
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
    "snapchat.com": "snapchat",
    "threads.com": "threads",
    "bsky.app": "bluesky",
    "reddit.com": "reddit",
    "t.me": "telegram",
    "telegram.me": "telegram",
    "telegram.dog": "telegram",
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
    "youtube.com",
    "snapchat.com",
    "t.me",
]


QUOTED_TERM_RE = re.compile(r'"([^"]+)"')


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").casefold()
    return re.sub(r"\s+", " ", "".join(c for c in text if not unicodedata.combining(c))).strip()


def _bounded_match(term: str, text: str) -> bool:
    term = _normalize(term)
    if " " in term:
        pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
    else:
        # Whole emails; aliases can carry a leading @ and sentence punctuation.
        prefix = "" if "@" in term else "@?"
        pattern = r"(?<![\w@.+-])" + prefix + re.escape(term) + r"(?![\w@+-]|\.[\w])"
    return bool(re.search(pattern, _normalize(text)))


def _matches_literally(dork: "Dork", title: str, snippet: str, url: str) -> bool:
    if dork.dni:
        return any(matches_dni(dork.dni, text) for text in (title, snippet))
    if dork.phone:
        return matches_phone_text(dork.phone, title, snippet)
    terms = QUOTED_TERM_RE.findall(dork.query)
    # Only path segments can support URL matches: reflected query strings are not evidence.
    segments = [unquote(p) for p in urlsplit(url).path.split("/") if p]
    for term in terms:
        if any(_bounded_match(term, text) for text in (title, snippet)):
            continue
        if "@" not in term and any(
            _normalize(segment.lstrip("@")) == _normalize(term)
            or (" " in term and _normalize(re.sub(r"[-._]+", " ", segment)) == _normalize(term))
            for segment in segments
        ):
            continue
        return False
    return True


class SearchResults(list):
    """Provider outcome; matched counts include duplicates to avoid unnecessary paid fallbacks."""
    def __init__(self, findings=(), *, status="ok", matched=0, usage=None):
        super().__init__(findings)
        self.status = status
        self.matched = matched
        self.usage = usage


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
    phone: Optional[str] = None
    dni: Optional[str] = None
    origin: str = "template"

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
        "con TinyFish opcional y DuckDuckGo como motores de respaldo."
    )
    category = ToolCategory.SEARCH
    required_inputs = ["full_name", "username", "email", "dni", "phone"]

    def can_run(self, context: TargetContext) -> bool:
        return bool(context.extra.get("search_queries")) or super().can_run(context) or bool(context.all_phones()) or bool(context.discovered_names) or bool(context.all_emails()) or bool(context.all_usernames())

    def _backends(self) -> List["SearchBackend"]:
        return [
            SearchBackend(
                name="tavily",
                is_available=lambda: settings.tavily_enabled,
                build_client=lambda: http_client.build_client(
                    timeout=15.0, rotate_ua=False, max_retries=0, follow_redirects=False
                ),
                search=self._search_tavily,
            ),
            SearchBackend(
                name="tinyfish",
                is_available=lambda: settings.tinyfish_enabled,
                build_client=lambda: http_client.build_client(timeout=15.0, rotate_ua=False, max_retries=0, follow_redirects=False),
                search=self._search_tinyfish,
            ),
            SearchBackend(
                name="duckduckgo",
                is_available=lambda: True,
                build_client=lambda: http_client.build_client(
                    timeout=12.0, headers=HEADERS, max_retries=0, follow_redirects=False
                ),
                search=self._search_duckduckgo,
            ),
        ]

    async def execute(self, context: TargetContext) -> List[ToolFinding]:
        dorks = self._generate_dorks(context)
        if not dorks:
            context.extra["search_last_status"] = "no_queries"
            return []
        dorks = list({(d.query, tuple(sorted(d.include_domains))): d for d in dorks}.values())

        max_queries = max(1, settings.tavily_max_queries)
        executed = context.extra.setdefault("search_queries_executed", [])
        used = context.extra.setdefault("search_queries_used", len(executed))
        if not context.extra.get("search_force"):
            dorks = [d for d in dorks if [d.query, d.include_domains] not in executed]
        # Prefer newly discovered identifiers over secondary domain variants on later rounds.
        if executed and not context.extra.get("search_queries"):
            dorks.sort(key=lambda d: bool(d.include_domains))
        dorks = dorks[:min(max(1, settings.search_max_queries_per_round), max(0, max_queries - used))]
        if not dorks:
            context.extra["search_last_status"] = "budget_exhausted" if used >= max_queries else "already_covered"
            return []
        context.extra["search_last_status"] = "completed"

        findings: List[ToolFinding] = []
        previous_urls = set(context.extra.setdefault("search_seen_urls", []))
        seen_urls = set() if context.extra.get("search_force") else set(previous_urls)
        diagnostics = context.extra.setdefault("search_diagnostics", [])
        disabled = set(context.extra.setdefault("search_disabled_backends", []))
        attempts = context.extra.setdefault("search_provider_attempts", {})
        backends = [backend for backend in self._backends() if backend.is_available()]
        clients = {}
        semaphore = asyncio.Semaphore(max(1, min(5, settings.search_query_concurrency)))

        async def search_one(dork):
            async with semaphore:
                if [dork.query, dork.include_domains] not in executed:
                    executed.append([dork.query, dork.include_domains])
                context.extra["search_queries_used"] += 1
                for backend in backends:
                    if backend.name in disabled or attempts.get(backend.name, 0) >= max_queries:
                        continue
                    # Reservation occurs without awaiting, so concurrent queries share one budget.
                    attempts[backend.name] = attempts.get(backend.name, 0) + 1
                    try:
                        result = await backend.search(clients[backend.name], dork, seen_urls)
                    except (httpx.HTTPError, ValueError, TypeError, KeyError):
                        result = SearchResults(status="request_error")
                    status = getattr(result, "status", "ok")
                    diagnostics.append({"engine": backend.name, "query": dork.query,
                                        "status": status, "findings": len(result),
                                        "usage": getattr(result, "usage", None)})
                    findings.extend(result)
                    if status in {"http_401", "http_402", "http_403", "http_429", "http_432"}:
                        disabled.add(backend.name)
                    if getattr(result, "matched", len(result)):
                        break

        try:
            async with asyncio.timeout(max(1, settings.search_timeout_seconds)):
                async with AsyncExitStack() as stack:
                    for backend in backends:
                        clients[backend.name] = await stack.enter_async_context(backend.build_client())
                    # TaskGroup cancels and joins outstanding requests on deadline or error.
                    async with asyncio.TaskGroup() as group:
                        for dork in dorks:
                            group.create_task(search_one(dork))
        except TimeoutError:
            context.extra["search_last_status"] = "deadline_exceeded"
            diagnostics.append({"engine": "coordinator", "status": "deadline_exceeded"})
        context.extra["search_disabled_backends"] = sorted(disabled)
        context.extra["search_seen_urls"] = sorted(previous_urls | seen_urls)
        if settings.search_read_pages:
            from app.tools.search_reader import enrich_search_findings
            await enrich_search_findings(findings, context)
        # Keep diagnostics reviewable even if a later provider supplied the evidence.
        for finding in findings:
            finding.metadata_info["search_provider_status"] = [dict(d) for d in diagnostics[-max_queries * 3:]]
        return findings

    # -- Generación de dorks ---------------------------------------------

    def _generate_dorks(self, context: TargetContext) -> List[Dork]:
        """
        Dorks ordenados de mayor a menor poder discriminante, porque el tope de
        consultas recorta por el final.
        """
        if context.extra.get("search_queries"):
            from app.schemas.workspace import SearchQuery
            queries = [SearchQuery.model_validate(q) for q in context.extra["search_queries"]]
            return [Dork(q.query, q.rationale, q.include_domains, origin="agent") for q in queries]
        groups: List[List[Dork]] = [[], [], [], [], []]
        for email in context.all_emails()[:5]:
            groups[0].append(Dork(f'"{email}"', "Menciones públicas del correo"))
        for phone in context.all_phones()[:settings.phone_max_numbers]:
            facts = analyze_phone(phone)
            if facts["valid"] and not facts.get("extension"):
                variants = list(dict.fromkeys([facts["e164"], facts["international"], facts["national"]]))
                groups[1].append(Dork(" OR ".join(f'"{v}"' for v in variants), "Menciones públicas del teléfono", phone=phone))
        dni = normalize_dni(context.dni)
        if dni:
            groups[2].append(Dork(f'"{dni}"', "DNI en documentos públicos", dni=dni))
        for username in context.all_usernames()[:5]:
            groups[3].append(Dork(f'"{username}"', "Menciones del alias"))
        names = list(dict.fromkeys([context.full_name] if context.full_name else context.discovered_names))[:3]
        for name in names:
            name = name.strip()
            if not name:
                continue
            uni = (context.university or "").strip()
            query = f'"{name}" "{uni}"' if uni else f'"{name}"'
            groups[4].append(Dork(query, "Nombre y afiliación" if uni else "Menciones del nombre completo"))
        # Give each identifier class a slot before extra phones/emails or site variants.
        dorks = [group[i] for i in range(max(map(len, groups), default=0)) for group in groups if i < len(group)]
        if context.university:
            for name in names:
                if name.strip():
                    dorks.append(Dork(f'"{name.strip()}"', "Menciones del nombre completo"))
        for name in names:
            if name.strip():
                dorks.append(Dork(f'"{name.strip()}"', "Perfiles del nombre", include_domains=PROFILE_DOMAINS))
        for username in context.all_usernames()[:5]:
            dorks.append(Dork(f'"{username}"', "Perfiles del alias", include_domains=PROFILE_DOMAINS))
        if dni:
            dorks.extend([
                Dork(f'"{dni}"', "Publicaciones abiertas de RENIEC", include_domains=["reniec.gob.pe"], dni=dni),
                Dork(f'"{dni}"', "Datos abiertos institucionales", include_domains=["gob.pe", "datosabiertos.gob.pe"], dni=dni),
            ])
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
        payload["exact_match"] = settings.tavily_exact_match and not bool(dork.phone)
        payload["include_usage"] = True
        if dork.include_domains:
            payload["include_domains"] = dork.include_domains
            payload["include_domains_mode"] = "restrict"
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
        return self._parse_api_response(resp, dork, seen_urls, "tavily")

    async def _search_tinyfish(self, client: httpx.AsyncClient, dork: Dork, seen_urls: set[str]) -> SearchResults:
        params = {"query": dork.query, "location": settings.tinyfish_location,
                  "language": settings.tinyfish_language}
        if dork.include_domains:
            params["include_domains"] = ",".join(dork.include_domains)
        resp = await http_client.get(client, "https://api.search.tinyfish.ai", params=params,
                                     headers={"X-API-Key": settings.tinyfish_api_key.get_secret_value()})
        return self._parse_api_response(resp, dork, seen_urls, "tinyfish")

    def _parse_api_response(self, resp: httpx.Response | None, dork: Dork, seen_urls: set[str], engine: str) -> SearchResults:
        if resp is None:
            return SearchResults(status="request_error")
        if resp.status_code != 200:
            return SearchResults(status=f"http_{resp.status_code}")
        try:
            data = resp.json()
        except ValueError:
            return SearchResults(status="invalid_json")
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            return SearchResults(status="invalid_payload")
        usage = data.get("usage")
        credits = usage.get("credits") if isinstance(usage, dict) else None
        usage = {"credits": credits} if isinstance(credits, (int, float)) and math.isfinite(credits) else None
        result = SearchResults(usage=usage)
        for item in data["results"][:max(1, min(20, settings.tavily_max_results))]:
            if not isinstance(item, dict):
                continue
            finding = self._validated_finding(dork, item.get("url"), item.get("title"),
                                              item.get("content") if engine == "tavily" else item.get("snippet"),
                                              engine, item.get("score"))
            if finding:
                result.matched += 1
                if finding.value not in seen_urls:
                    seen_urls.add(finding.value)
                    result.append(finding)
        if not result.matched:
            result.status = "no_verified_matches"
        return result

    def _validated_finding(self, dork: Dork, url: Any, title: Any, snippet: Any, engine: str, relevance: Any = None) -> ToolFinding | None:
        if not isinstance(url, str) or not public_source_url(url):
            return None
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        if dork.include_domains and not any(host == d or host.endswith("." + d) for d in dork.include_domains):
            return None
        title = title if isinstance(title, str) else ""
        snippet = snippet if isinstance(snippet, str) else ""
        literal = _matches_literally(dork, title, snippet, url)
        if not literal and (dork.phone or dork.dni or settings.tavily_require_literal_match):
            return None
        return self._build_finding(url=url, title=title, snippet=snippet, dork=dork,
                                   engine=engine, relevance=relevance, literal=literal)

    # -- Motor de respaldo: DuckDuckGo ------------------------------------

    async def _search_duckduckgo(
        self, client: httpx.AsyncClient, dork: Dork, seen_urls: set
    ) -> List[ToolFinding]:
        result = SearchResults()
        try:
            resp = await client.post("https://html.duckduckgo.com/html/", data={"q": dork.as_text_query()})
            if resp.status_code != 200:
                return SearchResults(status=f"http_{resp.status_code}")
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.find_all("div", class_="result")[:5]:
                title_tag = row.find("a", class_="result__a")
                if not title_tag:
                    continue
                url = title_tag.get("href", "")
                if "uddg=" in url:
                    match = re.search(r"uddg=([^&]+)", url)
                    if match:
                        url = unquote(match.group(1))
                snippet_tag = row.find("a", class_="result__snippet")
                finding = self._validated_finding(dork, url, title_tag.get_text(" ", strip=True),
                                                 snippet_tag.get_text(" ", strip=True) if snippet_tag else "", "duckduckgo")
                if finding:
                    result.matched += 1
                    if finding.value not in seen_urls:
                        seen_urls.add(finding.value)
                        result.append(finding)
        except httpx.HTTPError:
            return SearchResults(status="request_error")
        if not result.matched:
            result.status = "no_verified_matches"
        return result

    # -- Común ------------------------------------------------------------

    def _detect_platform(self, url: str) -> str:
        low = (urlsplit(url).hostname or "").lower()
        for domain, platform in PLATFORM_DOMAINS.items():
            if low == domain or low.endswith("." + domain):
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
        if not public_source_url(url):
            return None

        platform = self._detect_platform(url)

        # Tavily puntúa la relevancia de cada resultado; se traslada a la
        # confianza en lugar de asignar 0.60 plano a todo. Aun así se acota:
        # que un resultado sea relevante para la consulta no prueba que la
        # persona mencionada sea el objetivo y no un homónimo.
        try:
            relevance = float(relevance) if relevance is not None else None
            if relevance is not None and not math.isfinite(relevance):
                relevance = None
        except (ValueError, TypeError, OverflowError):
            relevance = None
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
                "query_origin": dork.origin,
                "rationale": dork.rationale,
                "engine": engine,
                "relevance_score": relevance,
                "literal_match": literal,
                "url": url,
                "source_tool": "search_dorker",
                "phones": [item["phone"] for item in extract_phone_observations(f"{title}\n{snippet}",
                           analyze_phone(dork.phone).get("country_iso", "PE") if dork.phone else "PE")],
                "dni_query": dork.dni,
                "dni_mention_status": "observed_in_search_result" if dork.dni else None,
                "phone_query": dork.phone,
                "phone_mention_status": "observed_in_search_result" if dork.phone else None,
                "ownership_status": "unverified",
            },
            confidence=confidence,
            evidence_urls=[url],
        )
