"""Foundation V2 contracts, with no live OSINT or database dependency."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.agent.tool_dispatch import build_call_context
from app.core.config import settings
from app.engine.hybrid_engine import HybridEngine
from app.engine.persistence import persist_findings
from app.engine.pivot_frontier import PivotFrontier
from app.engine.pivot_rules import extract_and_apply_pivots
from app.engine.rule_engine import RuleEngine
from app.identity.evidence import target_affinity
from app.models.entity import Entity
from app.models.target import Target
from app.schemas.entity import EntityRead
from app.schemas.footprint import DataProvenance, FootprintInput
from app.schemas.investigation import InvestigationCreate
from app.schemas.target import TargetCreate, TargetRead
from app.tools.base import BaseTool, TargetContext, ToolFinding
from app.tools.registry import tool_registry


def payload(**overrides):
    values = dict(input_version=2, given_names="  Ana   María ", family_names=" Pérez Díaz ",
        emails=[" ANA@example.org ", "ana@university.edu.pe", "ana@example.org"],
        usernames=[{"username": " @ana-code ", "platform": " GitHub "},
                   {"username": "ana-other"}, {"username": "ana-code", "platform": "github"},
                   {"username": "ana-code", "platform": "My Future Platform"}],
        phones=["912 345 678", "+51 912345678", "+1 (415) 555-2671", "+1 4155552671 ext. 12"])
    return TargetCreate(**{**values, **overrides})


def target(**overrides):
    return Target(id=uuid4(), created_at=datetime.now(timezone.utc), **payload(**overrides).persistence_values())


def test_multiple_identifiers_normalization_dedupe_and_namespace():
    data = payload()
    assert data.input_version == 2
    assert data.full_name == "Ana María Pérez Díaz"
    assert data.emails == ["ana@example.org", "ana@university.edu.pe"]
    assert [(item.username, item.platform) for item in data.usernames] == [
        ("ana-code", "github"), ("ana-other", None), ("ana-code", "my future platform")]
    assert data.phones == ["+51912345678", "+14155552671", "+14155552671;ext=12"]
    assert (data.email, data.username, data.phone) == (data.emails[0], data.usernames[0].username, data.phones[0])


def test_usernames_preserve_case_sensitive_values_and_optional_free_platform():
    data = FootprintInput(usernames=[{"username": "Álias.A"}, {"username": "álias.a"},
        {"username": "Álias.A", "platform": "   "}, {"username": "x", "platform": "future.social"}])
    assert len(data.usernames) == 3
    assert data.usernames[-1].platform == "future.social"


@pytest.mark.parametrize("fields", [
    {"given_names": "Ana"}, {"family_names": "Pérez"}, {"emails": ["a@example.org"]},
    {"usernames": [{"username": "a"}]}, {"phones": ["+14155552671"]},
])
def test_any_v2_identifier_is_sufficient_and_cannot_opt_out_of_consent(fields):
    data = TargetCreate(**fields, input_version=1)
    assert data.input_version == 2
    with pytest.raises(ValidationError, match="autorización"):
        InvestigationCreate(target=data)
    assert InvestigationCreate(target=data, subject_consent=True).self_consent is False


@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_consent_is_explicit_boolean(value):
    with pytest.raises(ValidationError):
        InvestigationCreate(target=payload(), subject_consent=value)


@pytest.mark.parametrize("fields", [
    {"emails": ["not-email"]}, {"phones": ["123"]},
    {"emails": ['a"b@example.org']},
    {"usernames": [{"username": "https://github.com/ana"}]},
    {"emails": ["x@example.org"] * 31}, {"given_names": "a" * 121},
    {"dni": "12345678"}, {"description": "personal description"},
    {"identifiers": [{"value": "0000-0002-1825-0097", "id_type": "orcid"}]},
    {"email": "different@example.org"},
])
def test_invalid_or_ambiguous_v2_input_is_rejected(fields):
    with pytest.raises(ValidationError):
        payload(**fields)


def test_no_blank_only_target_and_no_plus_tag_or_extension_collapse():
    with pytest.raises(ValidationError):
        TargetCreate(input_version=2, given_names=" ", emails=[], usernames=[], phones=[])
    data = FootprintInput(emails=["a.b+tag@example.org", "ab@example.org", "a.b@example.org"])
    assert len(data.emails) == 3


def test_declared_seed_provenance_is_server_generated_and_serializes():
    row = target(extra_data={"footprint_input": {"malicious": True}, "subject_consent": True})
    result = TargetRead.model_validate(row).model_dump(mode="json")
    declared = result["footprint_input"]
    assert declared == result["extra_data"]["footprint_input"]
    assert result["extra_data"].get("subject_consent") is None
    assert len(declared["declared_seeds"]) == 9
    for seed in declared["declared_seeds"]:
        assert seed["provenance"] == {"origin": "subject", "status": "declared",
            "subject_asserted": True, "needs_review": False, "evidence_urls": [], "matches_declared_identifier": False}
    # A JSON round trip must not turn computed provenance into editable input.
    declared["declared_seeds"][0]["provenance"]["status"] = "rejected"
    assert FootprintInput.model_validate(declared).declared_seeds[0].provenance.status == "declared"


def test_context_lists_and_call_overrides_do_not_promote_discoveries():
    row = target()
    ctx = TargetContext.from_target(row)
    assert ctx.all_emails() == ["ana@example.org", "ana@university.edu.pe"]
    assert ctx.all_usernames() == ["ana-code", "ana-other"]
    assert len(ctx.all_phones()) == 3
    assert ctx.discovered_emails == ctx.discovered_usernames == ctx.discovered_phones == []
    override = build_call_context({"email": "suggested@example.org"}, row, ctx)
    assert override.email == "suggested@example.org"
    assert "suggested@example.org" not in override.declared_values("email")
    assert override.declared_seeds == ctx.declared_seeds
    assert build_call_context({}, row).all_emails() == ctx.all_emails()
    serialized = TargetContext.model_validate_json(ctx.model_dump_json())
    assert serialized.declared_seeds == ctx.declared_seeds


def test_pivot_extraction_only_adds_new_discovered_values(monkeypatch):
    monkeypatch.setattr(settings, "phone_max_numbers", 10)
    ctx = TargetContext.from_target(target())
    finding = ToolFinding(entity_type="social_account", value="https://example.org/ana", metadata_info={
        "extracted_emails": ["ana@university.edu.pe", "new@example.org"],
        "extracted_usernames": ["ana-other", "new-alias"],
        "extracted_phones": ["+14155552671", "+442079460018"], "source_tool": "fixture"})
    assert extract_and_apply_pivots([finding], ctx)
    assert ctx.discovered_emails == ["new@example.org"]
    assert ctx.discovered_usernames == ["new-alias"]
    assert ctx.discovered_phones == ["+442079460018"]
    assert all(not seed.provenance.needs_review for seed in ctx.declared_seeds)


def test_frontier_seeds_all_declared_values_without_reclassifying_them():
    row = target()
    ctx = TargetContext.from_target(row)
    frontier = PivotFrontier(ctx)
    frontier.seed(row)
    ranked = frontier.rank()
    # Same alias across platforms is one exploration input, not one identity.
    assert len(ranked) == 8
    assert {item.confidence_class for item in ranked} == {"P0"}
    frontier.next(1)
    view = frontier.execution_view()
    assert view.all_emails() == ctx.all_emails()
    assert set(view.all_usernames()) == set(ctx.all_usernames())
    assert set(view.all_phones()) == set(ctx.all_phones())
    assert view.discovered_emails == view.discovered_usernames == []
    frontier.merge_view(view)
    assert all(seed.provenance.status == "declared" for seed in ctx.declared_seeds)


@pytest.mark.asyncio
@pytest.mark.parametrize("frontier_enabled", [True, False])
async def test_rule_sweep_receives_multiple_declared_inputs(monkeypatch, frontier_enabled):
    monkeypatch.setattr(settings, "pivot_frontier_enabled", frontier_enabled)
    seen = []
    class Tool(BaseTool):
        name = "fixture"
        description = "Controlled multi-seed fixture"
        required_inputs = ["email", "username", "phone"]
        async def execute(self, context):
            seen.append(context)
            return []
    monkeypatch.setattr(tool_registry, "get_all", lambda: [Tool()])
    sweep = await RuleEngine().collect_findings(str(uuid4()), target())
    assert len(seen) == 1
    assert len(seen[0].all_emails()) == 2
    assert len(seen[0].all_usernames()) == 2
    assert len(seen[0].all_phones()) == 3
    assert sweep.context.discovered_emails == []


def test_hybrid_run_key_retains_all_seed_inputs():
    ctx = TargetContext.from_target(target())
    tool = tool_registry.get_tool("email_checker")
    assert HybridEngine()._run_key("email_checker", {}, ctx) == RuleEngine()._get_tool_run_key(tool, ctx)


def test_correlation_matches_second_seed_but_never_confirms_alias_or_new_email():
    row = target()
    entity = Entity(entity_type="social_account", platform="github", value="https://github.com/ana-other",
        source_tool="social_verifier", metadata_info={"verification_status": "verified",
        "extracted_emails": ["ana@university.edu.pe"], "username": "ana-other"})
    affinity = target_affinity(entity, row)
    assert affinity["level"] == "strong"
    assert affinity["ownership_status"] == "unverified"
    entity.metadata_info = {"verification_status": "verified", "username": "ana-other"}
    assert target_affinity(entity, row)["weight"] == 0
    entity.metadata_info["extracted_emails"] = ["new@example.org"]
    assert target_affinity(entity, row)["weight"] == 0
    entity.metadata_info = {"phones": ["+14155552671"], "verification_status": "verified"}
    assert target_affinity(entity, row)["level"] == "strong"


@pytest.mark.asyncio
async def test_automatic_account_is_not_confirmed_by_declared_alias_or_tool_metadata():
    db = SimpleNamespace(add=lambda row: None, flush=AsyncMock())
    finding = ToolFinding(entity_type="social_account", value="https://github.com/ana-code",
        metadata_info={"source_tool": "fixture", "username": "ana-code", "provenance": {
            "origin": "subject", "status": "declared", "subject_asserted": True}},
        evidence_urls=["https://github.com/ana-code"])
    entities = await persist_findings(str(uuid4()), [finding], target(), db)
    provenance = DataProvenance.model_validate(entities[0].metadata_info["provenance"])
    assert provenance.status == "discovered" and provenance.needs_review
    assert provenance.origin == "automatic" and not provenance.subject_asserted
    assert provenance.evidence_urls == finding.evidence_urls


def test_historical_scalar_target_keeps_original_contract_without_subject_claims():
    row = Target(id=uuid4(), created_at=datetime.now(timezone.utc), full_name="Legacy Name",
                 email="old@example.org", username="old", phone="+51912345678", extra_data={})
    assert TargetRead.model_validate(row).footprint_input is None
    ctx = TargetContext.from_target(row)
    assert ctx.all_emails() == ["old@example.org"]
    assert ctx.declared_seeds == []
    assert not ctx.extra["self_consent"]
    assert not InvestigationCreate(target=TargetCreate(email="old@example.org")).subject_consent
    legacy = TargetCreate(email="old@example.org", username="old")
    assert TargetCreate.model_validate_json(legacy.model_dump_json()) == legacy
    v2 = payload()
    assert TargetCreate.model_validate_json(v2.model_dump_json()) == v2


def test_historical_null_json_fields_serialize_without_mutating_rows():
    from app.models.investigation import Investigation
    from app.schemas.investigation import InvestigationRead
    row = Target(id=uuid4(), created_at=datetime.now(timezone.utc), username="old", extra_data=None)
    inv = Investigation(id=uuid4(), target=row, target_id=row.id, status="pending", strategy="rule_based",
        execution_mode="internal", revision=0, metrics=None, created_at=datetime.now(timezone.utc))
    result = InvestigationRead.model_validate(inv).model_dump(mode="json")
    assert result["metrics"] == result["target"]["extra_data"] == {}
    assert inv.metrics is None and row.extra_data is None


def test_discovery_api_serialization_and_future_states():
    row = Entity(id=uuid4(), investigation_id=uuid4(), entity_type="email", value="a@example.org",
        source_tool="fixture", discovered_at=datetime.now(timezone.utc), metadata_info={})
    result = EntityRead.model_validate(row).model_dump(mode="json")
    assert result["provenance"]["status"] == "discovered"
    assert result["provenance"]["needs_review"]
    for status in ("confirmed", "rejected", "uncertain"):
        state = DataProvenance(origin="automatic", status=status, subject_asserted=status == "confirmed")
        assert state.needs_review == (status == "uncertain")


@pytest.mark.asyncio
async def test_rest_validation_and_response_serialization(monkeypatch):
    from app.api.v1 import investigations as routes
    from app.core.database import get_db
    from app.models.investigation import Investigation
    row = target()
    inv = Investigation(id=uuid4(), target_id=row.id, target=row, strategy="rule_based", status="pending",
        execution_mode="external", revision=0, metrics={}, created_at=datetime.now(timezone.utc))
    create = AsyncMock(return_value=inv)
    monkeypatch.setattr(routes.workspace, "create", create)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    async def no_database_for_workspace_create():
        return None
    app.dependency_overrides[get_db] = no_database_for_workspace_create
    body = {"target": {"emails": ["a@example.org", "b@example.org"]}, "execution_mode": "external"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.post("/api/v1/investigations", json=body)
        assert denied.status_code == 422
        create.assert_not_awaited()
        response = await client.post("/api/v1/investigations", json={**body, "subject_consent": True})
        assert response.status_code == 201
        result = response.json()["target"]["footprint_input"]
        assert result["emails"] == row.footprint_input["emails"]
        assert not any(seed["provenance"]["needs_review"] for seed in result["declared_seeds"])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["confirmed", "rejected", "uncertain"])
async def test_enrichment_preserves_existing_human_decision_and_original_origin(status):
    provenance = DataProvenance(origin="automatic", status=status,
        subject_asserted=status == "confirmed", evidence_urls=["https://example.org/original"]).model_dump(mode="json")
    existing = Entity(id=uuid4(), entity_type="social_account", value="https://github.com/ana-code",
        source_tool="fixture", metadata_info={"provenance": provenance})
    finding = ToolFinding(entity_type="social_account", value=existing.value,
        metadata_info={"source_tool": "new_fixture", "provenance": {"status": "discovered"}})
    db = SimpleNamespace(add=lambda row: None, flush=AsyncMock())
    result = await persist_findings(str(uuid4()), [finding], target(), db, existing_entities=[existing])
    assert result == [existing]
    assert existing.metadata_info["provenance"] == provenance


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,value,needs_review", [
    ("email", "ana@university.edu.pe", False), ("phone", "+1 415 555 2671", False),
    ("username", "ana-other", False), ("email", "new@example.org", True),
    ("social_account", "https://github.com/ana-code", True), ("breach", "ana@example.org", True),
])
async def test_reanalyzing_declared_identifier_does_not_require_reconfirmation(kind, value, needs_review):
    finding = ToolFinding(entity_type=kind, value=value, metadata_info={"source_tool": "fixture"})
    db = SimpleNamespace(add=lambda row: None, flush=AsyncMock())
    saved = await persist_findings(str(uuid4()), [finding], target(), db)
    provenance = DataProvenance.model_validate(saved[0].metadata_info["provenance"])
    assert provenance.needs_review is needs_review
    assert provenance.origin == "automatic" and provenance.status == "discovered"
    assert not provenance.subject_asserted  # Analysis itself was not supplied by the subject.


def test_atomic_username_review_exemption_requires_the_declared_namespace():
    from app.schemas.footprint import is_declared_identifier
    row = target()
    assert is_declared_identifier(row, "username", "ana-code", "GitHub")
    assert not is_declared_identifier(row, "username", "ana-code", "Reddit")
    assert not is_declared_identifier(row, "username", "ana-code")
    assert not is_declared_identifier(row, "username", "ana-other", "GitHub")
