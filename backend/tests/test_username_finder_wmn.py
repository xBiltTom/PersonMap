import pytest
from app.core.config import settings
from app.tools.username_finder import UsernameFinderTool
from app.tools.base import TargetContext


def test_username_finder_loads_the_unified_catalog():
    """
    Desde la Fase 4.1 el catálogo lo construye `dataset_adapter` normalizando
    WhatsMyName y Maigret en memoria, y devuelve objetos `SiteCheck` en lugar de
    los diccionarios crudos del fichero.
    """
    tool = UsernameFinderTool()
    sites = tool._load_sites()

    assert len(sites) >= 50
    assert len(sites) <= settings.username_scan_max_sites

    site_names = [s.name.lower() for s in sites]
    assert any("github" in name for name in site_names)
    assert any("reddit" in name for name in site_names)

    # La priorización es por ranking real, no por una lista escrita a mano: los
    # primeros del catálogo tienen que ser plataformas masivas.
    primeros = " ".join(site_names[:25])
    assert any(p in primeros for p in ("facebook", "youtube", "twitter", "linkedin"))


def test_username_finder_filters_generic_roles():
    tool = UsernameFinderTool()
    assert "admin" in tool._generic_users
    assert "root" in tool._generic_users
    assert "support" in tool._generic_users


@pytest.mark.asyncio
async def test_username_finder_empty_context():
    tool = UsernameFinderTool()
    context = TargetContext()
    findings = await tool.execute(context)
    assert findings == []
