"""
Red de seguridad del comprobador de contraseñas filtradas.

Esta funcionalidad se implementó **entera en el navegador**, y esa decisión es
toda su defensa: si la contraseña llegara al backend, la promesa de no guardarla
sería exactamente igual de creíble que la de cualquier web que pide contraseñas,
es decir, nada creíble.

Los tests viven en el backend aunque el código sea TypeScript porque lo que
vigilan es una propiedad del sistema completo —"la contraseña no cruza la
frontera"— y porque es el único banco de pruebas que este proyecto ejecuta. Son
estructurales, del mismo tipo que `test_an_og_image_is_not_treated_as_an_avatar`:
leen la fuente y comprueban que nadie ha reintroducido el fallo.
"""

from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent.parent
LIB = RAIZ / "frontend" / "src" / "lib" / "pwnedPasswords.ts"
COMPONENTE = (
    RAIZ / "frontend" / "src" / "components" / "security" / "PasswordExposureCheck.tsx"
)


@pytest.fixture(scope="module")
def lib() -> str:
    return LIB.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def componente() -> str:
    return COMPONENTE.read_text(encoding="utf-8")


# --- La frontera: la contraseña no llega al servidor -----------------------


def test_the_check_never_goes_through_our_backend(lib):
    """
    La petición sale del navegador directa al servicio. Verificado en vivo el
    2026-09-05: la API responde `Access-Control-Allow-Origin: *`, así que no hay
    ninguna necesidad de un proxy propio, y montarlo solo serviría para que las
    contraseñas de los usuarios pasaran por nuestros logs.
    """
    assert "https://api.pwnedpasswords.com/range/" in lib

    for prohibido in ("@/lib/api", "localhost:8000", "API_BASE", "NEXT_PUBLIC_API"):
        assert prohibido not in lib, f"la comprobación pasa por el backend vía {prohibido}"


def test_no_backend_route_receives_a_password():
    """
    Si algún día alguien añade un endpoint que reciba contraseñas, este test cae
    antes de que llegue a producción.
    """
    api = RAIZ / "backend" / "app" / "api"
    culpables = []

    for fichero in api.rglob("*.py"):
        texto = fichero.read_text(encoding="utf-8").lower()
        if "password" in texto or "contrasena" in texto:
            culpables.append(fichero.name)

    assert not culpables, f"la API menciona contraseñas en: {culpables}"


def test_only_the_prefix_leaves_the_browser(lib):
    """
    El k-anonimato es todo o nada: enviar el hash completo convertiría esto en
    una filtración voluntaria. La longitud está fijada en una constante para que
    cambiarla sea un acto deliberado y visible en el diff.
    """
    assert "export const PREFIX_LENGTH = 5;" in lib
    assert "hash.slice(0, PREFIX_LENGTH)" in lib

    # El sufijo se calcula pero solo para comparar en local: nunca se concatena
    # a la URL de la petición.
    assert "RANGE_ENDPOINT + prefix" in lib
    assert "RANGE_ENDPOINT + hash" not in lib
    assert "+ suffix" not in lib


# --- No se persiste nada ---------------------------------------------------


def test_nothing_is_persisted(lib, componente):
    """
    Ni almacenamiento del navegador, ni cookies, ni caché. El estado vive en el
    componente y muere con él, que es la única forma de que "no se guarda" sea
    una afirmación sobre el código y no sobre las intenciones.
    """
    for fuente in (lib, componente):
        for prohibido in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"):
            assert prohibido not in fuente, f"el comprobador persiste vía {prohibido}"


def test_the_password_is_never_put_in_a_url(componente):
    """
    Un `GET` con la contraseña en la query la dejaría en el historial del
    navegador, en los logs del proxy y en el `Referer`. La única forma de que
    eso no ocurra es que el formulario no navegue.
    """
    assert "e.preventDefault()" in componente
    assert "method=" not in componente


# --- La trampa del relleno -------------------------------------------------


def test_padding_entries_cannot_be_read_as_a_hit(lib):
    """
    Con `Add-Padding` el servicio inyecta sufijos falsos con contador 0 —medidos
    entre 112 y 157 por consulta el 2026-09-05— para que el tamaño de la
    respuesta no delate cuántas coincidencias reales hay.

    El fallo que eso habilita es sutil: un cliente que comprobara solo la
    pertenencia a la lista, sin leer el contador, podría declarar filtrada una
    contraseña por haber coincidido con relleno inventado. `parseRange` devuelve
    el contador precisamente para que 0 signifique lo mismo que ausente.
    """
    assert "Add-Padding" in lib
    assert "export function parseRange" in lib
    assert "Number.parseInt" in lib
    # Devuelve el contador, no un booleano de pertenencia.
    assert "export function parseRange(body: string, suffix: string): number" in lib


def test_the_result_is_reset_when_the_password_changes(componente):
    """
    Un veredicto que sobreviviera al cambio de contraseña estaría describiendo
    otra cadena distinta de la que se ve en pantalla. Es el mismo error de
    categoría que pintar un hallazgo con la certeza de otro.
    """
    assert "setResult(null)" in componente


# --- Coherencia con la minimización que ya practica el backend -------------


def test_the_dossier_still_refuses_to_store_passwords():
    """
    Añadir un comprobador de contraseñas no puede relajar la regla que ya regía:
    de Hudson Rock se guarda el hecho de la exposición, nunca las credenciales.
    `top_passwords` sigue fuera de la lista blanca.
    """
    from app.tools.infostealer_checker import STEALER_FIELDS

    assert "top_passwords" not in STEALER_FIELDS
    assert "passwords" not in STEALER_FIELDS
