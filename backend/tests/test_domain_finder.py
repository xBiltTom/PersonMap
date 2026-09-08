"""
Tests del descubrimiento de infraestructura personal vía crt.sh.

Lo importante aquí no es el parseo de los certificados, es **de quién es el
dominio**. Meter los subdominios de `unmsm.edu.pe` en el expediente de un
estudiante sería atribuirle una infraestructura que es de su universidad — el
mismo error de categoría que atribuirle una cuenta ajena.

Forma de la respuesta tomada de una petición real a crt.sh del 2026-09-04.
"""

import httpx
import pytest
import respx

from app.tools.base import TargetContext
from app.tools.domain_finder import (
    MAX_SUBDOMAINS_FOR_PERSONAL,
    DomainFinderTool,
)

CRT = "https://crt.sh/"


def _cert(name_value: str) -> dict:
    return {
        "id": 1,
        "issuer_name": 'C=US, O="Let\'s Encrypt", CN=R11',
        "common_name": name_value.splitlines()[0],
        "name_value": name_value,
        "not_before": "2026-07-14T10:00:00",
        "not_after": "2026-10-12T10:00:00",
    }


RESPUESTA_PERSONAL = [
    _cert("juan.dev\nwww.juan.dev"),
    _cert("staging.juan.dev"),
    _cert("*.juan.dev"),
    _cert("grafana.juan.dev"),
]


def _ctx(**extra) -> TargetContext:
    base = {"candidate_urls": [], "investigation_id": None}
    base.update(extra)
    return TargetContext(extra=base)


# --- ¿De quién es el dominio? --------------------------------------------


def test_free_providers_are_never_queried():
    """El dominio de Gmail es de Google, no de la persona."""
    tool = DomainFinderTool()

    assert tool._candidate_domains(_ctx(email="carlos@gmail.com")) == []


def test_institutional_domains_are_never_queried():
    tool = DomainFinderTool()

    ctx = _ctx(candidate_urls=["https://www.unmsm.edu.pe/facultad"])
    ctx.email = "carlos@unmsm.edu.pe"

    assert tool._candidate_domains(ctx) == []


def test_known_platforms_are_never_queried():
    """
    `github.com` es una plataforma, no la web de nadie. La lista sale del
    catálogo que ya mantiene `dataset_adapter`, para no duplicar una segunda
    lista que se desincronizaría.
    """
    tool = DomainFinderTool()

    candidatos = tool._candidate_domains(
        _ctx(candidate_urls=["https://github.com/jperez", "https://www.tiktok.com/@x"])
    )

    assert candidatos == []


def test_a_personal_domain_is_kept():
    tool = DomainFinderTool()

    candidatos = tool._candidate_domains(
        _ctx(candidate_urls=["https://juan.dev/blog", "https://github.com/juan"])
    )

    assert candidatos == ["juan.dev"]


def test_the_www_prefix_does_not_create_a_second_candidate():
    tool = DomainFinderTool()

    candidatos = tool._candidate_domains(
        _ctx(candidate_urls=["https://www.juan.dev/", "https://juan.dev/cv"])
    )

    assert candidatos == ["juan.dev"]


def test_the_tool_stays_idle_without_a_personal_domain():
    """Sin dominio candidato no debe despacharse en cada ronda para nada."""
    tool = DomainFinderTool()

    assert tool.can_run(_ctx(email="carlos@gmail.com")) is False
    assert tool.can_run(_ctx(candidate_urls=["https://juan.dev"])) is True


# --- Parseo de los certificados -------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_subdomains_are_extracted_and_deduplicated():
    respx.get(url__startswith=CRT).mock(
        return_value=httpx.Response(200, json=RESPUESTA_PERSONAL)
    )

    findings = await DomainFinderTool().execute(
        _ctx(candidate_urls=["https://juan.dev"])
    )

    assert len(findings) == 1
    meta = findings[0].metadata_info
    assert meta["domain"] == "juan.dev"
    assert "staging.juan.dev" in meta["subdomains"]
    assert "grafana.juan.dev" in meta["subdomains"]
    # El comodín no es un subdominio que visitar, y el dominio raíz no es su
    # propio subdominio.
    assert "*.juan.dev" not in meta["subdomains"]
    assert "juan.dev" not in meta["subdomains"]
    assert meta["subdomains"] == sorted(set(meta["subdomains"]))


@pytest.mark.asyncio
@respx.mock
async def test_an_organisation_domain_is_discarded_not_attributed():
    """
    El filtro que impide atribuirle a una persona la infraestructura de su
    universidad. Un portfolio personal tiene un puñado de subdominios; una
    organización, cientos.
    """
    muchos = [
        _cert(f"host{i}.grande.pe") for i in range(MAX_SUBDOMAINS_FOR_PERSONAL + 10)
    ]
    respx.get(url__startswith=CRT).mock(return_value=httpx.Response(200, json=muchos))

    findings = await DomainFinderTool().execute(
        _ctx(candidate_urls=["https://grande.pe"])
    )

    assert findings == []


@pytest.mark.asyncio
@respx.mock
async def test_a_degraded_source_fails_quietly():
    """
    crt.sh alterna rachas de 502 con rachas normales: medido, 1 de 4 por la
    mañana y 6 de 6 por la tarde del mismo día. Su caída no puede arrastrar al
    resto de la investigación.
    """
    respx.get(url__startswith=CRT).mock(return_value=httpx.Response(502))

    findings = await DomainFinderTool().execute(
        _ctx(candidate_urls=["https://juan.dev"])
    )

    assert findings == []


@pytest.mark.asyncio
@respx.mock
async def test_malformed_json_does_not_raise():
    respx.get(url__startswith=CRT).mock(
        return_value=httpx.Response(200, text="<html>error</html>")
    )

    findings = await DomainFinderTool().execute(
        _ctx(candidate_urls=["https://juan.dev"])
    )

    assert findings == []


@pytest.mark.asyncio
@respx.mock
async def test_a_domain_with_no_subdomains_produces_nothing():
    respx.get(url__startswith=CRT).mock(
        return_value=httpx.Response(200, json=[_cert("juan.dev")])
    )

    findings = await DomainFinderTool().execute(
        _ctx(candidate_urls=["https://juan.dev"])
    )

    assert findings == []
