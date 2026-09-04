"""
Tests del dorker con motores intercambiables.

Usan `respx` para simular el transporte de httpx: se verifica el parseo y la
selección de motor, nunca la red real. Es el patrón que deben seguir todas las
tools nuevas — si no trae fixture, no entra.
"""

import httpx
import pytest
import respx

from app.core.config import settings
from app.tools.base import TargetContext
from app.tools.search_dorker import SearchDorkerTool

TAVILY_URL = "https://api.tavily.com/search"
DDG_URL = "https://html.duckduckgo.com/html/"

TAVILY_RESPONSE = {
    "query": '"Juan Perez"',
    "results": [
        {
            "title": "Juan Perez | LinkedIn",
            "url": "https://www.linkedin.com/in/juanperez",
            "content": "Estudiante de Ingeniería de Sistemas en la UNT.",
            "score": 0.93,
        },
        {
            "title": "juanperez (Juan Perez) · GitHub",
            "url": "https://github.com/juanperez",
            "content": "Repositorios de seguridad.",
            "score": 0.71,
        },
        {
            "title": "Nota suelta",
            "url": "https://ejemplo.pe/nota",
            "content": "Mención en un blog.",
            "score": 0.20,
        },
    ],
    "response_time": 1.2,
}

DDG_HTML = """
<html><body>
  <div class="result">
    <a class="result__a" href="/l/?uddg=https%3A%2F%2Fgithub.com%2Fjuanperez">juanperez en GitHub</a>
    <a class="result__snippet">Perfil de desarrollo</a>
  </div>
</body></html>
"""


@pytest.fixture
def context() -> TargetContext:
    return TargetContext(
        full_name="Juan Perez",
        university="Universidad Nacional de Tumbes",
        username="juanperez",
        email="jperez@untumbes.edu.pe",
    )


@pytest.fixture
def with_tavily_key(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test-key", raising=False)
    return settings


@pytest.fixture
def without_tavily_key(monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", None, raising=False)
    return settings


# --- Generación de dorks -------------------------------------------------


def test_dorks_are_ordered_by_discriminating_power(context):
    dorks = SearchDorkerTool()._generate_dorks(context)
    queries = [d.query for d in dorks]

    # El correo es el identificador más discriminante: va primero.
    assert queries[0] == '"jperez@untumbes.edu.pe"'
    # El nombre siempre viaja entrecomillado: es lo que lo hace un dork.
    assert all('"' in q for q in queries)


def test_site_filter_is_data_not_a_string_operator(context):
    """
    Tavily filtra dominios con un parámetro nativo, así que el dork lo expresa
    como dato; solo el respaldo lo renderiza al operador `site:`.
    """
    dorks = SearchDorkerTool()._generate_dorks(context)
    profile_dork = next(d for d in dorks if d.include_domains)

    assert "site:" not in profile_dork.query
    assert "linkedin.com" in profile_dork.include_domains
    assert "site:linkedin.com" in profile_dork.as_text_query()


def test_no_dorks_without_any_identifier():
    assert SearchDorkerTool()._generate_dorks(TargetContext()) == []


# --- Motor Tavily --------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_tavily_is_used_when_key_is_configured(context, with_tavily_key):
    route = respx.post(TAVILY_URL).mock(
        return_value=httpx.Response(200, json=TAVILY_RESPONSE)
    )

    findings = await SearchDorkerTool().execute(context)

    assert route.called
    assert findings, "deberia devolver hallazgos"
    assert all(f.metadata_info["engine"] == "tavily" for f in findings)
    # Se deduplica por URL entre consultas.
    assert len(findings) == len({f.value for f in findings})


@pytest.mark.asyncio
@respx.mock
async def test_tavily_request_shape(context, with_tavily_key):
    route = respx.post(TAVILY_URL).mock(
        return_value=httpx.Response(200, json=TAVILY_RESPONSE)
    )

    await SearchDorkerTool().execute(context)

    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer tvly-test-key"

    import json

    body = json.loads(request.content)
    # `exact_match` es lo que hace que Tavily respete las comillas del dork en
    # vez de interpretarlo semánticamente y devolver homónimos.
    assert body["exact_match"] is True
    assert body["search_depth"] == settings.tavily_search_depth
    assert body["max_results"] == settings.tavily_max_results


@pytest.mark.asyncio
@respx.mock
async def test_relevance_score_maps_to_confidence(context, with_tavily_key):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=TAVILY_RESPONSE))

    findings = await SearchDorkerTool().execute(context)
    by_url = {f.value: f for f in findings}

    alta = by_url["https://www.linkedin.com/in/juanperez"]
    baja = by_url["https://ejemplo.pe/nota"]

    assert alta.confidence > baja.confidence
    # Ni el resultado más relevante llega a certeza: ser relevante para la
    # consulta no prueba que no sea un homónimo.
    assert alta.confidence <= 0.80


@pytest.mark.asyncio
@respx.mock
async def test_platform_is_detected_from_the_url(context, with_tavily_key):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=TAVILY_RESPONSE))

    findings = await SearchDorkerTool().execute(context)
    platforms = {f.value: f.platform for f in findings}

    assert platforms["https://www.linkedin.com/in/juanperez"] == "linkedin"
    assert platforms["https://github.com/juanperez"] == "github"
    assert platforms["https://ejemplo.pe/nota"] == "web_search"


# --- Respaldo ------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_falls_back_to_duckduckgo_without_key(context, without_tavily_key):
    tavily = respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json={}))
    ddg = respx.post(DDG_URL).mock(return_value=httpx.Response(200, text=DDG_HTML))

    findings = await SearchDorkerTool().execute(context)

    assert not tavily.called, "sin clave no debe llamarse a Tavily"
    assert ddg.called
    assert findings[0].value == "https://github.com/juanperez"
    assert findings[0].metadata_info["engine"] == "duckduckgo"


@pytest.mark.asyncio
@respx.mock
async def test_falls_back_when_tavily_quota_is_exhausted(context, with_tavily_key):
    """432 = plan limit exceeded. La investigación no debe quedarse sin dorks."""
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(432, json={"error": "limit"}))
    ddg = respx.post(DDG_URL).mock(return_value=httpx.Response(200, text=DDG_HTML))

    findings = await SearchDorkerTool().execute(context)

    assert ddg.called
    assert findings[0].metadata_info["engine"] == "duckduckgo"


@pytest.mark.asyncio
@respx.mock
async def test_malformed_tavily_payload_does_not_raise(context, with_tavily_key):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, text="no soy json"))
    respx.post(DDG_URL).mock(return_value=httpx.Response(500))

    assert await SearchDorkerTool().execute(context) == []
