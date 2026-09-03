import pytest
from app.tools.base import TargetContext
from app.tools.registry import tool_registry


def test_tool_registry_initialization():
    all_tools = tool_registry.get_all()
    assert len(all_tools) >= 5
    tool_names = [t.name for t in all_tools]
    assert "username_finder" in tool_names
    assert "email_checker" in tool_names
    assert "social_verifier" in tool_names
    assert "search_dorker" in tool_names
    assert "academic_finder" in tool_names
    assert "dni_lookup" in tool_names


def test_tool_runnable_filtering():
    # Context with only email
    ctx_email = TargetContext(email="test@example.com")
    runnable = tool_registry.get_runnable_tools(ctx_email)
    runnable_names = [t.name for t in runnable]
    assert "email_checker" in runnable_names
    assert "search_dorker" in runnable_names
    assert "username_finder" not in runnable_names

    # Context with username
    ctx_user = TargetContext(username="testuser")
    runnable_user = tool_registry.get_runnable_tools(ctx_user)
    runnable_user_names = [t.name for t in runnable_user]
    assert "username_finder" in runnable_user_names
    assert "github_deep_scanner" in runnable_user_names

    # Context with phone
    ctx_phone = TargetContext(phone="987654321")
    runnable_phone = tool_registry.get_runnable_tools(ctx_phone)
    assert "phone_lookup" in [t.name for t in runnable_phone]

    # Context with email has breach_checker
    assert "breach_checker" in runnable_names


@pytest.mark.asyncio
async def test_phone_lookup_peru_formatting():
    from app.tools.phone_lookup import PhoneLookupTool
    tool = PhoneLookupTool()
    ctx = TargetContext(phone="987654321")
    findings = await tool.execute(ctx)
    assert len(findings) == 1
    assert findings[0].value.startswith("+51")
    assert "whatsapp_link" in findings[0].metadata_info
