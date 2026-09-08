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
    catalog = tool._load_sites()
    aplicables = sum(1 for s in catalog if s.accepts_username("usuario_de_prueba"))

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
        # El total es el de sitios que SE VAN A PEDIR, no el del catálogo: los
        # descartados por formato de alias nunca gastan una petición, así que
        # incluirlos dejaría la barra clavada sin llegar nunca al 100%.
        assert event["total"] == aplicables
        assert aplicables <= len(catalog)
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
async def test_an_alias_is_never_rescanned_within_one_investigation():
    """
    El motor re-ejecuta la herramienta en cada ronda, porque su clave de
    ejecución incluye la lista de alias y el pivoteo la va ampliando. Sin este
    registro, la ronda 2 volvía a comprobar el alias de la ronda 1 y la ronda 3
    los dos anteriores: medido, 23 s + 45 s + 68 s con casi la mitad del trabajo
    repetido.
    """
    route = respx.route().mock(return_value=httpx.Response(404))

    tool = UsernameFinderTool()
    context = TargetContext(username="alias_uno", extra={})

    await tool.execute(context)
    first_pass = route.call_count
    assert first_pass > 0

    # Segunda ronda: el motor añade un alias descubierto y vuelve a llamar con
    # el MISMO contexto acumulado.
    context.discovered_usernames.append("alias_dos")
    await tool.execute(context)
    second_pass = route.call_count - first_pass

    # Solo se comprueba el alias nuevo, no los dos.
    assert second_pass == first_pass

    # Tercera ronda sin alias nuevos: no debe gastar ni una petición.
    await tool.execute(context)
    assert route.call_count == first_pass + second_pass


@pytest.mark.asyncio
@respx.mock
async def test_a_fresh_investigation_scans_the_alias_again():
    """El registro es por investigación, no global: la tool es un singleton."""
    route = respx.route().mock(return_value=httpx.Response(404))

    tool = UsernameFinderTool()

    await tool.execute(TargetContext(username="alias_uno", extra={}))
    first = route.call_count

    await tool.execute(TargetContext(username="alias_uno", extra={}))

    assert route.call_count == first * 2


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
