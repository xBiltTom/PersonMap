"""Email query contracts: explicit schemas, bounded coverage and no side effects."""
import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.config import settings
from app.core.runtime import durable_runtime
from app.engine.pivot_rules import extract_and_apply_pivots
from app.engine.rule_engine import RuleEngine
from app.models.target import Target
from app.services.workspace import call_fingerprint, merge_runtime
from app.tools import http_client
from app.tools.base import TargetContext
from app.tools.email_catalog import PROBES, capabilities, config_id, parse_registration
from app.tools.email_enumerator import EmailEnumeratorTool, execution_summary

EMAIL = "audit+tag@example.org"
CASES = {
    "spotify": ({"status": 20}, {"status": 1}),
    "taken": ({"taken": True}, {"taken": False}),
    "exists": ({"exists": True}, {"exists": False}),
    "available": ({"available": False}, {"available": True}),
    "registered": ({"registered": True}, {"registered": False}),
    "user_exists": ({"user_exists": True}, {"user_exists": False}),
    "duolingo": ({"users": [{"username": "observed"}]}, {"users": []}),
    "accounts": ({"accounts": [{"id": "observed"}]}, {"accounts": []}),
    "steam": ({"bEmailAlreadyTaken": True}, {"bEmailAlreadyTaken": False}),
    "pinterest": ({"resource_response": {"data": True}}, {"resource_response": {"data": False}}),
    "patreon": ({"data": {"is_available": False}}, {"data": {"is_available": True}}),
    "issuu": ({"status": "unavailable"}, {"status": "available"}),
    "amocrm": ({"status": "used"}, {"status": "free"}),
    "wordpress": ({"body": {"email_verified": False}}, {"body": {"error": "unknown_user"}}),
    "lastfm": ({"email": {"error_messages": ["Sorry, that email address is already registered to another account."]}}, {"email": {"valid": True}}),
    "codecademy": ({"errors": {"email": ["is already taken"]}}, None),
    "github": ("Email is already taken", "Email is available"),
    "atlassian": ({"action": "social_login", "identities": {"google": True}}, {"action": "signup"}),
    "orcid": ({"email": {"errors": ["orcid.frontend.verify.duplicate_email"]}}, {"email": {"errors": []}}),
    "miro": ({"recommendedAuthenticationType": "CREDENTIALS"}, {"recommendedAuthenticationType": "CREDENTIALS"}),
    "lastpass": ("no", "ok"),
    "text_exists": ("True", "False"),
    "text_available": ("false", "true"),
    "diigo": ("0", "1"),
    "codepen": ("That Email is already taken.", None),
    "envato": ("Email is already in use", None),
}


def response_for(spec, positive):
    payload = CASES[spec.parser][0 if positive else 1]
    if payload is None:
        return httpx.Response(200, json={"unrecognized": True})
    if isinstance(payload, str):
        return httpx.Response(422 if spec.parser == "github" and positive else 200, text=payload)
    return httpx.Response(200, json=payload)


def warmup_response():
    return httpx.Response(200, text='<meta name="csrf-token" content="synthetic-csrf-secret">'
        '<auto-check src="/email_validity_checks"><input data-csrf="true" value="synthetic-csrf-secret"></auto-check>',
        headers={"set-cookie": "csrftoken=synthetic-csrf-secret; Path=/; Secure"})


@pytest.fixture(autouse=True)
def default_config(monkeypatch):
    monkeypatch.setattr(settings, "email_enum_sites", [])
    monkeypatch.setattr(settings, "email_enum_max_emails", 3)


def bridge(monkeypatch, responder):
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(responder), follow_redirects=False))


def for_spec(spec, *, any_email=False):
    def responder(request):
        if spec.warmup and str(request.url) == spec.warmup:
            return warmup_response()
        serialized = str(request.url) + request.content.decode()
        # Decode transport encoding, including + tags, before identifying input.
        from urllib.parse import unquote_plus
        positive = any_email or EMAIL in unquote_plus(serialized.replace("+", "%2B"))
        return response_for(spec, positive)
    return responder


@pytest.mark.parametrize("spec", [spec for spec in PROBES if spec.parser != "miro"], ids=lambda spec: spec.key)
@pytest.mark.asyncio
async def test_each_adapted_probe_preserves_registration_scope_and_provenance(monkeypatch, spec):
    bridge(monkeypatch, for_spec(spec))
    monkeypatch.setattr(settings, "email_enum_sites", [spec.key])
    context = TargetContext(email=EMAIL)
    findings = await EmailEnumeratorTool().execute(context)
    assert len(findings) == 1, context.extra
    finding = findings[0]
    assert finding.entity_type == "email_registration"
    assert finding.metadata_info["service_url"] == spec.home
    assert "url" not in finding.metadata_info
    expected_control = "passed" if CASES[spec.parser][1] is not None else "untested"
    assert finding.metadata_info["negative_control"] == expected_control
    assert bool(finding.metadata_info.get("holehe_commit")) == bool(spec.upstream)
    pivots = TargetContext()
    extract_and_apply_pivots(findings, pivots)
    assert pivots.extra.get("candidate_urls", []) == []
    assert pivots.all_usernames() == []
    exported = json.dumps(durable_runtime(context.extra))
    assert "synthetic-csrf-secret" not in exported
    assert not EmailEnumeratorTool().can_run(context)


@pytest.mark.parametrize("spec", [spec for spec in PROBES if spec.parser != "miro"], ids=lambda spec: spec.key)
@pytest.mark.asyncio
async def test_every_probe_rejects_a_service_that_finds_every_email(monkeypatch, spec):
    bridge(monkeypatch, for_spec(spec, any_email=True))
    monkeypatch.setattr(settings, "email_enum_sites", [spec.key])
    context = TargetContext(email=EMAIL)
    assert await EmailEnumeratorTool().execute(context) == []
    assert context.extra["email_enum_diagnostics"][EMAIL][spec.key]["status"] == "non_discriminating"


@pytest.mark.parametrize("spec", PROBES, ids=lambda spec: spec.key)
@pytest.mark.parametrize("body", ["<html>false true error email taken</html>", '{"exists":"false"}', '{}'])
def test_unknown_schema_never_means_registered_or_not_registered(spec, body):
    assert parse_registration(spec.parser, httpx.Response(200, text=body)) is None


@pytest.mark.parametrize("payload,expected", [
    ({"isEmailAvailable": False}, True),
    ({"isEmailAvailable": True}, False),
    ({"isEmailAvailable": "false"}, None),
    ({"isEmailAvailable": True, "available": False}, None),
])
def test_observed_chess_schema_is_typed_and_conflicts_remain_unknown(payload, expected):
    assert parse_registration("available", httpx.Response(200, json=payload)) is expected


@pytest.mark.parametrize("payload,expected", [
    ([], False), ([{"authenticationMethods": [{"id": "password"}]}], True),
    ([{"authenticationMethods": [{"id": "saml"}]}], True), ([{"unexpected": True}], None),
])
def test_current_adobe_list_schema_includes_federated_accounts(payload, expected):
    assert parse_registration("accounts", httpx.Response(200, json=payload)) is expected


@pytest.mark.asyncio
async def test_miro_authentication_hint_is_not_registered_or_not_registered(monkeypatch):
    monkeypatch.setattr(settings, "email_enum_sites", ["miro"])
    bridge(monkeypatch, lambda request: httpx.Response(200, json={"recommendedAuthenticationType": "CREDENTIALS"}))
    context = TargetContext(email=EMAIL)
    assert await EmailEnumeratorTool().execute(context) == []
    assert execution_summary(context)["counts"] == {"auth_hint_only": 1}


@pytest.mark.parametrize("action", [None, "unknown", "", {}, ["signup"]])
def test_atlassian_never_treats_an_unknown_action_as_registered(action):
    assert parse_registration("atlassian", httpx.Response(200, json={"action": action})) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("code,status", [(403, "blocked"), (429, "rate_limited"), (404, "unavailable"), (503, "upstream_error"), (302, "redirected"), (422, "unexpected_response")])
async def test_http_failures_are_visible_and_are_not_account_absence(monkeypatch, code, status):
    bridge(monkeypatch, lambda request: httpx.Response(code, headers={"location": "https://other.example/"}, json={"exists": False}))
    monkeypatch.setattr(settings, "email_enum_sites", ["firefox"])
    context = TargetContext(email=EMAIL)
    assert await EmailEnumeratorTool().execute(context) == []
    assert context.extra["email_enum_diagnostics"][EMAIL]["firefox"]["status"] == status
    assert execution_summary(context)["counts"] == {status: 1}


@pytest.mark.asyncio
async def test_steam_code_84_is_a_rate_limit_not_an_account(monkeypatch):
    bridge(monkeypatch, lambda request: httpx.Response(200, json={"success": 84}))
    monkeypatch.setattr(settings, "email_enum_sites", ["steam"])
    context = TargetContext(email=EMAIL)
    assert await EmailEnumeratorTool().execute(context) == []
    assert execution_summary(context)["counts"] == {"rate_limited": 1}


@pytest.mark.asyncio
async def test_same_domain_control_and_encoded_email_cannot_inject_another_parameter(monkeypatch):
    seen = []
    def responder(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"taken": request.url.params["email"] == EMAIL})
    bridge(monkeypatch, responder)
    monkeypatch.setattr(settings, "email_enum_sites", ["twitter"])
    assert len(await EmailEnumeratorTool().execute(TargetContext(email=EMAIL))) == 1
    assert seen[0] == {"email": EMAIL}
    assert seen[1]["email"].endswith("@example.org")
    assert seen[1]["email"] != EMAIL


@pytest.mark.asyncio
async def test_email_budget_and_coverage_survive_pivots_and_configuration_changes(monkeypatch):
    monkeypatch.setattr(settings, "email_enum_sites", ["firefox"])
    monkeypatch.setattr(settings, "email_enum_max_emails", 2)
    bridge(monkeypatch, lambda request: httpx.Response(200, json={"exists": False}))
    context = TargetContext(email=EMAIL)
    await EmailEnumeratorTool().execute(context)
    context.discovered_emails.extend(["second@example.org", "third@example.org"])
    await EmailEnumeratorTool().execute(context)
    assert context.extra["email_enum_checked"] == [EMAIL, "second@example.org"]
    assert not EmailEnumeratorTool().can_run(context)
    assert len(durable_runtime(context.extra)["email_enum_diagnostics"]) == 2
    previous = call_fingerprint("email_enumerator", context)
    monkeypatch.setattr(settings, "email_enum_sites", ["twitter"])
    assert call_fingerprint("email_enumerator", context) != previous
    assert EmailEnumeratorTool().can_run(context)


@pytest.mark.asyncio
async def test_batch_timeout_keeps_completed_findings_and_reaps_pending_requests(monkeypatch):
    monkeypatch.setattr(settings, "email_enum_sites", ["firefox", "twitter"])
    monkeypatch.setattr(settings, "email_enum_batch_timeout", 0.1)
    hanging, cancelled = asyncio.Event(), asyncio.Event()
    async def responder(request):
        if "twitter" in request.url.host:
            hanging.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return httpx.Response(200, json={"exists": json.loads(request.content)["email"] == EMAIL})
    bridge(monkeypatch, responder)
    context = TargetContext(email=EMAIL)
    findings = await EmailEnumeratorTool().execute(context)
    assert len(findings) == 1
    assert hanging.is_set() and cancelled.is_set()
    assert execution_summary(context)["counts"] == {"budget_exhausted": 1, "registered": 1}


@pytest.mark.asyncio
async def test_invalid_inputs_and_disabled_catalog_make_no_requests(monkeypatch):
    def forbidden(request):
        raise AssertionError("No requests expected")
    bridge(monkeypatch, forbidden)
    tool = EmailEnumeratorTool()
    for context in [TargetContext(), TargetContext(email="bad"), TargetContext(email="bad@example.org/?x=1")]:
        assert not tool.can_run(context)
        assert await tool.execute(context) == []
    monkeypatch.setattr(settings, "email_enum_sites", ["unknown_module"])
    assert not tool.can_run(TargetContext(email=EMAIL))
    assert capabilities()["unknown_sites"] == ["unknown_module"]


@pytest.mark.asyncio
async def test_traditional_engine_preserves_diagnostics_and_does_not_repeat_email_on_alias_pivot(monkeypatch):
    from app.tools.registry import tool_registry
    tool = EmailEnumeratorTool()
    monkeypatch.setattr(tool_registry, "get_all", lambda: [tool])
    monkeypatch.setattr(settings, "email_enum_sites", ["firefox"])
    bridge(monkeypatch, lambda request: httpx.Response(403))
    result = await RuleEngine().collect_findings("email-integration", Target(email=EMAIL))
    assert result.findings == []
    assert execution_summary(result.context)["counts"] == {"blocked": 1}
    assert len(result.executed_runs) == 1


def test_catalog_excludes_signup_recovery_and_google_duplicates():
    assert {p.key for p in PROBES}.isdisjoint({"discord", "tumblr", "google", "gravatar"})
    assert len({p.key for p in PROBES}) == len(PROBES)
    for spec in PROBES:
        serialized = json.dumps(spec.payload).lower()
        assert 'password' not in serialized and 'consent' not in serialized
        assert not any(value in spec.url for value in ("/auth/register", "/svc/account/register", "password/reset", "forgot_password"))


@pytest.mark.parametrize("forced", [False, True])
def test_catalog_refresh_replaces_old_email_coverage_without_erasing_other_tools(forced):
    current = {"email_enum_config_id": "old", "email_enum_checked": [EMAIL, "previous@example.org"],
               "email_enum_diagnostics": {"previous@example.org": {"twitter": {"status": "blocked"}}},
               "ghunt_checked": ["email:" + EMAIL], "maigret_identifiers": [{"value": "observed", "id_type": "username"}]}
    baseline = {} if forced else dict(current)
    incoming = {"email_enum_config_id": "old" if forced else "new", "email_enum_checked": [EMAIL],
                "email_enum_diagnostics": {EMAIL: {"spotify": {"status": "not_registered"}}}}
    merged = merge_runtime(current, baseline, incoming)
    assert merged["email_enum_checked"] == [EMAIL]
    assert list(merged["email_enum_diagnostics"]) == [EMAIL]
    assert merged["ghunt_checked"] == current["ghunt_checked"]
    assert merged["maigret_identifiers"] == current["maigret_identifiers"]
