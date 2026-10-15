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
from app.tools.maigret_catalog import execution_config
from app.tools.ghunt_runtime import capabilities as ghunt_capabilities
from app.tools.email_catalog import capabilities as email_capabilities


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
        "email_enumerator": email_capabilities(),
        "ghunt": ghunt_capabilities(),
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
        "username_scan_engine_version": 4,
        "maigret_version": breakdown.get("maigret_version"),
        "maigret_catalog_sha256": breakdown.get("maigret_catalog_sha256"),
        "maigret_enrich": settings.maigret_enrich,
        "maigret_tags": settings.maigret_tags,
        "maigret_site_names": settings.maigret_site_names,
        "maigret_excluded_tags": settings.maigret_excluded_tags,
        "maigret_keywords": settings.maigret_keywords,
        **execution_config(),
        "maigret_enricher_version": 1,
        "mcp_max_parallel_tools": max(1, min(6, settings.mcp_max_parallel_tools)),
        "mcp_username_fast_sites": max(1, settings.mcp_username_fast_sites),
        "mcp_review_max_queries": max(0, settings.mcp_review_max_queries),
        "mcp_updates_version": 1,
        "mcp_pivot_contract_version": 1,
        "mcp_external_evidence_version": 1,
        "http_max_concurrency": settings.http_max_concurrency,
        "http_max_per_host": settings.http_max_per_host,
        "username_scan_concurrency": settings.tool_concurrency_budget(
            settings.username_scan_concurrency
        ),
        "social_engine_version": 4,
        "dni_engine_version": 4,
        "domain_engine_version": 2,
        "academic_engine_version": 2,
        "github_engine_version": 2,
        "github_token_configured": bool(settings.github_api_token),
        "openalex_key_configured": bool(settings.openalex_api_key),
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
        "search_engine_version": 6,
        "public_page_reader_version": 3,
        "search_engine": "tavily" if settings.tavily_enabled else ("tinyfish" if settings.tinyfish_enabled else ("brave" if settings.brave_enabled else "duckduckgo")),
        "search_backends": [name for name, enabled in [("tavily", settings.tavily_enabled), ("tinyfish", settings.tinyfish_enabled), ("brave", settings.brave_enabled), ("duckduckgo", True)] if enabled],
        "brave_country": settings.brave_country,
        "brave_search_language": settings.brave_search_language,
        "search_max_queries": settings.search_query_budget,
        "search_max_queries_per_round": settings.search_max_queries_per_round,
        "search_query_concurrency": max(1, min(5, settings.search_query_concurrency)),
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
