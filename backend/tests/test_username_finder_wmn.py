import pytest
from app.tools.username_finder import UsernameFinderTool
from app.tools.base import TargetContext


def test_username_finder_loads_wmn_sites():
    tool = UsernameFinderTool()
    sites = tool._load_sites()
    assert len(sites) >= 50
    assert len(sites) <= tool.MAX_SITES

    # Verify priority platforms are prioritized in the top list
    site_names = [s["name"].lower() for s in sites]
    assert any("github" in name for name in site_names)
    assert any("gitlab" in name for name in site_names)
    assert any("reddit" in name for name in site_names)


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
