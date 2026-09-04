"""
Tests del presupuesto de concurrencia y de la huella de configuración.

El diseño anterior tenía un solo semáforo global de 40 peticiones, y eso
confundía dos cosas distintas: la **cortesía** con cada host y el **consumo de
recursos** del proceso. Mandar 500 peticiones a 500 hosts distintos no molesta a
nadie, pero el tope global lo trataba igual que 500 peticiones al mismo host.
Medido: `username_finder` acaparaba 30 de las 40 ranuras y dejaba 10 para las
otras diecisiete herramientas de la ronda.

Lo que estos tests protegen es que los dos límites sigan siendo independientes,
y que ninguna herramienta pueda volver a quedarse con el presupuesto entero.
"""

import asyncio

import pytest

from app.core.config import settings
from app.core.fingerprint import run_fingerprint
from app.tools import http_client
from app.tools.username_finder import UsernameFinderTool


@pytest.fixture(autouse=True)
def _clean_gates():
    """Los semáforos se cachean por proceso; cada test parte de cero."""
    http_client.reset_concurrency_gates()
    yield
    http_client.reset_concurrency_gates()


# --- Cuota por herramienta -----------------------------------------------


def test_no_single_tool_can_take_the_whole_budget():
    """
    El fallo original: `username_finder` pedía 30 ranuras de un presupuesto de
    40 y mataba de inanición al resto de la ronda. Ahora la cuota lo impide por
    construcción, pida lo que pida.
    """
    budget = settings.tool_concurrency_budget(10_000)

    assert budget < settings.http_max_concurrency
    assert budget <= int(settings.http_max_concurrency * settings.tool_concurrency_share)


def test_a_modest_request_is_granted_intact():
    assert settings.tool_concurrency_budget(5) == 5


def test_the_budget_is_never_zero():
    """Una cuota de 0 colgaría la herramienta para siempre en su semáforo."""
    assert settings.tool_concurrency_budget(0) >= 1
    assert settings.tool_concurrency_budget(-3) >= 1


def test_the_quota_follows_the_global_budget(monkeypatch):
    """Subir o bajar el tope global reparte solo, sin tocar cada herramienta."""
    monkeypatch.setattr(settings, "http_max_concurrency", 20)
    monkeypatch.setattr(settings, "tool_concurrency_share", 0.5)

    assert settings.tool_concurrency_budget(1000) == 10


def test_username_finder_asks_within_its_quota():
    """La constante 30 escrita a mano en la tool ya no existe."""
    tool = UsernameFinderTool()

    assert not hasattr(tool, "CONCURRENCY_LIMIT")
    granted = settings.tool_concurrency_budget(settings.username_scan_concurrency)
    assert 1 <= granted <= settings.http_max_concurrency


# --- Cortesía por host ----------------------------------------------------


def test_each_host_gets_its_own_gate():
    """
    La cortesía es una propiedad del host, no del proceso. Dos hosts distintos
    no deben compartir puerta: si la compartieran, volveríamos al tope global
    disfrazado.
    """
    a = http_client._get_host_semaphore("github.com")
    b = http_client._get_host_semaphore("gitlab.com")

    assert a is not b
    assert http_client._get_host_semaphore("github.com") is a


def test_the_per_host_gate_is_sized_by_configuration(monkeypatch):
    monkeypatch.setattr(settings, "http_max_per_host", 3)
    http_client.reset_concurrency_gates()

    sem = http_client._get_host_semaphore("example.com")

    assert sem._value == 3


@pytest.mark.asyncio
async def test_the_per_host_gate_actually_serialises_beyond_its_cap(monkeypatch):
    """
    Con un tope de 2, tres tareas simultáneas contra el mismo host no pueden
    estar dentro a la vez. Es la garantía que permite subir el tope global sin
    volvernos descorteses con ningún sitio concreto.
    """
    monkeypatch.setattr(settings, "http_max_per_host", 2)
    http_client.reset_concurrency_gates()
    sem = http_client._get_host_semaphore("example.com")

    inside = 0
    peak = 0

    async def worker():
        nonlocal inside, peak
        async with sem:
            inside += 1
            peak = max(peak, inside)
            await asyncio.sleep(0.02)
            inside -= 1

    await asyncio.gather(*(worker() for _ in range(6)))

    assert peak == 2


@pytest.mark.asyncio
async def test_different_hosts_do_not_block_each_other(monkeypatch):
    """Es justo el caso que el diseño anterior penalizaba sin motivo."""
    monkeypatch.setattr(settings, "http_max_per_host", 1)
    http_client.reset_concurrency_gates()

    inside = 0
    peak = 0

    async def worker(host: str):
        nonlocal inside, peak
        async with http_client._get_host_semaphore(host):
            inside += 1
            peak = max(peak, inside)
            await asyncio.sleep(0.02)
            inside -= 1

    await asyncio.gather(*(worker(f"host{i}.example.com") for i in range(5)))

    assert peak == 5


# --- Huella de configuración ----------------------------------------------


def test_the_fingerprint_records_what_changes_the_result():
    """
    `scorer_version` protege el modelo de identidad; esto protege el resto. Sin
    ello, las investigaciones medidas antes y después de ampliar el catálogo
    quedan mezcladas en la misma tabla sin que nada permita distinguirlas.
    """
    fingerprint = run_fingerprint()

    for key in (
        "tools_registered",
        "username_catalog_available",
        "username_catalog_scanned",
        "http_max_concurrency",
        "http_max_per_host",
        "username_scan_concurrency",
        "search_engine",
    ):
        assert key in fingerprint

    assert fingerprint["tools_registered"] > 0
    assert fingerprint["username_catalog_scanned"] > 0
    assert fingerprint["username_catalog_scanned"] <= fingerprint["username_catalog_available"]


def test_the_fingerprint_survives_a_broken_catalog(monkeypatch):
    """La huella es telemetría: nunca debe tumbar una investigación."""
    from app.tools.registry import tool_registry

    tool = tool_registry.get_tool("username_finder")

    def explode():
        raise RuntimeError("fichero corrupto")

    monkeypatch.setattr(tool, "catalog_size", explode)

    fingerprint = run_fingerprint()

    assert fingerprint["username_catalog_scanned"] == 0
    assert fingerprint["tools_registered"] > 0


def test_catalog_size_reports_the_cap_and_the_whole_dataset():
    tool = UsernameFinderTool()

    size = tool.catalog_size()

    assert size["available"] >= size["scanned"] > 0
    assert size["scanned"] <= settings.username_scan_max_sites
