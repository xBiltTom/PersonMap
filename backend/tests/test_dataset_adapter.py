"""
Tests del adaptador de catálogos de username.

Lo que se protege aquí no es el parseo, es lo que costaría caro perder:

1. **Que ampliar no quite.** Ordenando solo por ranking, los sitios de Maigret
   que traen `alexaRank` desplazaban a los de WhatsMyName que no lo traen, y con
   un tope de 500 desaparecían Reddit e Instagram. Se habría "ampliado" el
   catálogo perdiendo cobertura donde más importa.
2. **Que la fusión siga siendo en memoria.** WhatsMyName es CC BY-SA 4.0 y el
   ShareAlike se contagia a cualquier derivado que se redistribuya.
3. **Que `regexCheck` filtre de verdad**, que es la mejora de precisión de la
   fase: descarta un sitio sin gastar la petición.
"""

import json

from app.tools.dataset_adapter import (
    MAIGRET_COMMIT,
    MAIGRET_FILE,
    NO_RANK,
    SiteCheck,
    WMN_FILE,
    build_catalog,
    catalog_stats,
    load_maigret,
    load_whatsmyname,
    _platform_key,
)


# --- No perder cobertura al ampliar ---------------------------------------


def test_the_curated_catalog_always_comes_first():
    """
    WhatsMyName es el catálogo curado que el proyecto ya tenía validado. Va
    delante para que subir el tope solo pueda añadir, nunca quitar.
    """
    catalog = build_catalog(limit=500)

    assert {site.source for site in catalog} == {"whatsmyname"}


def test_raising_the_cap_only_adds():
    pequeno = build_catalog(limit=300)
    grande = build_catalog(limit=2000)

    nombres_pequeno = [s.name for s in pequeno]
    assert nombres_pequeno == [s.name for s in grande[:300]]
    assert len(grande) > len(pequeno)


def test_the_major_platforms_survive_a_tight_cap():
    """
    La regresión concreta que esto evita: con el orden solo por ranking, Reddit
    e Instagram desaparecían del top 500.
    """
    nombres = " ".join(s.name.lower() for s in build_catalog(limit=500))

    for plataforma in ("reddit", "instagram", "github", "tiktok", "facebook"):
        assert plataforma in nombres, f"{plataforma} desapareció del catálogo recortado"


def test_ranking_orders_within_each_tier():
    """Dentro de un nivel sí manda el dato, no una lista escrita a mano."""
    catalog = [s for s in build_catalog() if s.source == "whatsmyname"]
    ranked = [s.rank for s in catalog if s.rank < NO_RANK]

    assert ranked == sorted(ranked)


# --- Licencias: la fusión no se redistribuye ------------------------------


def test_the_two_datasets_stay_in_separate_files():
    """
    El ShareAlike de WhatsMyName se contagia a cualquier dataset derivado que se
    redistribuya. Un fichero fusionado en el repositorio sería ese derivado.
    """
    assert WMN_FILE.exists()
    assert MAIGRET_FILE.exists()
    assert WMN_FILE != MAIGRET_FILE

    wmn = json.loads(WMN_FILE.read_text(encoding="utf-8"))
    maigret = json.loads(MAIGRET_FILE.read_text(encoding="utf-8"))
    # Formatos distintos: son los ficheros originales, no un derivado.
    assert isinstance(wmn.get("sites"), list)
    assert isinstance(maigret.get("sites"), dict)


def test_the_maigret_snapshot_is_pinned_to_a_commit():
    """
    Sin commit fijado, "N sitios" no significa nada en el artículo y el fichero
    remoto se convierte en un vector de cadena de suministro.
    """
    assert len(MAIGRET_COMMIT) == 40
    assert all(c in "0123456789abcdef" for c in MAIGRET_COMMIT)


# --- Precisión ------------------------------------------------------------


def test_regex_check_rejects_a_username_the_site_cannot_hold():
    """QQ solo admite identificadores numéricos: 'jperez' allí es ruido seguro."""
    site = SiteCheck(
        name="QQ",
        url="https://qq.com/{username}",
        regex_check=r"^[1-9][0-9]{4,8}$",
    )

    assert site.accepts_username("123456") is True
    assert site.accepts_username("jperez") is False


def test_a_site_without_regex_check_accepts_anything():
    site = SiteCheck(name="X", url="https://x.com/{username}")

    assert site.accepts_username("cualquier.cosa") is True


def test_a_broken_pattern_does_not_silence_the_site():
    """Un patrón que Python no compila no debe hacer desaparecer el sitio."""
    site = SiteCheck(name="X", url="https://x.com/{username}", regex_check="[sin cerrar")

    assert site.accepts_username("jperez") is True


def test_dotted_aliases_save_a_fifth_of_the_requests():
    """
    La cifra que justifica la fase: sobre un alias con punto —justo los que
    descubre el pivoteo— se descarta ~20% del catálogo sin gastar una petición.
    """
    catalog = build_catalog()
    descartados = sum(
        1 for s in catalog if not s.accepts_username("carloseduardo.mendozasilva")
    )

    assert descartados > len(catalog) * 0.10


# --- Identidad de plataforma ----------------------------------------------


def test_the_same_platform_is_recognised_across_datasets():
    """
    WhatsMyName apunta al endpoint de API y Maigret a la web. Son el mismo
    sitio, y tratarlos como distintos duplicaba petición y hallazgo.
    """
    assert _platform_key("https://api.mixcloud.com/{username}") == _platform_key(
        "https://www.mixcloud.com/{username}/"
    )


def test_multi_level_domains_are_not_truncated():
    """Truncar a dos etiquetas rompería `habbo.com.br` y los `.co.uk`."""
    assert _platform_key("https://habbo.com.br/api/x/{username}") == "habbo.com.br"


def test_no_platform_is_checked_twice():
    catalog = build_catalog()
    claves = [_platform_key(s.url) for s in catalog]

    # WhatsMyName tiene varias rutas legítimas por plataforma (YouTube canal vs
    # usuario), así que se permite repetición dentro del catálogo curado; lo que
    # no puede haber es un sitio de Maigret pisando a uno ya presente.
    de_maigret = [_platform_key(s.url) for s in catalog if s.source == "maigret"]
    de_wmn = {_platform_key(s.url) for s in catalog if s.source == "whatsmyname"}

    assert len(de_maigret) == len(set(de_maigret))
    assert not (set(de_maigret) & de_wmn)


# --- Enriquecimiento ------------------------------------------------------


def test_enrichment_applies_maigret_metadata_to_existing_sites():
    """
    La mejora de precisión que NO depende del volumen: los sitios que ya se
    escaneaban heredan `regexCheck`, ranking y cadenas de ausencia.
    """
    catalog = build_catalog()
    enriquecidos = [s for s in catalog if s.enriched_by == "maigret"]

    assert enriquecidos, "ningún sitio curado recibió metadatos de Maigret"
    assert all(s.source == "whatsmyname" for s in enriquecidos)
    assert any(s.rank < NO_RANK for s in enriquecidos)


def test_engine_inheritance_is_resolved():
    """
    1.693 sitios de Maigret no declaran su forma de comprobación: la heredan de
    uno de 17 motores. Sin resolverlo, se comprobarían con los valores por
    defecto y darían falsos positivos en masa.
    """
    maigret = load_maigret()
    con_cadenas = [s for s in maigret if s.presence or s.absence]

    assert len(con_cadenas) > 500


def test_unreachable_sites_are_skipped():
    """
    Los sitios tras Cloudflare o con huella TLS no se pueden alcanzar con un
    cliente HTTP normal: intentarlo solo quema reintentos.
    """
    raw = json.loads(MAIGRET_FILE.read_text(encoding="utf-8"))
    protegidos = {
        name
        for name, site in raw["sites"].items()
        if isinstance(site, dict) and site.get("protection")
    }
    cargados = {s.name for s in load_maigret()}

    assert protegidos, "el snapshot debería traer sitios con protección"
    assert not (protegidos & cargados)


def test_stats_describe_the_catalog():
    stats = catalog_stats(build_catalog())

    assert stats["total"] == stats["from_whatsmyname"] + stats["from_maigret"]
    assert stats["with_regex_check"] > 0
    assert stats["maigret_commit"] == MAIGRET_COMMIT


def test_whatsmyname_still_loads_on_its_own():
    sites = load_whatsmyname()

    assert len(sites) > 500
    assert all(s.source == "whatsmyname" for s in sites)
