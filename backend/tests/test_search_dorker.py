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
            "title": "Blog de Juan Perez",
            "url": "https://ejemplo.pe/nota",
            "content": "Mención de Juan Perez en un blog.",
            "score": 0.20,
        },
    ],
    "response_time": 1.2,
}

# Caso real observado contra la API: al buscar un correo inexistente, Tavily
# devuelve por relevancia semántica la portada del dominio, sin que el término
# buscado aparezca en ninguna parte del resultado.
TAVILY_SEMANTIC_NOISE = {
    "query": '"jperez@untumbes.edu.pe"',
    "results": [
        {
            "title": "Universidad Nacional de Tumbes",
            "url": "https://untumbes.edu.pe/index.php",
            "content": "Portal institucional de la universidad.",
            "score": 0.55,
        }
    ],
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
    assert body["search_depth"] == settings.tavily_search_depth
    assert body["max_results"] == settings.tavily_max_results
    # `exact_match` NO debe enviarse: verificado contra la API real, devuelve
    # cero resultados siempre (con y sin comillas), dejando el dorking mudo.
    assert "exact_match" not in body


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
async def test_semantic_noise_is_discarded(context, with_tavily_key):
    """
    Tavily busca por relevancia semántica: un dork de un correo inexistente
    devuelve la portada del dominio. Ese falso positivo acabaría en el
    expediente de una persona, así que se descarta al no contener literalmente
    el término entrecomillado.
    """
    respx.post(TAVILY_URL).mock(
        return_value=httpx.Response(200, json=TAVILY_SEMANTIC_NOISE)
    )
    ddg = respx.post(DDG_URL).mock(return_value=httpx.Response(500))

    findings = await SearchDorkerTool().execute(context)

    assert findings == []
    # Al quedarse sin resultados literales, intenta el motor de respaldo.
    assert ddg.called


@pytest.mark.asyncio
@respx.mock
async def test_literal_results_are_kept(context, with_tavily_key):
    """El control de exactitud no debe descartar coincidencias reales."""
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=TAVILY_RESPONSE))

    findings = await SearchDorkerTool().execute(context)

    assert len(findings) == 3
    assert all(f.metadata_info["literal_match"] is True for f in findings)


def test_literal_match_tolerates_url_separators():
    """
    En las URLs el nombre viaja con guiones o puntos ("juan-perez"), así que la
    comprobación compara también una versión sin separadores.
    """
    from app.tools.search_dorker import Dork, _matches_literally

    dork = Dork('"Juan Perez"', "prueba")
    assert _matches_literally(dork, "Perfil", "", "https://x.com/juan-perez")
    assert _matches_literally(dork, "JUAN PEREZ", "", "https://x.com/otro")
    assert not _matches_literally(dork, "Universidad", "Portal", "https://untumbes.edu.pe")


def test_multi_term_dork_requires_all_terms():
    """
    Un dork `"Juan Perez" "Universidad X"` pide ambas cosas. Si bastara con que
    coincidiera una, la portada de la universidad entraría en el expediente de
    cualquier alumno.
    """
    from app.tools.search_dorker import Dork, _matches_literally

    dork = Dork('"Juan Perez" "Universidad Nacional de Tumbes"', "prueba")

    assert not _matches_literally(
        dork, "Universidad Nacional de Tumbes", "Portal", "https://untumbes.edu.pe"
    )
    assert _matches_literally(
        dork,
        "Juan Perez - Universidad Nacional de Tumbes",
        "Tesis de grado",
        "https://repositorio.untumbes.edu.pe/123",
    )


def test_dork_without_quotes_imposes_no_restriction():
    from app.tools.search_dorker import Dork, _matches_literally

    assert _matches_literally(Dork("consulta libre", "prueba"), "algo", "", "https://x.pe")


@pytest.mark.asyncio
@respx.mock
async def test_malformed_tavily_payload_does_not_raise(context, with_tavily_key):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, text="no soy json"))
    respx.post(DDG_URL).mock(return_value=httpx.Response(500))

    assert await SearchDorkerTool().execute(context) == []


# --- Motores enchufables (Fase 4.5) ---------------------------------------


def test_the_engines_are_a_table_not_a_branch():
    """
    Añadir un motor debe ser una entrada más en la tabla, no una rama nueva
    dentro de `execute`. Es la única mejora que pedía este apartado del plan:
    arquitectónica, no de cobertura.
    """
    from app.tools.search_dorker import SearchDorkerTool

    backends = SearchDorkerTool()._backends()

    assert [b.name for b in backends] == ["tavily", "duckduckgo"]


def test_the_free_engine_is_always_available():
    """
    El de respaldo no puede depender de configuración: si lo hiciera, un
    proyecto sin claves se quedaría sin dorking en silencio.
    """
    from app.tools.search_dorker import SearchDorkerTool

    duckduckgo = SearchDorkerTool()._backends()[-1]

    assert duckduckgo.name == "duckduckgo"
    assert duckduckgo.is_available() is True


def test_tavily_is_only_offered_when_configured(monkeypatch):
    from app.core.config import settings
    from app.tools.search_dorker import SearchDorkerTool

    tavily = SearchDorkerTool()._backends()[0]

    monkeypatch.setattr(settings, "tavily_api_key", None)
    assert tavily.is_available() is False

    monkeypatch.setattr(settings, "tavily_api_key", "tvly-x")
    assert tavily.is_available() is True


def test_each_engine_brings_its_own_client():
    """
    No comparten cliente a propósito: Tavily es una API y quiere un User-Agent
    estable; el raspado de DuckDuckGo necesita cabeceras de navegador.
    """
    from app.tools.search_dorker import SearchDorkerTool

    for backend in SearchDorkerTool()._backends():
        client = backend.build_client()
        assert client is not None
