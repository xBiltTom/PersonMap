"""
Tests de la enumeración pasiva de correo.

Existen por una razón concreta: la sonda de Quora marcaba **todos** los correos
como registrados. Su endpoint dejó de ser una API y pasó a devolver la portada
HTML de 81 KB, y la comprobación era `"false" in resp.text.lower()` — una
palabra que aparece en cualquier JavaScript. El resultado llegó a un expediente
real: "Quora: Cuenta Activa" con un 90 % de confianza, sobre un correo que nunca
tuvo cuenta allí.

Nada lo detectaba porque nada lo comprobaba. De ahí estos dos niveles:

- Rápido y sin red: que ninguna sonda vuelva a apoyarse en un marcador genérico,
  y que no se intente iniciar sesión en la cuenta de nadie.
- Marcado como `network`: cada sonda contra un correo de control que no puede
  estar registrado en ningún sitio. Cualquier "registrado" ahí es un falso
  positivo garantizado.
"""

import inspect
import re
from pathlib import Path

import pytest

from app.tools import http_client
from app.tools.base import TargetContext
from app.tools.email_enumerator import EmailEnumeratorTool

FUENTE = Path(__file__).parent.parent / "app" / "tools" / "email_enumerator.py"

# Un correo con esta pinta no está registrado en ningún servicio del mundo.
CONTROL = "no_existe_jamas_9f3a2b7c1d@gmail.com"

# Marcadores demasiado genéricos para distinguir nada dentro de una página HTML.
# "false" es el que produjo el falso positivo de Quora.
MARCADORES_PROHIBIDOS = {"false", "true", "error", "email", "taken", "ok", "user"}


def _probe_names(tool: EmailEnumeratorTool):
    return [
        name
        for name, _ in inspect.getmembers(tool, predicate=inspect.ismethod)
        if name.startswith("_check_")
    ]


# --- Estructura: que la clase de fallo no vuelva ---------------------------


def test_no_probe_matches_on_a_generic_marker():
    """
    El fallo de Quora en una línea: buscar `"false"` en el cuerpo de la
    respuesta. Un marcador de una palabra común encuentra cualquier cosa dentro
    de 81 KB de HTML.
    """
    fuente = FUENTE.read_text(encoding="utf-8")
    comparaciones = re.findall(r'"([^"]{1,12})" in resp\.text(?:\.lower\(\))?', fuente)

    genericos = [c for c in comparaciones if c.strip().lower() in MARCADORES_PROHIBIDOS]

    assert not genericos, f"marcadores demasiado genéricos: {genericos}"


def test_no_probe_attempts_a_login():
    """
    Enviar una contraseña a un endpoint de sesión es un intento de acceso real
    contra la cuenta de una persona: dispara alertas de seguridad y puede
    bloquearla. Es el mismo motivo por el que el plan descarta `ignorant` para
    teléfonos: deja de ser OSINT pasivo. La sonda de Vimeo hacía exactamente eso
    contra `vimeo.com/log_in`.

    Lo que sí es aceptable, y por eso el test mira las dos cosas juntas:

    - **Validar un alta** con una contraseña inventada: no toca ninguna cuenta
      existente, solo pregunta si el correo está libre.
    - **Consultar si una cuenta existe** sin contraseña (Adobe, Microsoft): es
      el primer paso del formulario de acceso, no una autenticación fallida.
    """
    fuente = FUENTE.read_text(encoding="utf-8")
    bloques = re.split(r"    async def (_check_\w+)", fuente)[1:]

    culpables = []
    for nombre, cuerpo in zip(bloques[0::2], bloques[1::2]):
        envia_password = re.search(r'"password"\s*:', cuerpo)
        endpoint_sesion = re.search(r"log_in|/login|/signin|sessions/new", cuerpo)
        if envia_password and endpoint_sesion:
            culpables.append(nombre)

    assert not culpables, f"sondas que intentan iniciar sesión: {culpables}"


def test_the_probe_list_matches_the_implemented_probes():
    """
    Al retirar una sonda es fácil quitar el método y dejar la llamada, o al
    revés. Lo primero rompe la herramienta; lo segundo deja código muerto que
    aparenta cobertura que no existe.
    """
    tool = EmailEnumeratorTool()
    fuente = FUENTE.read_text(encoding="utf-8")

    # La lista de sondas se pasa como referencias (`self._check_x,`) para poder
    # repetir cada una con el correo inventado del control negativo.
    llamadas = set(re.findall(r"self\.(_check_\w+),", fuente))

    assert llamadas == set(_probe_names(tool))


def test_the_description_does_not_overstate_the_coverage():
    """
    La descripción decía "20+ plataformas" cuando siete de los endpoints
    respondían 404 y no podían dar señal nunca. Es la cifra que el LLM lee para
    decidir si vale la pena llamar a la herramienta.
    """
    tool = EmailEnumeratorTool()

    assert "20+" not in tool.description
    assert len(_probe_names(tool)) >= 8


@pytest.mark.asyncio
async def test_no_emails_means_no_requests():
    findings = await EmailEnumeratorTool().execute(TargetContext())

    assert findings == []


# --- En vivo: el control que faltaba --------------------------------------


@pytest.mark.network
@pytest.mark.asyncio
async def test_no_probe_reports_a_control_address_as_registered():
    """
    La red de seguridad. Un correo sintético no puede estar registrado en
    ningún sitio, así que cualquier sonda que diga "registrado" aquí está
    inventando un hallazgo que acabará en el expediente de una persona.

    Marcado `network` porque consulta los servicios reales: es justo lo que los
    mocks no pueden comprobar, y por lo que el fallo de Quora sobrevivió.
    """
    tool = EmailEnumeratorTool()
    culpables = []

    async with http_client.build_client(timeout=10.0) as client:
        for name in _probe_names(tool):
            try:
                resultado = await getattr(tool, name)(client, CONTROL)
            except Exception:
                continue
            if isinstance(resultado, dict) and resultado.get("registered"):
                culpables.append(name)

    assert not culpables, f"falsos positivos garantizados: {culpables}"
