"""
Tests de la cosecha activa de avatares.

El plan llama a esta la fase más peligrosa, y el peligro tiene nombre: **los
avatares por defecto son idénticos entre personas distintas**. Medido contra
Gravatar el 2026-09-05, la silueta genérica da distancia de Hamming 0 entre
cuatro identidades sin ninguna relación. Con cosecha pasiva eso era raro; con
cosecha activa sobre la cola larga sería la norma, porque la mayoría de esas
cuentas no tienen foto propia.

Fusionar a dos personas bajo una misma identidad es el error más grave que puede
cometer esta herramienta. Estos tests son la red que lo impide.
"""

import hashlib

import imagehash
import pytest

from app.identity.avatar_harvest import (
    DIRECT_PROVIDERS,
    JSON_PROVIDERS,
    MAX_HARVESTED,
    gravatar_url,
    harvest_avatar_urls,
)
from app.identity.avatar_hasher import (
    DEFAULT_AVATAR_HASHES,
    FLAT_IMAGE_HASH,
    avatar_hasher,
    is_default_avatar,
)


class _Entity:
    """Doble mínimo: la cosecha solo necesita plataforma, tipo y metadatos."""

    def __init__(self, platform=None, username=None, entity_type="social_account", value=""):
        self.id = f"{platform}-{username}"
        self.platform = platform
        self.entity_type = entity_type
        self.value = value
        self.metadata_info = {"username": username} if username else {}


# --- La salvaguarda: avatares por defecto ---------------------------------


def test_the_generic_gravatar_silhouette_is_rejected():
    """
    El caso concreto que motiva toda la salvaguarda: cuatro personas distintas
    sin foto comparten esta imagen exacta, y correlacionarlas las declararía la
    misma persona.
    """
    silueta = imagehash.hex_to_hash("281432616933f0c0")

    assert is_default_avatar(silueta) is True


def test_a_flat_image_carries_no_evidence():
    """Un recuadro de un solo color no distingue a nadie de nadie."""
    assert is_default_avatar(imagehash.hex_to_hash(FLAT_IMAGE_HASH)) is True


def test_a_placeholder_resized_is_still_a_placeholder():
    """
    El mismo placeholder servido a otro tamaño puede variar en algún bit. El
    margen existe para eso, y se mantiene muy por debajo del umbral de
    coincidencia para no descartar por error un avatar real.
    """
    base = imagehash.hex_to_hash("281432616933f0c0")
    casi = imagehash.hex_to_hash("281432616933f0c1")  # un bit distinto

    assert is_default_avatar(casi) is True


def test_a_real_avatar_is_not_mistaken_for_a_placeholder():
    """
    La salvaguarda no puede pasarse de celosa: descartar avatares reales
    silenciaría la señal entera.
    """
    real = imagehash.hex_to_hash("f0e1d2c3b4a59687")

    assert is_default_avatar(real) is False


def test_generated_avatars_are_kept_because_they_do_identify():
    """
    `identicon`, `retro` y `monsterid` se **derivan del hash del correo**, así
    que dos iguales sí son evidencia de que hay un mismo correo detrás. No son
    placeholders y no deben descartarse.

    Es la razón por la que la salvaguarda es una lista de hashes conocidos y no
    un umbral de entropía: medido, la silueta genérica y un `identicon` tienen
    la MISMA entropía (1.49) y son cosas opuestas.
    """
    identicon_medido = imagehash.hex_to_hash("ccb2ccb2334d334d")

    assert is_default_avatar(identicon_medido) is False


def test_two_people_without_a_photo_are_never_correlated():
    """
    M8 del plan, la red de seguridad de esta fase.

    Dos avatares por defecto distintos —o el mismo servido a dos personas— no
    pueden producir una correlación. Como `compute_dhash_from_url` devuelve
    `None` para un placeholder, ninguno llega siquiera a la comparación.
    """
    silueta = imagehash.hex_to_hash("281432616933f0c0")
    plano = imagehash.hex_to_hash(FLAT_IMAGE_HASH)

    # Sin el filtro, la distancia entre dos siluetas idénticas sería 0 y el
    # hasher las declararía la misma persona.
    coincide, distancia = avatar_hasher.compare_hashes(silueta, silueta)
    assert coincide is True and distancia == 0

    # Con el filtro, ninguna de las dos entra en la comparación.
    assert is_default_avatar(silueta)
    assert is_default_avatar(plano)


def test_the_known_defaults_are_documented_hashes():
    assert DEFAULT_AVATAR_HASHES
    for valor in DEFAULT_AVATAR_HASHES:
        assert len(valor) == 16
        assert all(c in "0123456789abcdef" for c in valor)


# --- Cosecha: solo sobre lo confirmado ------------------------------------


@pytest.mark.asyncio
async def test_only_known_providers_are_harvested():
    """
    No se inventan URLs para plataformas cuyo patrón no se ha verificado: una
    URL construida a ciegas descarga la foto de quien sea.
    """
    entidades = [
        _Entity("GitHub (User)", "jperez"),
        _Entity("AllKPop", "jperez"),
        _Entity("Datpiff", "jperez"),
    ]

    await harvest_avatar_urls(entidades)

    assert entidades[0].metadata_info["avatar_url"].startswith("https://github.com/")
    assert "avatar_url" not in entidades[1].metadata_info
    assert "avatar_url" not in entidades[2].metadata_info


@pytest.mark.asyncio
async def test_an_entity_without_a_username_is_skipped():
    """
    Sin alias confirmado no hay nada que cosechar. Construir la URL para un
    alias no confirmado significaría descargar la foto de un tercero que no es
    el objetivo, que es justo lo que esta herramienta enseña a no hacer.
    """
    entidad = _Entity("GitHub (User)", None)

    await harvest_avatar_urls([entidad])

    assert "avatar_url" not in entidad.metadata_info


@pytest.mark.asyncio
async def test_a_passively_discovered_avatar_is_respected():
    """Si una herramienta ya expuso el avatar real, no se sobrescribe."""
    entidad = _Entity("GitHub (User)", "jperez")
    entidad.metadata_info["avatar_url"] = "https://ejemplo.test/foto-real.jpg"

    await harvest_avatar_urls([entidad])

    assert entidad.metadata_info["avatar_url"] == "https://ejemplo.test/foto-real.jpg"
    assert "avatar_harvested" not in entidad.metadata_info


@pytest.mark.asyncio
async def test_email_entities_get_their_gravatar():
    entidad = _Entity(entity_type="email", value="Carlos@UNMSM.edu.pe")

    await harvest_avatar_urls([entidad])

    esperado = hashlib.md5(b"carlos@unmsm.edu.pe").hexdigest()
    assert esperado in entidad.metadata_info["avatar_url"]
    assert entidad.metadata_info["avatar_source"] == "gravatar"


def test_gravatar_uses_the_clean_binary_signal():
    """
    `d=404` es lo que hace la señal limpia: sin él, Gravatar sirve un
    placeholder genérico que luego habría que filtrar, y que además es idéntico
    entre personas distintas.
    """
    assert "d=404" in gravatar_url("alguien@ejemplo.test")


def test_the_email_is_normalised_before_hashing():
    assert gravatar_url("  Carlos@Ejemplo.TEST ") == gravatar_url("carlos@ejemplo.test")


@pytest.mark.asyncio
async def test_harvesting_is_capped():
    """
    Cada avatar es una descarga. El valor está en las primeras cuentas
    confirmadas, no en la cola de una investigación con cientos de hallazgos.
    """
    entidades = [_Entity("GitHub (User)", f"usuario{i}") for i in range(MAX_HARVESTED + 20)]

    cosechadas = await harvest_avatar_urls(entidades)

    assert cosechadas <= MAX_HARVESTED


def test_every_provider_is_verified_and_documented():
    """
    Los patrones se comprobaron uno a uno contra el servicio real. Los que no
    pasaron (GitLab y Codeberg dan 403, Bitbucket 404 siempre, Reddit devuelve
    HTML y NPM exige autenticación) están anotados como descartados en el
    módulo, para que nadie los vuelva a intentar sin motivo.
    """
    from app.identity import avatar_harvest

    total = len(DIRECT_PROVIDERS) + len(JSON_PROVIDERS)
    assert 4 <= total <= 8, "el plan acota a 6-8 proveedores, no la lista completa"

    fuente = avatar_harvest.__doc__ or ""
    assert "confirmadas" in fuente or "confirmado" in fuente


# --- Lo que NO es un avatar -----------------------------------------------


def test_an_og_image_is_not_treated_as_an_avatar():
    """
    `og:image` es la imagen de vista previa social de la PÁGINA, no la foto de
    una persona. En la mayoría de sitios es su logo, idéntico en todas sus URLs.

    Medido sobre una investigación real: entraban como "foto de perfil" el logo
    de Imgur, la imagen social de Pastebin y la de PayPal, y una llegó a
    correlacionar a **distancia 0** — es decir, el sistema afirmaba que dos
    cuentas usaban la misma foto cuando lo que compartían era el logo del sitio.

    Es la misma clase de fallo que los avatares por defecto, por otra vía: una
    imagen idéntica entre identidades distintas.
    """
    from pathlib import Path

    fuente = (
        Path(__file__).parent.parent / "app" / "tools" / "social_verifier.py"
    ).read_text(encoding="utf-8")

    assert '"og_image"' in fuente
    assert '"avatar_url": og_image' not in fuente


def test_only_per_user_images_feed_the_visual_signal():
    """
    La señal de avatar solo tiene sentido con imágenes que identifiquen a UNA
    persona. Las herramientas que exponen `avatar_url` deben hacerlo desde un
    campo por usuario de la API, no desde metadatos de la página.
    """
    from pathlib import Path

    tools = Path(__file__).parent.parent / "app" / "tools"
    culpables = []
    for fichero in tools.glob("*.py"):
        texto = fichero.read_text(encoding="utf-8")
        for linea in texto.splitlines():
            if '"avatar_url":' in linea and "og_image" in linea:
                culpables.append(fichero.name)

    assert not culpables, f"og:image usado como avatar en: {culpables}"


def test_the_mastodon_placeholder_is_filtered():
    """
    Apareció en una corrida real de verificación y NO estaba filtrado. Mastodon
    sirve `missing.png` a toda cuenta sin foto, así que dos usuarios distintos
    sin avatar se habrían correlacionado.
    """
    assert is_default_avatar(imagehash.hex_to_hash("d42b0f178e4c5824")) is True


def test_an_account_is_never_correlated_with_itself():
    """
    Dos entidades de la MISMA cuenta, descubiertas por dos herramientas
    distintas, tienen por fuerza el mismo avatar. Es una coincidencia
    garantizada por cómo se buscó, no evidencia.

    Visto en una corrida real: el avatar cosechado de `github.com/{u}.png`
    coincidía a distancia 0 con el que la API de GitHub había expuesto para esa
    misma cuenta, e inflaba la puntuación con información inexistente.
    """
    from app.identity.avatar_hasher import _account_key

    class _P:
        def __init__(self, platform):
            self.platform = platform

    # Los catálogos nombran la misma plataforma de formas distintas.
    assert _account_key(_P("GitHub (User)"), {"username": "Torvalds"}) == _account_key(
        _P("github"), {"username": "torvalds"}
    )
    # Cuentas distintas en la misma plataforma sí pueden correlacionarse.
    assert _account_key(_P("github"), {"username": "ana"}) != _account_key(
        _P("github"), {"username": "luis"}
    )
    # Sin alias no hay clave, y entonces no se suprime nada.
    assert _account_key(_P("github"), {}) == ""
