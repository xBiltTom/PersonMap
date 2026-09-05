"""
Cosecha activa de avatares.

`reverse_image_search.py` existe pero está apagado: exige una clave de SerpApi o
de Bing Visual Search, y el proyecto se restringe a fuentes gratuitas sin clave.
Aquí se invierte el planteamiento. En lugar de *"busca esta imagen en la web"*,
que necesita una API de pago, se hace *"descarga el avatar de esta cuenta en las
plataformas donde ya la confirmamos y compara los hashes"*.

**Solo sobre cuentas ya confirmadas.** Es la salvaguarda que define el módulo:
se construyen URLs de avatar únicamente para entidades que el barrido ya
verificó que existen. Construirlas para alias *no confirmados* significaría
descargar y fingerprintear fotos de terceros que no son el objetivo —
exactamente lo que una herramienta de concientización enseña a no hacer.

La otra salvaguarda vive en `avatar_hasher.is_default_avatar`: los avatares por
defecto se descartan antes de comparar. Medido el 2026-09-05, la silueta
genérica de Gravatar da distancia de Hamming **0 entre cuatro identidades
distintas**; sin ese filtro, la cosecha activa fusionaría a personas sin
relación bajo una misma identidad, y con cosecha activa sobre la cola larga eso
sería la norma, no la excepción, porque la mayoría de esas cuentas no tienen
foto propia.

Los patrones son directos y están verificados en vivo (2026-09-05). Se toma como
referencia la lista de proveedores de `microlinkhq/unavatar` (MIT) **sin
consumir su API**, que limita a 25 peticiones al día por IP en anónimo.
"""

import asyncio
import hashlib
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.tools import http_client

# Proveedores con patrón de URL directo. La clave es el fragmento que debe
# aparecer en el nombre de la plataforma del hallazgo, en minúsculas.
#
# Verificados el 2026-09-05: cada uno devuelve 200 con una imagen para una
# cuenta que existe y 404 para una que no, que es la señal que hace falta.
DIRECT_PROVIDERS: Dict[str, Callable[[str], str]] = {
    "github": lambda u: f"https://github.com/{u}.png?size=200",
    "telegram": lambda u: f"https://t.me/i/userpic/320/{u}.jpg",
    "keybase": lambda u: f"https://keybase.io/{u}/picture",
}

# Proveedores que exigen una consulta a su API para obtener la URL del avatar.
# `field` es la clave del JSON que la contiene.
JSON_PROVIDERS: Dict[str, Dict[str, str]] = {
    "dev.to": {
        "url": "https://dev.to/api/users/by_username?url={u}",
        "field": "profile_image",
    },
    "mastodon": {
        "url": "https://mastodon.social/api/v1/accounts/lookup?acct={u}",
        "field": "avatar",
    },
}

# Descartados tras comprobarlos en vivo el 2026-09-05, para que nadie los
# vuelva a intentar sin motivo: GitLab y Codeberg responden 403 al patrón
# directo, Bitbucket 404 siempre, Reddit devuelve HTML en lugar de JSON y el
# registro de NPM exige autenticación.

# Tope de avatares que se cosechan por investigación. Cada uno es una descarga
# de imagen, y el valor de la señal está en las primeras cuentas confirmadas,
# no en la cola.
MAX_HARVESTED = 25


def gravatar_url(email: str) -> str:
    """
    Avatar de Gravatar asociado a un correo.

    `d=404` es lo que lo convierte en una señal binaria limpia: si la persona no
    tiene avatar propio, Gravatar devuelve 404 en lugar de servir un placeholder
    genérico que luego habría que filtrar.
    """
    digest = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
    return f"https://gravatar.com/avatar/{digest}?d=404&s=200"


def _provider_for(platform: Optional[str]) -> Optional[str]:
    """Fragmento de proveedor que casa con el nombre de la plataforma."""
    if not platform:
        return None
    name = platform.lower()
    for key in DIRECT_PROVIDERS:
        if key in name:
            return key
    for key in JSON_PROVIDERS:
        if key in name:
            return key
    return None


async def _resolve_json_provider(
    client: httpx.AsyncClient, key: str, username: str
) -> Optional[str]:
    spec = JSON_PROVIDERS[key]
    resp = await http_client.get(client, spec["url"].format(u=username))
    if resp is None or resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if isinstance(data, list):
        data = data[0] if data else {}
    value = data.get(spec["field"]) if isinstance(data, dict) else None
    return value if isinstance(value, str) and value.startswith("http") else None


async def harvest_avatar_urls(entities: List[Any]) -> int:
    """
    Añade `avatar_url` a las entidades cuya plataforma tiene patrón conocido.

    Devuelve cuántas se enriquecieron. No descarga ni compara imágenes: eso lo
    hace después `avatar_hasher`, que además descarta los avatares por defecto.

    Solo toca entidades que **ya existen**, es decir, cuentas que el barrido
    confirmó. Las que ya traían `avatar_url` del pivoteo pasivo se respetan.
    """
    pendientes: List[Any] = []
    json_pendientes: List[tuple] = []
    enriquecidas = 0

    for entity in entities:
        if len(pendientes) + len(json_pendientes) >= MAX_HARVESTED:
            break

        metadata = getattr(entity, "metadata_info", None) or {}
        if metadata.get("avatar_url"):
            continue

        # Gravatar se deriva del correo, no de la plataforma.
        if getattr(entity, "entity_type", "") == "email":
            entity.metadata_info = {
                **metadata,
                "avatar_url": gravatar_url(str(entity.value)),
                "avatar_source": "gravatar",
                "avatar_harvested": True,
            }
            enriquecidas += 1
            continue

        username = metadata.get("username")
        if not username:
            continue

        key = _provider_for(getattr(entity, "platform", None))
        if key is None:
            continue

        if key in DIRECT_PROVIDERS:
            entity.metadata_info = {
                **metadata,
                "avatar_url": DIRECT_PROVIDERS[key](str(username)),
                "avatar_source": key,
                "avatar_harvested": True,
            }
            enriquecidas += 1
            pendientes.append(entity)
        else:
            json_pendientes.append((entity, key, str(username), metadata))

    if json_pendientes:
        async with http_client.build_client(timeout=10.0, rotate_ua=False) as client:
            resueltas = await asyncio.gather(
                *(
                    _resolve_json_provider(client, key, username)
                    for _, key, username, _ in json_pendientes
                ),
                return_exceptions=True,
            )
        for (entity, key, _, metadata), url in zip(json_pendientes, resueltas):
            if isinstance(url, str):
                entity.metadata_info = {
                    **metadata,
                    "avatar_url": url,
                    "avatar_source": key,
                    "avatar_harvested": True,
                }
                enriquecidas += 1

    return enriquecidas
