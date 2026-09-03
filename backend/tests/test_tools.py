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
