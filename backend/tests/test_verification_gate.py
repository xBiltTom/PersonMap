"""PostgreSQL and REST integration coverage for the persisted Fair review gate.

Run against a disposable PostgreSQL database with:
  VERIFICATION_GATE_TEST_DATABASE_URL=postgresql+asyncpg://... pytest -m db tests/test_verification_gate.py -q
"""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import get_db
from app.core.events import event_bus
from app.engine.persistence import persist_findings
from app.models.entity import Entity
from app.models.investigation import Investigation
from app.models.relationship import Relationship
from app.models.review_decision import ReviewDecision
from app.models.target import Target
from app.schemas.footprint import discovered_provenance
from app.schemas.target import TargetCreate
from app.tools.base import ToolFinding

pytestmark = pytest.mark.db


@pytest_asyncio.fixture
async def fair_review_workspace(monkeypatch):
    from app.main import app

    schema = "review_gate_" + uuid.uuid4().hex
    database_url = os.getenv("VERIFICATION_GATE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Configura VERIFICATION_GATE_TEST_DATABASE_URL con una base PostgreSQL descartable.")
    bootstrap = create_async_engine(database_url, poolclass=NullPool)
    async with bootstrap.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(database_url, poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))

    def migrate(connection):
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    async with engine.begin() as connection:
        await connection.run_sync(migrate)
    target_payload = TargetCreate(input_version=2, given_names="Ana", family_names="Pérez",
        emails=["declared@example.org"], usernames=[{"username": "pepito", "platform": "instagram"}],
        phones=["+51912345678"])
    target = Target(**target_payload.persistence_values())
    target.extra_data["subject_consent"] = True
    investigation = Investigation(target=target, strategy="rule_based", status="completed",
        completed_at=datetime.now(timezone.utc), metrics={"acquisition_mode": "fair", "fair_snapshot": {
            "execution": {"partial": True},
            "sources": {"search_dorker": {"status": "partial", "reason": "query_budget", "findings_count": 2},
                        "ghunt": {"status": "provider_unavailable", "reason": "session_missing", "findings_count": 0}},
        }, "fair_progress": {"social_sources": {
            "instagram": {"status": "completed", "reason": "observed"},
            "tiktok": {"status": "timeout", "reason": "tool_or_global_deadline"},
        }}})
    normal_target = Target(username="normal-user", extra_data={})
    normal_investigation = Investigation(target=normal_target, strategy="rule_based", status="completed",
        completed_at=datetime.now(timezone.utc), metrics={"acquisition_mode": "normal"})
    async with factory() as db:
        db.add_all([investigation, normal_investigation])
        await db.commit()
        investigation_id, normal_id = investigation.id, normal_investigation.id

    async def get_test_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "factory": factory, "investigation_id": investigation_id,
                   "normal_id": normal_id, "target_id": target.id}
        finally:
            app.dependency_overrides.pop(get_db, None)
    await engine.dispose()
    async with bootstrap.begin() as connection:
        await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await bootstrap.dispose()


async def add_finding(workspace, finding: ToolFinding) -> Entity:
    async with workspace["factory"]() as db:
        target = await db.get(Target, workspace["target_id"])
        rows = await persist_findings(str(workspace["investigation_id"]), [finding], target, db)
        await db.commit()
        return rows[0]


async def seed_findings(workspace):
    declared = await add_finding(workspace, ToolFinding(entity_type="social_account", platform="instagram",
        value="https://instagram.com/pepito", metadata_info={"username": "pepito", "source_tool": "social_verifier"},
        evidence_urls=["https://instagram.com/pepito"]))
    instagram = await add_finding(workspace, ToolFinding(entity_type="social_account", platform="instagram",
        value="https://instagram.com/pepito_alt", display_name="Pepito alternate", confidence=.8,
        metadata_info={"username": "pepito_alt", "bio": "Public profile bio", "source_tool": "search_dorker",
            "source_tools": ["search_dorker", "social_verifier"], "literal_match": True,
            "public_content": [{"url": "https://instagram.com/p/post-a", "caption": "Observed public post",
                "posted_at": "2026-10-01", "origin": "automatic"}]},
        evidence_urls=["https://search.example/result", "https://instagram.com/pepito_alt"]))
    tiktok = await add_finding(workspace, ToolFinding(entity_type="social_account", platform="tiktok",
        value="https://www.tiktok.com/@pepito", metadata_info={"username": "pepito", "source_tool": "username_finder"},
        evidence_urls=["https://www.tiktok.com/@pepito"]))
    email = await add_finding(workspace, ToolFinding(entity_type="email", value="new@example.org",
        metadata_info={"source_tool": "email_enumerator"}, evidence_urls=["https://example.org/email-evidence"]))
    phone = await add_finding(workspace, ToolFinding(entity_type="phone", platform="telephony",
        value="+442079460018", metadata_info={"source_tool": "phone_lookup"}, evidence_urls=["https://example.org/phone"]))
    declared_breach = await add_finding(workspace, ToolFinding(entity_type="breach", value="declared@example.org",
        platform="data_leak", metadata_info={"email": "declared@example.org", "breaches": ["Archive A"],
            "source_tool": "breach_checker"}, evidence_urls=["https://xposedornot.com/email/declared@example.org"]))
    pending_email_breach = await add_finding(workspace, ToolFinding(entity_type="breach", value="new@example.org",
        platform="data_leak", metadata_info={"email": "new@example.org", "breaches": ["Archive B"],
            "source_tool": "breach_checker"}, evidence_urls=["https://xposedornot.com/email/new@example.org"]))
    academic_profile = await add_finding(workspace, ToolFinding(entity_type="academic", platform="openalex_author",
        value="https://openalex.org/A123", display_name="Ana Pérez", metadata_info={"source_tool": "academic_finder",
            "query_name": "Ana Pérez", "institutions": ["Universidad X"], "affiliation_match": True,
            "profile_url": "https://openalex.org/A123"}, evidence_urls=["https://openalex.org/A123"]))
    paper = await add_finding(workspace, ToolFinding(entity_type="academic", platform="research_paper",
        value="https://doi.org/10.1234/fixture", display_name="Verified paper", metadata_info={
            "source_tool": "academic_finder", "academic_records": [{"authors": [{"name": "Coauthor One"}],
                "matched_authors": [{"name": "Ana Pérez"}], "match_basis": "openalex_author_id"}],
            "authorship_evidence": "openalex_author_id"}, evidence_urls=["https://doi.org/10.1234/fixture"]))
    async with workspace["factory"]() as db:
        db.add(Relationship(investigation_id=workspace["investigation_id"], source_entity_id=academic_profile.id,
            target_entity_id=paper.id, relation_type="authored_work", supports_group=False,
            evidence={"verified_by": "academic_engine"}))
        await db.commit()
    return {"declared": declared, "instagram": instagram, "tiktok": tiktok, "email": email, "phone": phone,
        "declared_breach": declared_breach, "pending_email_breach": pending_email_breach,
        "academic_profile": academic_profile, "paper": paper}


@pytest.mark.asyncio
async def test_candidates_exclude_declared_accounts_and_show_partial_acquisition(fair_review_workspace):
    workspace = fair_review_workspace
    entities = await seed_findings(workspace)
    response = await workspace["client"].get(f"/api/v1/investigations/{workspace['investigation_id']}/review")
    assert response.status_code == 200
    data = response.json()
    candidate_ids = {candidate["id"] for candidate in data["candidates"]}
    assert str(entities["declared"].id) not in candidate_ids
    assert {str(entities["instagram"].id), str(entities["tiktok"].id), str(entities["email"].id),
            str(entities["phone"].id), str(entities["academic_profile"].id)} <= candidate_ids
    assert data["review_status"] == "not_started"
    assert data["counts"]["pending"] == len(candidate_ids)
    assert data["fair"]["partial"] is True
    assert "fuentes incompletas" in data["fair"]["warning"]
    assert data["fair"]["social_sources"]["tiktok"]["status"] == "timeout"
    assert {seed["kind"] for seed in data["declared_seeds"]} >= {"email", "phone", "username", "name"}
    assert all(candidate["id"] != str(entities["declared"].id) for candidate in data["candidates"])


@pytest.mark.asyncio
async def test_human_decision_is_persistent_idempotent_and_keeps_automatic_origin(fair_review_workspace):
    workspace = fair_review_workspace
    entities = await seed_findings(workspace)
    path = f"/api/v1/investigations/{workspace['investigation_id']}/review/{entities['instagram'].id}"
    first = await workspace["client"].patch(path, json={"decision": "confirmed"})
    assert first.status_code == 200
    account = next(item for item in first.json()["candidates"] if item["id"] == str(entities["instagram"].id))
    assert account["decision"] == "confirmed"
    assert account["provenance"]["origin"] == "automatic"
    assert account["provenance"]["status"] == "confirmed"
    replay = await workspace["client"].patch(path, json={"decision": "confirmed"})
    assert replay.status_code == 200
    async with workspace["factory"]() as db:
        row = (await db.execute(select(ReviewDecision).where(ReviewDecision.entity_id == entities["instagram"].id))).scalar_one()
        entity = await db.get(Entity, entities["instagram"].id)
        assert len(row.history) == 1
        assert entity.metadata_info["provenance"]["origin"] == "automatic"
        assert entity.metadata_info["provenance"]["status"] == "confirmed"
        assert entity.metadata_info["ownership"]["status"] == "subject_confirmed"
        target = await db.get(Target, workspace["target_id"])
        existing = list((await db.scalars(select(Entity).where(
            Entity.investigation_id == workspace["investigation_id"]))).all())
        refreshed = await persist_findings(str(workspace["investigation_id"]), [ToolFinding(
            entity_type="social_account", platform="instagram", value="https://instagram.com/pepito_alt",
            metadata_info={"username": "pepito_alt", "source_tool": "apify_social",
                "provenance": {"origin": "automatic", "status": "rejected"},
                "ownership": {"status": "subject_rejected", "needs_review": False},
                "ownership_status": "subject_rejected"},
            evidence_urls=["https://apify.example/result"])], target, db, existing_entities=existing)
        await db.commit()
        assert refreshed[0].id == entities["instagram"].id
        assert refreshed[0].metadata_info["provenance"]["status"] == "confirmed"
        assert refreshed[0].metadata_info["ownership"]["status"] == "subject_confirmed"
    persisted = await workspace["client"].get(f"/api/v1/investigations/{workspace['investigation_id']}/review")
    assert next(item for item in persisted.json()["candidates"] if item["id"] == str(entities["instagram"].id))["decision"] == "confirmed"
    assert any(event.get("type") == "verification_review_updated" for event in event_bus.get_history(str(workspace["investigation_id"])))


@pytest.mark.asyncio
async def test_reject_and_uncertain_retain_raw_findings_and_are_excluded_from_dataset(fair_review_workspace):
    workspace = fair_review_workspace
    entities = await seed_findings(workspace)
    rejected = await workspace["client"].patch(
        f"/api/v1/investigations/{workspace['investigation_id']}/review/{entities['instagram'].id}",
        json={"decision": "rejected"})
    uncertain = await workspace["client"].patch(
        f"/api/v1/investigations/{workspace['investigation_id']}/review/{entities['email'].id}",
        json={"decision": "uncertain"})
    assert rejected.status_code == uncertain.status_code == 200
    async with workspace["factory"]() as db:
        assert await db.get(Entity, entities["instagram"].id) is not None
        assert await db.get(Entity, entities["email"].id) is not None
        assert (await db.get(Entity, entities["instagram"].id)).metadata_info["provenance"]["origin"] == "automatic"
    before_final = await workspace["client"].get(f"/api/v1/investigations/{workspace['investigation_id']}/reviewed-footprint")
    assert before_final.status_code == 409 and before_final.json()["detail"]["code"] == "review_not_finalized"
    finalized = await workspace["client"].post(f"/api/v1/investigations/{workspace['investigation_id']}/review/finalize")
    assert finalized.status_code == 200
    dataset_response = await workspace["client"].get(f"/api/v1/investigations/{workspace['investigation_id']}/reviewed-footprint")
    assert dataset_response.status_code == 200
    dataset = dataset_response.json()
    assert str(entities["instagram"].id) not in {item["entity_id"] for item in dataset["accounts"]}
    assert str(entities["email"].id) not in {item["entity_id"] for item in dataset["emails"]}
    assert {item["entity_id"] for item in dataset["review"]["rejected"]} == {str(entities["instagram"].id)}
    assert {item["entity_id"] for item in dataset["review"]["uncertain"]} == {str(entities["email"].id)}
    assert {item["email"] for item in dataset["breaches"]} == {"declared@example.org"}
    assert dataset["execution"]["acquisition_partial"] is True


@pytest.mark.asyncio
async def test_confirmed_account_inherits_public_content_but_not_same_alias_on_other_platform(fair_review_workspace):
    workspace = fair_review_workspace
    entities = await seed_findings(workspace)
    await workspace["client"].patch(
        f"/api/v1/investigations/{workspace['investigation_id']}/review/{entities['instagram'].id}",
        json={"decision": "confirmed"})
    await workspace["client"].post(f"/api/v1/investigations/{workspace['investigation_id']}/review/finalize")
    dataset = (await workspace["client"].get(f"/api/v1/investigations/{workspace['investigation_id']}/reviewed-footprint")).json()
    account_ids = {item["entity_id"] for item in dataset["accounts"]}
    assert str(entities["instagram"].id) in account_ids
    assert str(entities["declared"].id) in account_ids
    assert str(entities["tiktok"].id) not in account_ids
    declared_account = next(item for item in dataset["accounts"] if item["ownership"]["status"] == "subject_declared")
    declared_seed = next(item for item in dataset["subject"]["declared"] if item["kind"] == "username")
    assert declared_account["username"] == "pepito"
    assert declared_account["seed_id"] == declared_seed["seed_id"]
    assert len(dataset["social_content"]) == 1
    post = dataset["social_content"][0]
    assert post["account_entity_id"] == str(entities["instagram"].id)
    assert post["origin"] == "automatic"
    assert all(candidate["entity_type"] != "social_post" for candidate in (await workspace["client"].get(
        f"/api/v1/investigations/{workspace['investigation_id']}/review")).json()["candidates"])


@pytest.mark.asyncio
async def test_breach_uses_attributed_email_and_academic_profile_includes_verified_work_only(fair_review_workspace):
    workspace = fair_review_workspace
    entities = await seed_findings(workspace)
    await workspace["client"].patch(
        f"/api/v1/investigations/{workspace['investigation_id']}/review/{entities['email'].id}", json={"decision": "confirmed"})
    await workspace["client"].patch(
        f"/api/v1/investigations/{workspace['investigation_id']}/review/{entities['academic_profile'].id}",
        json={"decision": "confirmed"})
    await workspace["client"].post(f"/api/v1/investigations/{workspace['investigation_id']}/review/finalize")
    dataset = (await workspace["client"].get(f"/api/v1/investigations/{workspace['investigation_id']}/reviewed-footprint")).json()
    assert {item["email"] for item in dataset["breaches"]} == {"declared@example.org", "new@example.org"}
    assert [item["value"] for item in dataset["academic_profiles"]] == ["https://openalex.org/A123"]
    assert [item["value"] for item in dataset["documents"]] == ["https://doi.org/10.1234/fixture"]
    assert dataset["documents"][0]["associated_profile_entity_id"] == str(entities["academic_profile"].id)
    assert dataset["documents"][0]["authorship_evidence"]["verified_by"] == "academic_engine"
    assert "Coauthor One" not in {item["value"] for item in dataset["academic_profiles"]}


@pytest.mark.asyncio
async def test_decision_changes_and_new_candidates_do_not_erase_prior_review(fair_review_workspace):
    workspace = fair_review_workspace
    entities = await seed_findings(workspace)
    path = f"/api/v1/investigations/{workspace['investigation_id']}/review/{entities['instagram'].id}"
    await workspace["client"].patch(path, json={"decision": "confirmed"})
    changed = await workspace["client"].patch(path, json={"decision": "rejected"})
    assert changed.status_code == 200
    async with workspace["factory"]() as db:
        row = (await db.execute(select(ReviewDecision).where(ReviewDecision.entity_id == entities["instagram"].id))).scalar_one()
        assert row.decision == "rejected" and len(row.history) == 2
    await workspace["client"].post(f"/api/v1/investigations/{workspace['investigation_id']}/review/finalize")
    new_entity = await add_finding(workspace, ToolFinding(entity_type="social_account", platform="instagram",
        value="https://instagram.com/new_after_finalize", metadata_info={"username": "new_after_finalize",
            "source_tool": "username_finder"}, evidence_urls=["https://instagram.com/new_after_finalize"]))
    review = (await workspace["client"].get(f"/api/v1/investigations/{workspace['investigation_id']}/review")).json()
    by_id = {candidate["id"]: candidate for candidate in review["candidates"]}
    assert review["review_status"] == "in_progress"
    assert by_id[str(entities["instagram"].id)]["decision"] == "rejected"
    assert by_id[str(new_entity.id)]["decision"] is None
    stale = await workspace["client"].get(f"/api/v1/investigations/{workspace['investigation_id']}/reviewed-footprint")
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_declared_is_not_patchable_tools_cannot_confirm_and_normal_mode_is_unchanged(fair_review_workspace):
    workspace = fair_review_workspace
    entities = await seed_findings(workspace)
    gate = f"/api/v1/investigations/{workspace['investigation_id']}"
    forged = await add_finding(workspace, ToolFinding(entity_type="social_account", platform="instagram",
        value="https://instagram.com/forged", metadata_info={"username": "forged", "source_tool": "agent",
            "provenance": {"origin": "subject", "status": "confirmed", "subject_asserted": True},
            "ownership_status": "confirmed"}, evidence_urls=["https://instagram.com/forged"]))
    async with workspace["factory"]() as db:
        stored = await db.get(Entity, forged.id)
        assert stored.metadata_info["provenance"]["origin"] == "automatic"
        assert stored.metadata_info["provenance"]["status"] == "discovered"
        assert stored.metadata_info["ownership_status"] == "unverified"
    declared_patch = await workspace["client"].patch(f"{gate}/review/{entities['declared'].id}",
        json={"decision": "confirmed"})
    assert declared_patch.status_code == 404
    forged_body = await workspace["client"].patch(f"{gate}/review/{forged.id}",
        json={"decision": "confirmed", "metadata_info": {"ownership_status": "confirmed"}})
    assert forged_body.status_code == 422
    normal = await workspace["client"].get(f"/api/v1/investigations/{workspace['normal_id']}/review")
    assert normal.status_code == 404
