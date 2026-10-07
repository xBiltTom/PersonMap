import pytest
import respx
import httpx
from app.tools.base import TargetContext
from app.tools.dni_lookup import DniLookupTool, _extract_full_name
from app.core.config import settings


def test_dni_can_run():
    tool = DniLookupTool()
    assert tool.can_run(TargetContext(dni="12345678")) is True
    assert tool.can_run(TargetContext(dni="1234567")) is False  # 7 digits
    assert tool.can_run(TargetContext(dni="123456789")) is False  # 9 digits
    assert tool.can_run(TargetContext(dni="abcdefgh")) is False
    assert tool.can_run(TargetContext()) is False


def test_extract_full_name_variants():
    # apis.net.pe variant
    assert _extract_full_name({
        "nombres": "JUAN CARLOS",
        "apellidoPaterno": "PEREZ",
        "apellidoMaterno": "GARCIA",
    }) == "JUAN CARLOS PEREZ GARCIA"

    # alternative variant
    assert _extract_full_name({
        "nombre": "MARIA",
        "ape_paterno": "QUISPE",
        "ape_materno": "MAMANI",
    }) == "MARIA QUISPE MAMANI"


@pytest.mark.asyncio
@respx.mock
async def test_dni_lookup_v2_with_token(monkeypatch):
    monkeypatch.setattr(settings, "apis_net_pe_token", "test-bearer-token")

    respx.get("https://api.apis.net.pe/v2/reniec/dni?numero=45678901").respond(
        status_code=200,
        json={
            "nombres": "CARLOS ALBERTO",
            "apellidoPaterno": "RODRIGUEZ",
            "apellidoMaterno": "FLORES",
        },
    )

    tool = DniLookupTool()
    findings = await tool.execute(TargetContext(dni="45678901"))

    assert len(findings) == 1
    f = findings[0]
    assert f.platform == "reniec_peru"
    assert f.confidence == 0.99
    assert f.display_name == "CARLOS ALBERTO RODRIGUEZ FLORES"
    assert f.metadata_info["source"] == "apis_net_pe_v2"


@pytest.mark.asyncio
@respx.mock
async def test_dni_lookup_v1_fallback(monkeypatch):
    monkeypatch.setattr(settings, "apis_net_pe_token", None)

    respx.get("https://api.apis.net.pe/v1/dni?numero=45678901").respond(
        status_code=200,
        json={
            "nombre": "ANA LUCIA",
            "apellidoPaterno": "MENDOZA",
            "apellidoMaterno": "TORRES",
        },
    )

    tool = DniLookupTool()
    findings = await tool.execute(TargetContext(dni="45678901"))

    assert len(findings) == 1
    f = findings[0]
    assert f.confidence == 0.99
    assert f.display_name == "ANA LUCIA MENDOZA TORRES"
    assert f.metadata_info["source"] == "apis_net_pe_v1"


@pytest.mark.asyncio
@respx.mock
async def test_dni_lookup_apisperu_fallback(monkeypatch):
    monkeypatch.setattr(settings, "apis_net_pe_token", None)

    # v1 fails (401 or 500)
    respx.get("https://api.apis.net.pe/v1/dni?numero=45678901").respond(status_code=401)
    # apisperu succeeds
    respx.get("https://dniruc.apisperu.com/api/dni/45678901").respond(
        status_code=200,
        json={
            "nombres": "PEDRO",
            "apellidoPaterno": "SANCHEZ",
            "apellidoMaterno": "DIAZ",
        },
    )

    tool = DniLookupTool()
    findings = await tool.execute(TargetContext(dni="45678901"))

    assert len(findings) == 1
    f = findings[0]
    assert f.confidence == 0.99
    assert f.display_name == "PEDRO SANCHEZ DIAZ"
    assert f.metadata_info["source"] == "apisperu_com"


@pytest.mark.asyncio
@respx.mock
async def test_dni_lookup_all_fail_format_only(monkeypatch):
    monkeypatch.setattr(settings, "apis_net_pe_token", None)

    respx.get("https://api.apis.net.pe/v1/dni?numero=45678901").respond(status_code=503)
    respx.get("https://dniruc.apisperu.com/api/dni/45678901").respond(status_code=503)

    tool = DniLookupTool()
    findings = await tool.execute(TargetContext(dni="45678901"))

    assert len(findings) == 1
    f = findings[0]
    assert f.confidence == 0.85
    assert f.display_name == "DNI 45678901"
    assert f.metadata_info["source"] == "format_validated"
