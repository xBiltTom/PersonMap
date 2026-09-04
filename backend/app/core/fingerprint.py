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

    return {
        "tools_registered": len(tool_registry.get_all()),
        "username_catalog_available": catalog.get("available", 0),
        "username_catalog_scanned": catalog.get("scanned", 0),
        "http_max_concurrency": settings.http_max_concurrency,
        "http_max_per_host": settings.http_max_per_host,
        "username_scan_concurrency": settings.tool_concurrency_budget(
            settings.username_scan_concurrency
        ),
        "search_engine": "tavily" if settings.tavily_enabled else "duckduckgo",
    }
