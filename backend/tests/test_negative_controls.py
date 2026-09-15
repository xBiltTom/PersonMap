"""
Controles negativos de la detección.

Una cuenta que no existe, presentada como de la persona, es el peor error que
puede cometer el sistema delante de ella: nada en el expediente rebate un "esa
cuenta no es mía". Estos tests fijan que un sitio o una plataforma que también
"encuentra" un identificador inventado no produce ningún hallazgo.
"""

import asyncio

import httpx
import pytest
import respx

from app.tools.base import TargetContext
from app.tools.dataset_adapter import SiteCheck
from app.tools.email_enumerator import EmailEnumeratorTool
from app.tools.username_finder import UsernameFinderTool


async def _check_site(site: SiteCheck, username: str):
    tool = UsernameFinderTool()
    counter = {"checked": 0, "control_rejected": 0}
    async with httpx.AsyncClient() as client:
        finding = await tool._check_site(
            client, username, site, asyncio.Semaphore(4), None, counter, 1
        )
    return finding, counter


# --- Alias -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_site_that_finds_any_alias_is_discarded():
    """
    Caso medido el 2026-09-10: los foros de Southklad, Starsonice y
    Terminatorium "encontraban" a JorgeWueder y también a un alias inventado.
    """
    site = SiteCheck(name="Foro", url="https://foro.example/{username}", presence=("<title>Foro",))
    with respx.mock() as router:
        router.get(url__regex=r"https://foro\.example/.+").mock(
            return_value=httpx.Response(200, html="<html><title>Foro</title></html>")
        )
        finding, counter = await _check_site(site, "JorgeWueder")

    assert finding is None
    assert counter["control_rejected"] == 1


@pytest.mark.asyncio
async def test_site_that_tells_them_apart_keeps_the_account():
    site = SiteCheck(name="Kaggle", url="https://kaggle.example/{username}", absence=("Not Found",))
    with respx.mock() as router:
        router.get("https://kaggle.example/JorgeWueder").mock(
            return_value=httpx.Response(200, html="<title>JORGE-WUEDER | Kaggle</title> JorgeWueder")
        )
        router.get(url__regex=r"https://kaggle\.example/.+").mock(
            return_value=httpx.Response(404, html="Not Found")
        )
        finding, counter = await _check_site(site, "JorgeWueder")

    assert finding is not None
    assert finding.metadata_info["negative_control"] == "passed"
    assert counter["control_rejected"] == 0


def test_invented_alias_keeps_a_shape_the_site_accepts():
    """El control no sirve si el sitio lo rechaza por formato antes de mirar."""
    site = SiteCheck(name="Formato", url="https://f.example/{username}", regex_check=r"^[a-z]+_\d{4}$")

    alias = UsernameFinderTool()._invented_alias(site, "jorge_2004")

    assert alias is not None and alias != "jorge_2004"
    assert site.accepts_username(alias)


# --- Correo ----------------------------------------------------------------


def _only_these_probes(monkeypatch, tool: EmailEnumeratorTool, **probes):
    async def nothing(client, email):
        return None

    for name in [n for n in dir(tool) if n.startswith("_check_")]:
        monkeypatch.setattr(tool, name, probes.get(name, nothing))


@pytest.mark.asyncio
async def test_platform_that_registers_any_email_is_discarded(monkeypatch):
    """
    El fallo real de Quora: su sonda daba por registrado cualquier correo. Con
    el control, una plataforma así no llega al expediente.
    """
    tool = EmailEnumeratorTool()

    async def any_email(client, email):
        return {"platform": "Quora", "registered": True, "url": "https://quora.com"}

    async def only_the_real_one(client, email):
        if email == "jorgewueder@outlook.es":
            return {"platform": "Twitter/X", "registered": True, "url": "https://x.com"}
        return None

    _only_these_probes(monkeypatch, tool, _check_spotify=any_email, _check_twitter=only_the_real_one)

    findings = await tool.execute(TargetContext(email="jorgewueder@outlook.es"))

    assert [f.platform for f in findings] == ["Twitter/X"]
    assert findings[0].metadata_info["negative_control"] == "passed"


@pytest.mark.asyncio
async def test_signup_probes_never_receive_an_invented_email(monkeypatch):
    """
    Las sondas que envían un alta completa podrían crear una cuenta real con el
    correo inventado. No se les pasa el control: el hallazgo queda "sin probar".
    """
    tool = EmailEnumeratorTool()
    seen = []

    async def discord(client, email):
        seen.append(email)
        return {"platform": "Discord", "registered": True, "url": "https://discord.com"}

    discord.__name__ = "_check_discord"
    _only_these_probes(monkeypatch, tool, _check_discord=discord)

    findings = await tool.execute(TargetContext(email="jorgewueder@outlook.es"))

    assert seen == ["jorgewueder@outlook.es"]
    assert findings[0].metadata_info["negative_control"] == "untested"
