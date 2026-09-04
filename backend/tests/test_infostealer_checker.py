"""
Tests de la fuente de registros de infostealer (Hudson Rock Cavalier).

Dos cosas se protegen aquí por encima del parseo:

1. **La puerta de consentimiento.** Es la única herramienta del registro que
   envía a un tercero la identidad de a quién se investiga. Si algún día deja
   de fallar cerrada, lo hará en silencio y nadie se enterará.
2. **La minimización de datos.** La API puede devolver contraseñas y logins en
   claro. Se copia una lista blanca de campos; si alguien la convirtiera en
   lista negra, un campo nuevo con otro nombre acabaría en la base de datos.

La forma de las respuestas está tomada de peticiones reales del 2026-09-04.
"""

import httpx
import pytest
import respx

from app.tools.base import TargetContext
from app.tools.http_client import HostRateLimiter
from app.tools.infostealer_checker import API_BASE, InfostealerCheckerTool

SIN_INFECCION = {
    "message": (
        "This email address is not associated with a computer infected by an "
        "info-stealer."
    ),
    "stealers": [],
    "total_corporate_services": 0,
    "total_user_services": 0,
}

# Forma REAL de la respuesta, copiada de una petición en vivo del 2026-09-04.
#
# Importa que sea la real y no la que uno supondría leyendo la documentación,
# porque tres detalles solo se ven contra la API:
#   - `top_logins` NO son servicios afectados pese a lo que sugiere el nombre:
#     son logins enmascarados.
#   - `ip` y `malware_path` traen la cadena literal "Not Found", no vienen vacíos.
#   - los totales aparecen tanto dentro del registro como en la raíz.
CON_INFECCION = {
    "message": "This email address is associated with a computer infected by an info-stealer.",
    "stealers": [
        {
            "date_compromised": "2026-09-03T00:43:32.000Z",
            "computer_name": "DESKTOP-CEM7788 (Carlos)",
            "operating_system": "Windows 11 Home Single Language 25H2 (Build 26200)",
            "malware_path": "Not Found",
            "ip": "Not Found",
            "antiviruses": ["Windows Defender"],
            "stealer_family": "Generic Stealer",
            "top_logins": ["c**********@gmail.com", "c*******@unmsm.edu.pe"],
            "top_passwords": ["V*******4!", "c*******3"],
            "total_corporate_services": 4,
            "total_user_services": 120,
        }
    ],
    "total_corporate_services": 4,
    "total_user_services": 120,
}


def _ctx(**kwargs) -> TargetContext:
    extra = {"self_consent": True}
    extra.update(kwargs.pop("extra", {}))
    return TargetContext(extra=extra, **kwargs)


# --- Puerta de consentimiento --------------------------------------------


def test_the_tool_refuses_to_run_without_explicit_consent():
    """
    Es la única fuente que revela a un tercero a quién se está investigando.
    Falla cerrada: sin la marca, el motor ni siquiera la despacha.
    """
    tool = InfostealerCheckerTool()

    assert tool.can_run(TargetContext(email="alguien@uni.edu.pe")) is False
    assert tool.can_run(TargetContext(email="alguien@uni.edu.pe", extra={})) is False


def test_consent_alone_is_not_enough_without_an_identifier():
    tool = InfostealerCheckerTool()

    assert tool.can_run(_ctx()) is False


def test_consent_plus_an_identifier_enables_the_tool():
    tool = InfostealerCheckerTool()

    assert tool.can_run(_ctx(email="alguien@uni.edu.pe")) is True
    assert tool.can_run(_ctx(username="cmendoza")) is True


@pytest.mark.asyncio
@respx.mock
async def test_execute_makes_no_request_at_all_without_consent():
    """
    La comprobación se repite dentro de `execute`, no solo en `can_run`: el
    agente autónomo puede invocar una herramienta directamente, saltándose el
    filtro del motor de reglas.
    """
    route = respx.get(url__startswith=API_BASE).mock(
        return_value=httpx.Response(200, json=CON_INFECCION)
    )

    tool = InfostealerCheckerTool()
    findings = await tool.execute(
        TargetContext(email="alguien@uni.edu.pe", extra={"self_consent": False})
    )

    assert findings == []
    assert route.call_count == 0


# --- Parseo ---------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_a_clean_identity_produces_no_finding():
    """`stealers: []` es la respuesta normal, no un error ni un hallazgo."""
    respx.get(url__startswith=API_BASE).mock(
        return_value=httpx.Response(200, json=SIN_INFECCION)
    )

    findings = await InfostealerCheckerTool().execute(_ctx(email="limpio@uni.edu.pe"))

    assert findings == []


@pytest.mark.asyncio
@respx.mock
async def test_an_infection_produces_a_finding_with_the_actionable_facts():
    respx.get(url__startswith=f"{API_BASE}/search-by-email").mock(
        return_value=httpx.Response(200, json=CON_INFECCION)
    )
    respx.get(url__startswith=f"{API_BASE}/search-by-username").mock(
        return_value=httpx.Response(200, json=SIN_INFECCION)
    )

    findings = await InfostealerCheckerTool().execute(_ctx(email="carlos@unmsm.edu.pe"))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.entity_type == "infostealer"
    assert finding.platform == "Generic Stealer"

    meta = finding.metadata_info
    assert meta["computer_name"] == "DESKTOP-CEM7788 (Carlos)"
    assert meta["operating_system"].startswith("Windows 11")
    assert meta["date_compromised"].startswith("2026-09-03")
    # El total del registro es el del equipo concreto, que es lo que el informe
    # afirma; el de la raíz agrega todos los equipos encontrados.
    assert meta["total_user_services"] == 120
    # El correo se expone con la clave que lee el modelo de identidad, para que
    # la señal `email_match` pueda evaluarse.
    assert meta["emails"] == ["carlos@unmsm.edu.pe"]


@pytest.mark.asyncio
@respx.mock
async def test_placeholder_values_are_dropped_instead_of_persisted():
    """
    La API rellena lo que no sabe con la cadena "Not Found". Guardarla pondría
    "Ruta del malware: Not Found" en el informe, que parece un fallo del sistema
    en vez de un dato ausente.
    """
    respx.get(url__startswith=API_BASE).mock(
        return_value=httpx.Response(200, json=CON_INFECCION)
    )

    meta = (
        await InfostealerCheckerTool().execute(_ctx(email="c@unmsm.edu.pe"))
    )[0].metadata_info

    assert "malware_path" not in meta
    assert "ip" not in meta


@pytest.mark.asyncio
@respx.mock
async def test_masked_logins_are_not_relabelled_as_affected_services():
    """
    `top_logins` son logins enmascarados, no servicios, pese a lo que sugiere el
    nombre. Presentarlos como "servicios afectados" habría metido una afirmación
    falsa en el expediente de una persona concreta.
    """
    respx.get(url__startswith=API_BASE).mock(
        return_value=httpx.Response(200, json=CON_INFECCION)
    )

    meta = (
        await InfostealerCheckerTool().execute(_ctx(email="c@unmsm.edu.pe"))
    )[0].metadata_info

    assert "affected_services" not in meta
    assert "top_logins" not in meta


@pytest.mark.asyncio
@respx.mock
async def test_credentials_are_never_persisted():
    """
    El requisito de minimización. La lista blanca es la que garantiza que un
    campo sensible nuevo, con un nombre que nadie previó, no se cuele.
    """
    respx.get(url__startswith=API_BASE).mock(
        return_value=httpx.Response(200, json=CON_INFECCION)
    )

    findings = await InfostealerCheckerTool().execute(_ctx(email="carlos@unmsm.edu.pe"))

    serialised = repr(findings[0].metadata_info)
    for secret in ("V*******4!", "c*******3", "top_passwords", "top_logins"):
        assert secret not in serialised


@pytest.mark.asyncio
@respx.mock
async def test_one_infection_found_twice_stays_one_entity():
    """
    El mismo equipo aparece al consultar por correo y por alias. Sin una clave
    estable, una sola infección produciría dos entidades y el expediente diría
    que la persona tiene dos máquinas comprometidas.
    """
    respx.get(url__startswith=API_BASE).mock(
        return_value=httpx.Response(200, json=CON_INFECCION)
    )

    findings = await InfostealerCheckerTool().execute(
        _ctx(email="carlos@unmsm.edu.pe", username="cmendoza")
    )

    assert len(findings) == 1


@pytest.mark.asyncio
@respx.mock
async def test_an_api_failure_is_silent_and_harmless():
    respx.get(url__startswith=API_BASE).mock(return_value=httpx.Response(503))

    findings = await InfostealerCheckerTool().execute(_ctx(email="carlos@unmsm.edu.pe"))

    assert findings == []


@pytest.mark.asyncio
@respx.mock
async def test_malformed_json_does_not_raise():
    respx.get(url__startswith=API_BASE).mock(
        return_value=httpx.Response(200, text="no soy json")
    )

    findings = await InfostealerCheckerTool().execute(_ctx(email="carlos@unmsm.edu.pe"))

    assert findings == []


# --- Límite de tasa por host ---------------------------------------------


@pytest.mark.asyncio
async def test_the_rate_limiter_holds_the_published_ceiling():
    """
    Hudson Rock publica 50 peticiones cada 10 s por host. El semáforo por host
    acota cuántas hay A LA VEZ, no cuántas POR SEGUNDO: sin esta ventana, una
    investigación con varios correos y alias descubiertos se salta el límite y
    la primera demo se lleva un 429.
    """
    limiter = HostRateLimiter(max_requests=3, per_seconds=60.0)

    for _ in range(3):
        await limiter.acquire()

    assert len(limiter._hits) == 3


@pytest.mark.asyncio
async def test_the_rate_limiter_lets_the_window_slide():
    limiter = HostRateLimiter(max_requests=2, per_seconds=0.05)

    await limiter.acquire()
    await limiter.acquire()
    # La tercera espera a que la ventana avance en vez de fallar.
    await limiter.acquire()

    assert len(limiter._hits) <= 2 + 1


def test_the_hudson_rock_limit_is_declared_next_to_its_endpoint():
    """Que el límite viva junto al endpoint es lo que evita que se olvide."""
    from app.tools import http_client, infostealer_checker

    limiter = http_client._host_rate_limits.get(infostealer_checker.API_HOST)

    assert limiter is not None
    assert limiter.max_requests == 50
    assert limiter.per_seconds == 10.0


# --- Categoría del hallazgo en la resolución de identidad -----------------


@pytest.mark.asyncio
async def test_an_infostealer_is_not_a_homonym_candidate():
    """
    Un equipo comprometido no es un perfil que atribuir: es un hecho sobre el
    correo o el alias que la propia persona aportó. Pasarlo por la resolución de
    homónimos producía la contradicción de marcarlo "descartado" y a la vez
    contarlo como riesgo crítico en el scorecard.
    """
    import uuid as _uuid

    from app.identity.resolver import identity_resolver
    from app.models.entity import Entity
    from app.models.target import Target

    def _entity(entity_type: str, score: float) -> Entity:
        return Entity(
            id=_uuid.uuid4(),
            investigation_id=_uuid.uuid4(),
            entity_type=entity_type,
            platform="x",
            value=f"{entity_type}-1",
            display_name=entity_type,
            metadata_info={},
            confidence=score,
            existence_confidence=score,
            identity_score=score,
            verified=False,
            source_tool="infostealer_checker",
        )

    perfil = _entity("social_account", 0.9)
    equipo = _entity("infostealer", 0.02)

    clusters = await identity_resolver.resolve_clusters(
        _uuid.uuid4(), [perfil, equipo], Target(full_name="Carlos Mendoza"), []
    )

    por_estado = {c.scoring_breakdown["status"]: c for c in clusters}
    assert "identifier_bound" in por_estado
    assert str(equipo.id) in por_estado["identifier_bound"].entity_ids

    # Y sobre todo: NO aparece entre los homónimos descartados.
    descartados = por_estado.get("homonym_discarded")
    if descartados is not None:
        assert str(equipo.id) not in descartados.entity_ids


@pytest.mark.asyncio
async def test_the_alias_match_no_longer_carries_the_attribution():
    """
    Antes, un registro hallado buscando el alias puntuaba 0.893 con UNA sola
    señal evaluable: `username_match = 1.0`. Encontrarlo por ese alias garantiza
    la coincidencia, así que no es evidencia de nada. Es el mismo fallo que en
    su día hacía que `xboxgamertag.com/search/<alias>` puntuara 0.99.
    """
    from app.identity.scorer import compute_identity_score
    from app.models.target import Target

    score, breakdown = compute_identity_score(
        display_name="Equipo comprometido",
        value="infostealer:DESKTOP-X:2026-09-03",
        metadata={
            "username": "admin",
            "source_tool": "infostealer_checker",
            "source_tools": ["infostealer_checker"],
        },
        target=Target(username="admin", full_name="Carlos Mendoza"),
    )

    assert breakdown.get("username_match_applicable") is False
    assert score < 0.40
