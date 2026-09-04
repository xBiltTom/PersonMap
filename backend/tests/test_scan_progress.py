"""
Contrato del evento de progreso del escaneo.

`username_finder` ya emitía `phase: "progress"`, pero solo con una frase. La
interfaz no podía hacer nada con eso salvo pintarlo como una línea de log más,
así que durante los minutos que dura el barrido la consola parecía congelada —
justo cuando hay un jurado mirando.

Estos tests fijan las cifras que la barra necesita. Si alguien vuelve a emitir
el evento sin `checked`/`total`, la barra desaparece en silencio y nadie se
entera hasta la sustentación.
"""

import httpx
import pytest
import respx

from app.core.events import event_bus
from app.tools.base import TargetContext
from app.tools.username_finder import UsernameFinderTool

INVESTIGATION_ID = "test-progress"


@pytest.fixture(autouse=True)
def _clean_history():
    # Síncrono a propósito: `event_bus.clear` es una corutina y una fixture
    # async necesitaría el decorador de pytest-asyncio. Aquí basta con vaciar el
    # historial del bus, que es un dict en memoria.
    event_bus._history.pop(INVESTIGATION_ID, None)
    yield
    event_bus._history.pop(INVESTIGATION_ID, None)


def _progress_events():
    return [
        e
        for e in event_bus.get_history(INVESTIGATION_ID)
        if e.get("phase") == "progress"
    ]


@pytest.mark.asyncio
@respx.mock
async def test_progress_events_carry_the_numbers_the_bar_needs():
    # Todo sitio responde 404: no interesa el hallazgo, sino el progreso.
    respx.route().mock(return_value=httpx.Response(404))

    tool = UsernameFinderTool()
    total_sites = len(tool._load_sites())

    await tool.execute(
        TargetContext(
            username="usuario_de_prueba",
            extra={"investigation_id": INVESTIGATION_ID},
        )
    )

    events = _progress_events()
    assert events, "el barrido no emitió ningún evento de progreso"

    for event in events:
        assert isinstance(event["checked"], int)
        assert event["total"] == total_sites
        assert 0 <= event["pct"] <= 100
        assert event["subject"] == "usuario_de_prueba"
        assert event["tool"] == "username_finder"


@pytest.mark.asyncio
@respx.mock
async def test_progress_advances_monotonically():
    """Una barra que retrocede es peor que no tener barra."""
    respx.route().mock(return_value=httpx.Response(404))

    tool = UsernameFinderTool()
    await tool.execute(
        TargetContext(
            username="usuario_de_prueba",
            extra={"investigation_id": INVESTIGATION_ID},
        )
    )

    checked = [e["checked"] for e in _progress_events()]

    assert checked == sorted(checked)
    assert len(set(checked)) == len(checked)


@pytest.mark.asyncio
@respx.mock
async def test_the_scan_stays_silent_without_an_investigation_id():
    """
    Sin investigación a la que publicar no debe emitirse nada: el bus retiene
    historial por investigación y colgarle eventos huérfanos lo llenaría de
    ruido que nadie va a leer.
    """
    respx.route().mock(return_value=httpx.Response(404))

    tool = UsernameFinderTool()
    await tool.execute(TargetContext(username="usuario_de_prueba", extra={}))

    assert _progress_events() == []
