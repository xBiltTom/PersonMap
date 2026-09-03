import pytest
from app.tools.base import TargetContext
from app.tools.email_enumerator import EmailEnumeratorTool
from app.tools.gravatar_deep import GravatarDeepTool
from app.tools.keybase_resolver import KeybaseResolverTool
from app.tools.social_url_extractor import SocialUrlExtractorTool
from app.tools.wikipedia_edits import WikipediaEditsTool
from app.engine.rule_engine import RuleEngine
from app.engine.pivot_rules import extract_and_apply_pivots, _clean_url


def test_social_url_extractor_regex():
    tool = SocialUrlExtractorTool()
    context = TargetContext(
        extra={
            "candidate_urls": [
                "https://www.linkedin.com/in/juan-perez-12345/",
                "https://github.com/juanperezdev/",
                "https://x.com/juanperez_pe",
                "https://t.me/juanperez_telegram",
                "https://www.instagram.com/juan.perez.foto/",
            ]
        }
    )
    assert tool.can_run(context) is True

    import asyncio
    findings = asyncio.run(tool.execute(context))
    assert len(findings) == 5

    platforms = {f.platform: f.metadata_info.get("username") for f in findings}
    assert platforms["linkedin"] == "juan-perez-12345"
    assert platforms["github"] == "juanperezdev"
    assert platforms["twitter"] == "juanperez_pe"
    assert platforms["telegram"] == "juanperez_telegram"
    assert platforms["instagram"] == "juan.perez.foto"


def test_url_cleaner_and_pivot_extraction():
    url_with_tracking = "https://github.com/targetuser?utm_source=twitter&ref=share"
    clean = _clean_url(url_with_tracking)
    assert "utm_source" not in clean
    assert "ref=" not in clean
    assert clean == "https://github.com/targetuser"


def test_rule_engine_fingerprinting():
    engine = RuleEngine()
    tool = EmailEnumeratorTool()

    ctx1 = TargetContext(email="user@test.com")
    key1 = engine._get_tool_run_key(tool, ctx1)

    # Discovered a second email via pivot
    ctx2 = TargetContext(email="user@test.com", discovered_emails=["new_user@gmail.com"])
    key2 = engine._get_tool_run_key(tool, ctx2)

    # The fingerprint MUST differ so the tool runs again on the expanded context
    assert key1 != key2
    assert "new_user@gmail.com" in key2
