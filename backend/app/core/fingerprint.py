"""
Huella de la configuración con la que se ejecutó una investigación.

`scorer_version` protege el modelo de identidad: dos puntuaciones solo son
comparables si salieron de la misma calibración. Pero el resto de la
configuración no lo protegía nadie, y afecta igual o más a los resultados.

El caso concreto que motiva este módulo: la Fase 4 amplía el catálogo de
`username_finder` de ~716 sitios a ~2960. A partir de ese momento, "entidades
descubiertas" y "latencia media" significan otra cosa, y las filas medidas
antes y después quedan mezcladas en la misma tabla **sin que nada permita
distinguirlas**. Un revisor que pregunte "¿estas mediciones se tomaron igual?"
tendría razón, y sin esta huella no habría respuesta.

Se persiste dentro de `investigation.metrics`, junto al resto, de modo que
cualquier análisis agregado pueda agrupar o descartar por configuración.
"""

import hashlib
import json
from typing import Any, Dict

from app.core.config import settings
from app.tools.registry import tool_registry


def run_fingerprint() -> Dict[str, Any]:
    """Parámetros que cambian el resultado de una investigación."""
    catalog: Dict[str, int] = {"available": 0, "scanned": 0}

    finder = tool_registry.get_tool("username_finder")
    if finder is not None and hasattr(finder, "catalog_size"):
        try:
            catalog = finder.catalog_size()
        except Exception:
            # La huella nunca debe tumbar una investigación: si el catálogo no
            # se puede leer, se registra en cero y se ve en el análisis.
            catalog = {"available": 0, "scanned": 0}

    breakdown: Dict[str, Any] = {}
    if finder is not None and hasattr(finder, "catalog_breakdown"):
        try:
            breakdown = finder.catalog_breakdown()
        except Exception:
            breakdown = {}

    return {
        "tools_registered": len(tool_registry.get_all()),
        # Composición del catálogo unificado. `maigret_commit` es lo que hace
        # reproducible una medición: "N sitios, snapshot Maigret @ <sha>".
        "catalog_from_whatsmyname": breakdown.get("from_whatsmyname", 0),
        "catalog_from_maigret": breakdown.get("from_maigret", 0),
        "catalog_enriched": breakdown.get("enriched", 0),
        "catalog_with_regex_check": breakdown.get("with_regex_check", 0),
        "maigret_commit": breakdown.get("maigret_commit"),
        "username_catalog_available": catalog.get("available", 0),
        "username_catalog_scanned": catalog.get("scanned", 0),
        "http_max_concurrency": settings.http_max_concurrency,
        "http_max_per_host": settings.http_max_per_host,
        "username_scan_concurrency": settings.tool_concurrency_budget(
            settings.username_scan_concurrency
        ),
        "social_engine_version": 4,
        "dni_engine_version": 3,
        "pdf_ocr_enabled": settings.pdf_ocr_enabled,
        "pdf_ocr_max_pages": settings.pdf_ocr_max_pages,
        "pdf_ocr_timeout_seconds": settings.pdf_ocr_timeout_seconds,
        "pdf_ocr_languages": settings.pdf_ocr_languages,
        "dni_max_public_sources": settings.dni_max_public_sources,
        "dni_public_sources_fingerprint": hashlib.sha256(json.dumps(settings.dni_public_source_urls, sort_keys=True).encode()).hexdigest(),
        "phone_engine_version": 2,
        "phone_max_numbers": settings.phone_max_numbers,
        "phone_network_fields": settings.phone_twilio_fields,
        "social_verify_concurrency": settings.tool_concurrency_budget(settings.social_verify_concurrency),
        "social_verify_max_urls": settings.social_verify_max_urls,
        "social_verify_url_timeout": settings.social_verify_url_timeout,
        "search_engine_version": 2,
        "search_engine": "tavily" if settings.tavily_enabled else ("tinyfish" if settings.tinyfish_enabled else "duckduckgo"),
        "search_max_queries": settings.tavily_max_queries,
        "search_max_queries_per_round": settings.search_max_queries_per_round,
        "search_max_results": settings.tavily_max_results,
        "search_depth": settings.tavily_search_depth,
        "search_country": settings.tavily_country,
        "search_literal_match": settings.tavily_require_literal_match,
        "search_exact_match": settings.tavily_exact_match,
        "search_timeout_seconds": settings.search_timeout_seconds,
        "search_read_pages": settings.search_read_pages,
        "search_max_pages": settings.search_max_pages,
        "tinyfish_enabled": settings.tinyfish_enabled,
        "tinyfish_fetch_enabled": settings.tinyfish_fetch_enabled,
        "tinyfish_location": settings.tinyfish_location,
        "tinyfish_language": settings.tinyfish_language,
    }
