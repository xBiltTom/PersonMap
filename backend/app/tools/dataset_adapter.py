"""
Normalización en memoria de los catálogos de sitios de username.

Dos fuentes con licencias distintas y formatos distintos:

| Fuente | Licencia | Aporta |
|---|---|---|
| WhatsMyName | CC BY-SA 4.0 | `uri_check`, `e_code`, `e_string`, `m_string`, `cat` |
| Maigret | MIT | `regexCheck`, `alexaRank`, `absenceStrs`, `protection`, `tags`, `engine` |

**Los dos ficheros se mantienen separados y la fusión ocurre solo en memoria.**
No es una decisión estética: WhatsMyName es CC BY-SA 4.0 y el ShareAlike se
contagia a cualquier dataset derivado **que se redistribuya**. Un fichero
fusionado en el repositorio sería ese derivado; un `dict` construido en tiempo
de ejecución, no.

**El objetivo no es el volumen, es la precisión.** Lo valioso de Maigret no son
los 3.000 sitios extra sino la calidad de la comprobación:

- `regexCheck` descarta un alias inválido **sin gastar una petición**. QQ solo
  admite identificadores numéricos: comprobar "jperez" allí es tráfico tirado y
  una fuente de falsos positivos.
- `absenceStrs` reduce los falsos positivos de las páginas que responden 200 a
  cualquier cosa.
- `alexaRank` da una priorización basada en datos, en lugar del conjunto escrito
  a mano que había antes.
- `protection` identifica los sitios inalcanzables sin `curl_cffi` (huella TLS,
  retos de Cloudflare, WAF) para saltarlos en vez de quemar reintentos en ellos.

Por eso el adaptador **primero enriquece** los sitios que ya se escaneaban y solo
después añade los nuevos: la mejora de precisión se aplica al catálogo conocido
aunque no se suba el volumen.

Snapshot fijado por commit, nunca sincronizado en caliente: un fichero remoto
sin firmar que define a qué miles de hosts se manda tráfico es un vector de
cadena de suministro, y una lista cambiante rompe la reproducibilidad que
necesitan las mediciones del artículo.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DATA_DIR = Path(__file__).parent / "data"
WMN_FILE = DATA_DIR / "wmn-data.json"
MAIGRET_FILE = DATA_DIR / "maigret-data.json"

# Snapshot vendorizado de Maigret. Se anota el commit para que una medición sea
# reproducible: "N sitios, snapshot Maigret @ <sha>".
MAIGRET_COMMIT = "8f42a42d0ebb117f265eeaf6c75ebda5249a79b4"
MAIGRET_LICENSE = "MIT"
WMN_LICENSE = "CC BY-SA 4.0"

# Categorías que no se escanean nunca.
EXCLUDED_CATEGORIES = {"xx NSFW xx", "archived"}

# Etiquetas equivalentes en Maigret. WhatsMyName marca lo adulto con la
# categoría "xx NSFW xx" y Maigret con estas etiquetas: sin traducirlas, 19
# sitios porno se colaban en el catálogo de una herramienta educativa que se
# usa con estudiantes y cuyo informe se le enseña a la persona investigada.
EXCLUDED_TAGS = {"adult", "porn", "nsfw", "xxx"}

# Protecciones que hacen inalcanzable un sitio con un cliente HTTP normal.
# Intentarlo solo gasta reintentos y aumenta el ruido: se saltan y se cuentan.
UNREACHABLE_PROTECTIONS = {
    "tls_fingerprint",
    "cf_js_challenge",
    "cf_firewall",
    "js_challenge",
    "aws_waf_js_challenge",
    "ddos_guard_challenge",
    "custom_bot_protection",
    "ip_reputation",
    "login",
}

# Categorías que se priorizan cuando un sitio no trae ranking.
PRIORITY_TAGS = {
    "social", "coding", "tech", "gaming", "music", "art", "blog", "video",
    "images", "business", "forum", "photo", "networking", "freelance",
}

# Los sitios sin ranking van después de los rankeados. Se usa un valor centinela
# muy alto en lugar de None para que el orden sea total y estable.
NO_RANK = 5_000_000
NO_RANK_UNPRIORITISED = 9_000_000


@dataclass(frozen=True)
class SiteCheck:
    """Un sitio comprobable, ya normalizado, venga de donde venga."""

    name: str
    url: str
    pretty_url: Optional[str] = None
    check_type: str = "status_code"
    expected_code: int = 200
    presence: Tuple[str, ...] = field(default_factory=tuple)
    absence: Tuple[str, ...] = field(default_factory=tuple)
    regex_check: Optional[str] = None
    rank: int = NO_RANK
    category: Optional[str] = None
    tags: Tuple[str, ...] = field(default_factory=tuple)
    source: str = "whatsmyname"
    enriched_by: Optional[str] = None

    def accepts_username(self, username: str) -> bool:
        """
        ¿Merece la pena gastar una petición con este alias?

        Es la comprobación que ahorra tráfico y evita falsos positivos: un sitio
        que solo admite identificadores numéricos nunca va a tener a "jperez", y
        preguntárselo solo puede devolver ruido.
        """
        if not self.regex_check:
            return True
        try:
            return re.search(self.regex_check, username) is not None
        except re.error:
            # Un patrón que Python no compila no debe silenciar el sitio entero.
            return True

    def build_url(self, username: str) -> str:
        return self.url.replace("{username}", username).replace("{account}", username)

    def build_pretty_url(self, username: str) -> str:
        template = self.pretty_url or self.url
        return template.replace("{username}", username).replace("{account}", username)


# Subdominios de servicio que no distinguen plataforma. Sin quitarlos, el mismo
# sitio en los dos catálogos parece dos sitios distintos.
SERVICE_SUBDOMAINS = {"www", "api", "m", "mobile", "beta", "community", "web", "en"}


def _platform_key(url_template: str) -> str:
    """
    Clave de identidad de una PLATAFORMA, no de una URL.

    Comparar plantillas completas no sirve: WhatsMyName suele apuntar al
    endpoint de API (`api.mixcloud.com/{username}`) y Maigret a la página web
    (`mixcloud.com/{username}`). Son el mismo sitio, y tratarlos como distintos
    duplicaba la petición y el hallazgo.

    Se compara el dominio con los subdominios de servicio recortados. No se usa
    una lista de sufijos públicos a propósito: truncar a dos etiquetas rompería
    los dominios de varios niveles (`habbo.com.br`, `.co.uk`), que aquí abundan.
    """
    host = url_template.lower()
    host = re.sub(r"^https?://", "", host)
    host = host.split("/", 1)[0].split("?", 1)[0]

    labels = host.split(".")
    while len(labels) > 2 and labels[0] in SERVICE_SUBDOMAINS:
        labels.pop(0)
    return ".".join(labels)


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(str(v) for v in value if v)
    return ()


def load_whatsmyname() -> List[SiteCheck]:
    """Catálogo de WhatsMyName, el que ya se venía usando."""
    if not WMN_FILE.exists():
        return []
    try:
        data = json.loads(WMN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    sites: List[SiteCheck] = []
    for raw in data.get("sites", []):
        if raw.get("valid", True) is False:
            continue
        if raw.get("cat") in EXCLUDED_CATEGORIES:
            continue
        uri_check = raw.get("uri_check")
        if not uri_check:
            continue

        sites.append(
            SiteCheck(
                name=raw.get("name", "Unknown"),
                url=uri_check,
                pretty_url=raw.get("uri_pretty"),
                # WhatsMyName siempre valida por código y, si los trae, por
                # cadenas. Se modela como "message" cuando hay cadenas para que
                # el verificador aplique ambas comprobaciones.
                check_type="message" if raw.get("e_string") else "status_code",
                expected_code=int(raw.get("e_code", 200) or 200),
                presence=_as_tuple(raw.get("e_string")),
                absence=_as_tuple(raw.get("m_string")),
                category=raw.get("cat"),
                source="whatsmyname",
            )
        )
    return sites


def load_maigret() -> List[SiteCheck]:
    """
    Catálogo de Maigret, resolviendo la herencia de `engine`.

    1.693 de sus sitios no declaran su propia forma de comprobación: la heredan
    de uno de 17 motores compartidos (`engine404`, `MediaWiki`, `Wordpress/Author`…).
    Sin resolver esa herencia, esos sitios se comprobarían con los valores por
    defecto y darían falsos positivos en masa.
    """
    if not MAIGRET_FILE.exists():
        return []
    try:
        data = json.loads(MAIGRET_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []

    engines: Dict[str, Dict[str, Any]] = {
        name: (body or {}).get("site", {}) or {}
        for name, body in (data.get("engines") or {}).items()
    }

    sites: List[SiteCheck] = []
    for name, raw in (data.get("sites") or {}).items():
        if not isinstance(raw, dict) or raw.get("disabled"):
            continue
        if raw.get("type", "username") != "username":
            continue

        protections = {str(p) for p in _as_tuple(raw.get("protection"))}
        if protections & UNREACHABLE_PROTECTIONS:
            continue

        raw_tags = {t.lower() for t in _as_tuple(raw.get("tags"))}
        if raw_tags & EXCLUDED_TAGS:
            continue

        # El engine aporta los valores base; lo que el sitio declare manda.
        merged: Dict[str, Any] = {}
        engine_name = raw.get("engine")
        if engine_name and engine_name in engines:
            merged.update(engines[engine_name])
        merged.update(raw)

        url = merged.get("url")
        if not url:
            continue
        # Las plantillas de los motores traen huecos propios del motor.
        url = url.replace("{urlMain}", str(merged.get("urlMain", "")).rstrip("/"))
        url = url.replace("{urlSubpath}", str(merged.get("urlSubpath", "")))
        if "{username}" not in url:
            continue

        rank = merged.get("alexaRank")
        tags = _as_tuple(merged.get("tags"))

        sites.append(
            SiteCheck(
                name=name,
                url=url,
                pretty_url=merged.get("urlPretty"),
                check_type=str(merged.get("checkType") or "status_code"),
                expected_code=200,
                presence=_as_tuple(merged.get("presenseStrs")),
                absence=_as_tuple(merged.get("absenceStrs")),
                regex_check=merged.get("regexCheck"),
                rank=int(rank) if isinstance(rank, int) and rank > 0 else NO_RANK,
                category=tags[0] if tags else None,
                tags=tags,
                source="maigret",
            )
        )
    return sites


def _is_trustworthy(site: SiteCheck) -> bool:
    """
    ¿Puede este sitio afirmar algo, o solo devolver 200 a cualquier cosa?

    1.098 de los 3.077 sitios de Maigret (36 %) no traen NINGUNA cadena de
    validación: su única comprobación es el código de estado. Muchos responden
    200 a cualquier URL de perfil, así que "encuentran" una cuenta para
    cualquier alias. Medido sobre un alias sintético que no existe en ningún
    sitio: 255 hallazgos, todos falsos.

    Se admiten solo si traen alguna forma de comprobar el CONTENIDO. Una
    versión anterior de esta regla hacía además una excepción con los sitios de
    ranking alto, suponiendo que una plataforma popular devuelve un 404 de
    verdad. Medido, es falso: seis de los doce falsos positivos restantes eran
    justo eso — WordPressOrg (ranking 12), AllKPop, Datpiff, Studfile, Avizo y
    Runitonce, todos rankeados, todos sin una sola cadena, todos respondiendo
    200 a un alias inexistente. La excepción se retiró.

    Es la regla que convierte "4x cobertura" en precisión, que es lo que este
    apartado del plan pedía vender.
    """
    return bool(site.presence or site.absence)


def _sort_key(site: SiteCheck) -> Tuple[int, int, str]:
    """
    Prioridad en dos niveles: primero el catálogo curado, luego el volumen.

    El nivel es lo que impide una regresión. Ordenando solo por ranking, los 681
    sitios de Maigret que traen `alexaRank` desplazaban a los de WhatsMyName que
    no lo traen, y con un tope de 500 desaparecían plataformas centrales como
    Reddit o Instagram: se habría "ampliado" el catálogo perdiendo cobertura
    donde más importa.

    WhatsMyName va siempre delante porque es el catálogo curado que este
    proyecto ya tenía validado; Maigret aporta la cola larga **detrás**, de modo
    que subir el tope solo puede añadir, nunca quitar. Dentro de cada nivel sí
    manda el ranking real, que es la priorización basada en datos que sustituye
    a la lista escrita a mano.
    """
    tier = 0 if site.source == "whatsmyname" else 1

    if site.rank < NO_RANK:
        return (tier, site.rank, site.name.lower())

    prioritised = bool(set(site.tags) & PRIORITY_TAGS) or site.category in PRIORITY_TAGS
    base = NO_RANK if prioritised else NO_RANK_UNPRIORITISED
    return (tier, base, site.name.lower())


def build_catalog(limit: Optional[int] = None) -> List[SiteCheck]:
    """
    Catálogo unificado y ordenado por prioridad.

    El orden importa: `limit` recorta por la cola, así que lo que sobrevive a un
    tope bajo son los sitios donde una persona real tiene presencia.
    """
    wmn = load_whatsmyname()
    maigret = load_maigret()
    # Índice por plataforma. Si dos entradas de Maigret comparten dominio, se
    # queda la mejor rankeada: es la que representa la plataforma principal.
    maigret_index: Dict[str, SiteCheck] = {}
    for site in maigret:
        key = _platform_key(site.url)
        current = maigret_index.get(key)
        if current is None or site.rank < current.rank:
            maigret_index[key] = site

    catalog: List[SiteCheck] = []
    used_maigret: set = set()

    # 1. Los sitios que ya se escaneaban, ENRIQUECIDOS con lo que Maigret sepa
    #    de ellos. Aquí está la mejora de precisión que no depende del volumen.
    for site in wmn:
        key = _platform_key(site.url)
        twin = maigret_index.get(key)
        if twin is None:
            catalog.append(site)
            continue

        used_maigret.add(key)
        catalog.append(
            SiteCheck(
                name=site.name,
                url=site.url,
                pretty_url=site.pretty_url or twin.pretty_url,
                check_type=site.check_type,
                expected_code=site.expected_code,
                presence=site.presence,
                # La ausencia se suma: son cadenas que delatan una página de
                # "no existe", y cuantas más se conozcan, menos falsos positivos.
                absence=tuple(dict.fromkeys(site.absence + twin.absence)),
                regex_check=site.regex_check or twin.regex_check,
                rank=min(site.rank, twin.rank),
                category=site.category or twin.category,
                tags=twin.tags,
                source=site.source,
                enriched_by="maigret",
            )
        )

    # 2. Los sitios que solo tiene Maigret: el volumen. Se descartan los que
    #    comparten plataforma con uno ya presente, para no consultar dos veces
    #    el mismo sitio por dos rutas distintas.
    for site in maigret:
        if _platform_key(site.url) in used_maigret:
            continue
        if not _is_trustworthy(site):
            continue
        catalog.append(site)
        used_maigret.add(_platform_key(site.url))

    catalog.sort(key=_sort_key)
    return catalog[:limit] if limit else catalog


_platform_hosts_cache: Optional[set] = None


def platform_hosts() -> set:
    """
    Todos los dominios que el catálogo conoce como plataformas.

    Es la lista más completa que este proyecto tiene de "esto es un servicio, no
    la web personal de alguien", y la usa `domain_finder` para no confundir
    `github.com` con `juan.dev`. Reutilizar el catálogo evita mantener a mano una
    segunda lista que se desincronizaría.
    """
    global _platform_hosts_cache
    if _platform_hosts_cache is None:
        _platform_hosts_cache = {_platform_key(s.url) for s in build_catalog()}
    return _platform_hosts_cache


def catalog_stats(catalog: List[SiteCheck]) -> Dict[str, Any]:
    """Cifras del catálogo, para la huella de configuración y la interfaz."""
    return {
        "total": len(catalog),
        "from_whatsmyname": sum(1 for s in catalog if s.source == "whatsmyname"),
        "from_maigret": sum(1 for s in catalog if s.source == "maigret"),
        "enriched": sum(1 for s in catalog if s.enriched_by),
        "with_regex_check": sum(1 for s in catalog if s.regex_check),
        "with_absence_strings": sum(1 for s in catalog if s.absence),
        "ranked": sum(1 for s in catalog if s.rank < NO_RANK),
        "maigret_commit": MAIGRET_COMMIT,
    }
