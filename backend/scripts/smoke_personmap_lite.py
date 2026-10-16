#!/usr/bin/env python3
"""Exercise Fair acquisition, review decisions and the reviewed dataset on Lite."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import engine, get_db
from app.engine.persistence import persist_findings
from app.main import app
from app.models.entity_observation import EntityObservation
from app.models.investigation import Investigation
from app.models.target import Target
from app.models.tool_execution import ToolExecution
from app.schemas.target import TargetCreate
from app.tools.base import ToolFinding


async def run_smoke() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url or make_url(database_url).database != "personmap_lite":
        raise SystemExit("El smoke test exige DATABASE_URL apuntando exactamente a personmap_lite.")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    payload = TargetCreate(
        input_version=2,
        given_names="Demo",
        family_names="Subject",
        usernames=[{"username": "lite_seed_user", "platform": "instagram"}],
    )
    target = Target(**payload.persistence_values())
    target.extra_data["subject_consent"] = True
    investigation = Investigation(
        target=target,
        strategy="rule_based",
        status="completed",
        completed_at=now,
        metrics={"acquisition_mode": "fair", "fair_snapshot": {"execution": {"partial": False}, "sources": {}}},
    )
    findings = [
        ToolFinding(entity_type="social_account", platform="instagram", value="https://instagram.com/lite_seed_user",
            metadata_info={"username": "lite_seed_user", "source_tool": "controlled_fixture"},
            evidence_urls=["https://instagram.com/lite_seed_user"]),
        ToolFinding(entity_type="social_account", platform="instagram", value="https://instagram.com/lite_confirmed",
            metadata_info={"username": "lite_confirmed", "source_tool": "controlled_fixture",
                "public_content": [{"url": "https://instagram.com/p/lite-post", "caption": "Controlled public post",
                    "origin": "automatic"}]}, evidence_urls=["https://instagram.com/lite_confirmed"]),
        ToolFinding(entity_type="social_account", platform="tiktok", value="https://www.tiktok.com/@lite_rejected",
            metadata_info={"username": "lite_rejected", "source_tool": "controlled_fixture"},
            evidence_urls=["https://www.tiktok.com/@lite_rejected"]),
        ToolFinding(entity_type="social_account", platform="github", value="https://github.com/lite_uncertain",
            metadata_info={"username": "lite_uncertain", "source_tool": "controlled_fixture"},
            evidence_urls=["https://github.com/lite_uncertain"]),
    ]

    investigation_id = None
    target_id = None
    app.dependency_overrides[get_db] = _database_dependency(factory)
    try:
        async with factory() as db:
            db.add(investigation)
            await db.flush()
            investigation_id, target_id = investigation.id, target.id
            entities = await persist_findings(str(investigation.id), findings, target, db)
            execution = ToolExecution(
                investigation_id=investigation.id,
                tool_name="controlled_fixture",
                engine="smoke_test",
                engine_layer="fixture",
                started_at=now,
                completed_at=now,
                status="completed",
                findings_count=len(entities),
                input_summary={"fixture": "synthetic"},
            )
            db.add(execution)
            await db.flush()
            db.add_all([
                EntityObservation(
                    investigation_id=investigation.id,
                    entity_id=entity.id,
                    tool_execution_id=execution.id,
                    observed_at=now,
                    source_url=entity.value,
                    evidence_urls=[entity.value],
                )
                for entity in entities
            ])
            await db.commit()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://lite-smoke") as client:
            review_url = f"/api/v1/investigations/{investigation_id}/review"
            review_response = await client.get(review_url)
            assert review_response.status_code == 200, review_response.text
            review = review_response.json()
            by_username = {candidate["username"]: candidate for candidate in review["candidates"]}
            assert "lite_seed_user" not in by_username
            assert set(by_username) == {"lite_confirmed", "lite_rejected", "lite_uncertain"}

            for username, decision in (("lite_confirmed", "confirmed"),
                                       ("lite_rejected", "rejected"),
                                       ("lite_uncertain", "uncertain")):
                response = await client.patch(f"{review_url}/{by_username[username]['id']}", json={"decision": decision})
                assert response.status_code == 200, response.text

            finalized = await client.post(f"{review_url}/finalize")
            assert finalized.status_code == 200, finalized.text
            dataset_response = await client.get(f"/api/v1/investigations/{investigation_id}/reviewed-footprint")
            assert dataset_response.status_code == 200, dataset_response.text
            dataset = dataset_response.json()
            account_ids = {item["entity_id"] for item in dataset["accounts"]}
            assert by_username["lite_confirmed"]["id"] in account_ids
            assert by_username["lite_rejected"]["id"] not in account_ids
            assert by_username["lite_uncertain"]["id"] not in account_ids
            assert any(post["account_entity_id"] == by_username["lite_confirmed"]["id"]
                       for post in dataset["social_content"])

        async with factory() as db:
            counts = (await db.execute(text("""
                SELECT
                    (SELECT count(*) FROM targets WHERE id = :target_id) AS targets,
                    (SELECT count(*) FROM investigations WHERE id = :investigation_id) AS investigations,
                    (SELECT count(*) FROM entities WHERE investigation_id = :investigation_id) AS entities,
                    (SELECT count(*) FROM tool_executions WHERE investigation_id = :investigation_id) AS executions,
                    (SELECT count(*) FROM entity_observations WHERE investigation_id = :investigation_id) AS observations,
                    (SELECT count(*) FROM review_decisions WHERE investigation_id = :investigation_id) AS decisions
            """), {"target_id": target_id, "investigation_id": investigation_id})).mappings().one()
            assert dict(counts) == {
                "targets": 1, "investigations": 1, "entities": 4,
                "executions": 1, "observations": 4, "decisions": 3,
            }
        print("SMOKE OK: Target → Investigation → Entity/observation → ReviewDecision → reviewed footprint.")
    finally:
        app.dependency_overrides.pop(get_db, None)
        if target_id is not None:
            async with factory() as db:
                await db.execute(text("DELETE FROM targets WHERE id = :target_id"), {"target_id": target_id})
                await db.commit()


def _database_dependency(factory):
    async def dependency():
        async with factory() as db:
            yield db
    return dependency


if __name__ == "__main__":
    asyncio.run(run_smoke())
