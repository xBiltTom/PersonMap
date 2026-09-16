import asyncio
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple
import httpx
import imagehash
from PIL import Image

from app.tools import http_client


# Avatares por defecto conocidos, por su dHash de 8x8.
#
# Medidos contra los servicios reales el 2026-09-05, y **estables**: el mismo
# hash para tres semillas distintas y tres tamaños (80, 200, 400 px).
#
# Por qué una lista y no un umbral de entropía, que sería lo primero que uno
# intenta: no discrimina. La silueta genérica de Gravatar y un `identicon`
# tienen la MISMA entropía (1.49), y sin embargo son cosas opuestas — el
# identicon se deriva del hash del correo, así que dos iguales sí son evidencia
# de que hay un mismo correo detrás; la silueta es la misma imagen para todo el
# mundo y no dice nada. Eso no se puede deducir de la imagen: hay que saber
# cuáles son placeholders.
DEFAULT_AVATAR_HASHES = {
    "281432616933f0c0",  # Gravatar mystery-person (d=mp / d=mm)
    "3361c8e87169e8d4",  # Libravatar mystery-man
    # Mastodon sirve esta imagen a TODA cuenta sin foto. Apareció en una corrida
    # real de verificación y no estaba filtrada: sin ella, dos usuarios de
    # Mastodon sin avatar se habrían correlacionado.
    "d42b0f178e4c5824",  # mastodon.social/avatars/original/missing.png
}

# Un hash con todos los bits a cero es una imagen plana: un color, sin ningún
# detalle. Cubre `d=blank`, los recuadros monocromos y cualquier placeholder
# futuro que nadie haya catalogado.
FLAT_IMAGE_HASH = "0000000000000000"

# Margen para los placeholders: un mismo placeholder servido a otro tamaño puede
# variar en algún bit. Se mantiene muy por debajo del umbral de coincidencia
# para no descartar por error un avatar real.
DEFAULT_AVATAR_MAX_DISTANCE = 2


def _account_key(entity: Any, metadata: Dict[str, Any]) -> str:
    """
    Identidad de la CUENTA, para no correlacionar una cuenta consigo misma.

    Se normaliza la plataforma porque los catálogos la nombran de formas
    distintas ("github", "GitHub (User)") y son la misma.
    """
    platform = str(getattr(entity, "platform", "") or "").lower()
    platform = platform.split("(")[0].strip()
    username = str(metadata.get("username") or "").lower().strip()
    return f"{platform}|{username}" if platform and username else ""


def is_default_avatar(digest: "imagehash.ImageHash") -> bool:
    """
    ¿Es este el avatar por defecto del servicio, y por tanto evidencia nula?

    Dos personas distintas sin foto de perfil comparten exactamente la misma
    imagen. Correlacionarlas por eso las declararía la misma persona.
    """
    texto = str(digest)
    if texto == FLAT_IMAGE_HASH:
        return True

    for conocido in DEFAULT_AVATAR_HASHES:
        try:
            if int(digest - imagehash.hex_to_hash(conocido)) <= DEFAULT_AVATAR_MAX_DISTANCE:
                return True
        except Exception:
            continue
    return False


class AvatarHasher:
    """
    Perceptual Image Hashing Engine for Avatar Correlation.
    Uses Difference Hashing (dHash) and Hamming Distance to identify
    when observations reuse a profile photo across disparate platforms.
    """

    HAMMING_MATCH_THRESHOLD = 6  # <= 6 indicates near-identical or resized image
    HASH_SIZE = 8

    async def compute_dhash_from_url(self, client: httpx.AsyncClient, url: str) -> Optional[imagehash.ImageHash]:
        """
        Descarga una imagen y calcula su dHash, **descartando los placeholders**.

        Un avatar por defecto se devuelve como `None`, es decir, no participa en
        ninguna comparación. Es la salvaguarda más importante de la cosecha
        activa de avatares: medido el 2026-09-05, la silueta genérica de Gravatar
        da **distancia de Hamming 0 entre cuatro identidades distintas**, así que
        sin este filtro el sistema fusionaría a personas sin ninguna relación
        bajo una misma identidad. Es el error más grave que puede cometer esta
        herramienta, y con cosecha pasiva era raro; con cosecha activa sobre la
        cola larga sería la norma, porque la mayoría de esas cuentas no tienen
        foto propia.
        """
        if not url or not url.startswith("http"):
            return None
        try:
            resp = await client.get(url, timeout=6.0)
            if resp.status_code != 200:
                return None
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            digest = imagehash.dhash(img, hash_size=self.HASH_SIZE)
            return None if is_default_avatar(digest) else digest
        except Exception:
            return None

    def compare_hashes(self, hash_a: imagehash.ImageHash, hash_b: imagehash.ImageHash) -> Tuple[bool, int]:
        """Calculates Hamming distance between two perceptual hashes."""
        dist = int(hash_a - hash_b)
        is_match = bool(dist <= self.HAMMING_MATCH_THRESHOLD)
        return is_match, dist

    async def correlate_entity_avatars(
        self, entities: List[Any]
    ) -> List[Dict[str, Any]]:
        """
        Extracts avatar URLs from entities, calculates perceptual hashes,
        and performs all-pairs Hamming distance comparison.
        """
        targets_with_avatars: List[Dict[str, Any]] = []

        for ent in entities:
            metadata = getattr(ent, "metadata_info", {}) or {}
            avatar_url = metadata.get("avatar_url") or metadata.get("photo_url")
            if avatar_url and isinstance(avatar_url, str) and avatar_url.startswith("http"):
                targets_with_avatars.append({
                    "entity_id": str(getattr(ent, "id", "")),
                    "platform": getattr(ent, "platform", "unknown"),
                    "account_key": _account_key(ent, metadata),
                    "display_name": getattr(ent, "display_name", "") or getattr(ent, "value", ""),
                    "avatar_url": avatar_url,
                })

        if len(targets_with_avatars) < 2:
            return []

        # Descarga y hashing concurrentes a través de la capa HTTP compartida.
        # Antes este módulo construía su propio httpx.AsyncClient con verify=False,
        # quedando fuera del semáforo global, del backoff y de la rotación de
        # User-Agent — y desactivando la verificación TLS en un proyecto de
        # seguridad de la información.
        async with http_client.build_client(timeout=6.0) as client:
            tasks = [self.compute_dhash_from_url(client, item["avatar_url"]) for item in targets_with_avatars]
            hashes = await asyncio.gather(*tasks, return_exceptions=True)

        hashed_entries = []
        for item, h in zip(targets_with_avatars, hashes):
            if isinstance(h, imagehash.ImageHash):
                hashed_entries.append({**item, "hash": h})

        correlations: List[Dict[str, Any]] = []
        for i, a in enumerate(hashed_entries):
            for b in hashed_entries[i + 1 :]:
                if a["entity_id"] == b["entity_id"]:
                    continue

                # Dos entidades de la MISMA cuenta, descubiertas por dos
                # herramientas distintas, tienen por fuerza el mismo avatar. Es
                # una coincidencia garantizada por cómo se buscó, no evidencia:
                # correlacionarlas inflaría la puntuación con información que no
                # existe. Visto en una corrida real, donde el avatar cosechado
                # de `github.com/{u}.png` coincidía a distancia 0 con el que la
                # API de GitHub había expuesto para esa misma cuenta.
                if a["account_key"] and a["account_key"] == b["account_key"]:
                    continue

                is_match, dist = self.compare_hashes(a["hash"], b["hash"])
                if is_match:
                    correlations.append({
                        "entity_a_id": a["entity_id"],
                        "entity_b_id": b["entity_id"],
                        "platform_a": a["platform"],
                        "platform_b": b["platform"],
                        "hamming_distance": dist,
                        "match_type": "exact_avatar" if dist == 0 else "visually_similar_avatar",
                        "avatar_a": a["avatar_url"],
                        "avatar_b": b["avatar_url"],
                    })

        return correlations


avatar_hasher = AvatarHasher()
