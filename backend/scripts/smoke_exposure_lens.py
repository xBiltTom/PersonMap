#!/usr/bin/env python3
"""Run a provider-free Exposure Lens fixture exclusively on personmap_lite."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.database import engine, get_db
from app.exposure import ai as exposure_ai
from app.main import app
from app.models.exposure_run import ExposureContentCache, ExposureRun
from app.models.investigation import Investigation
from app.models.review_decision import ReviewDecision
from app.models.target import Target
from app.schemas.review import ReviewedFootprintDataset
from app.schemas.target import TargetCreate
from app.services.exposure_lens import _is_attributed, _unit_hash, _units
from app.tools.base import ToolFinding
from app.engine.persistence import persist_findings


FIXTURE_TAG = "smoke_exposure_lens_20261016"


async def run_smoke() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if os.getenv("PERSONMAP_ENV") != "lite" or settings.personmap_env != "lite":
        raise SystemExit("El smoke test exige PERSONMAP_ENV=lite.")
    if not database_url or make_url(database_url).database != "personmap_lite":
        raise SystemExit("El smoke test exige DATABASE_URL apuntando exactamente a personmap_lite.")
    if make_url(settings.database_url).database != "personmap_lite":
        raise SystemExit("La configuración del backend no apunta a personmap_lite.")

    async with engine.connect() as connection:
        actual_database = (await connection.execute(text("SELECT current_database()"))).scalar_one()
        if actual_database != "personmap_lite":
            raise SystemExit("La conexión real no terminó en personmap_lite.")

    # This smoke is provider-free even when the local demo enables Exposure AI.
    settings.exposure_ai_enabled = False
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    payload = TargetCreate(
        input_version=2,
        given_names="Exposure",
        family_names="Fixture",
        emails=[f"{FIXTURE_TAG}@example.org"],
        usernames=[{"username": FIXTURE_TAG, "platform": "instagram"}],
    )
    target = Target(**payload.persistence_values())
    target.extra_data["subject_consent"] = True
    investigation = Investigation(
        target=target,
        strategy="rule_based",
        status="completed",
        completed_at=now,
        metrics={
            "acquisition_mode": "fair",
            "fair_snapshot": {"execution": {"partial": False}, "sources": {}},
        },
    )
    investigation_id = None
    target_id = None
    cache_hashes: set[str] = set()
    app.dependency_overrides[get_db] = _database_dependency(factory)
    try:
        async with factory() as db:
            db.add(investigation)
            await db.flush()
            investigation_id, target_id = investigation.id, target.id
            findings = [
                ToolFinding(
                    entity_type="social_account",
                    platform="instagram",
                    value=f"https://www.instagram.com/{FIXTURE_TAG}/",
                    metadata_info={
                        "username": FIXTURE_TAG,
                        "bio": f"Contact {FIXTURE_TAG}@example.org",
                        "source_tool": "controlled_fixture",
                    },
                    evidence_urls=[f"https://www.instagram.com/{FIXTURE_TAG}/"],
                ),
                ToolFinding(
                    entity_type="social_account",
                    platform="tiktok",
                    value=f"https://www.tiktok.com/@{FIXTURE_TAG}",
                    metadata_info={
                        "username": FIXTURE_TAG,
                        "bio": f"Contact {FIXTURE_TAG}@example.org · https://www.instagram.com/{FIXTURE_TAG}/",
                        "source_tool": "controlled_fixture",
                        "public_content": [{
                            "id": f"{FIXTURE_TAG}-post",
                            "url": f"https://www.tiktok.com/@{FIXTURE_TAG}/video/{FIXTURE_TAG}",
                            "caption": (
                                "Tengo lupus y estudio en Universidad del Norte. "
                                "Trabajo en Empresa Y y todos los martes entro a las 08:10. "
                                "Nos vemos en Calle Olivos 123 para el evento. "
                                f"Contact {FIXTURE_TAG}@example.org."
                            ),
                            "posted_at": now.date().isoformat(),
                            "origin": "automatic",
                        }],
                    },
                    evidence_urls=[f"https://www.tiktok.com/@{FIXTURE_TAG}"],
                ),
                ToolFinding(
                    entity_type="social_account",
                    platform="youtube",
                    value="https://www.youtube.com/@" + FIXTURE_TAG,
                    metadata_info={
                        "username": FIXTURE_TAG,
                        "source_tool": "controlled_fixture",
                    },
                    evidence_urls=["https://www.youtube.com/@" + FIXTURE_TAG + "_rejected"],
                ),
                ToolFinding(
                    entity_type="social_account",
                    platform="github",
                    value="https://github.com/" + FIXTURE_TAG,
                    metadata_info={
                        "username": FIXTURE_TAG,
                        "source_tool": "controlled_fixture",
                    },
                    evidence_urls=["https://github.com/" + FIXTURE_TAG],
                ),
                ToolFinding(
                    entity_type="breach",
                    platform="data_leak",
                    value=f"{FIXTURE_TAG}@example.org",
                    metadata_info={
                        "email": f"{FIXTURE_TAG}@example.org",
                        "breaches": ["Controlled Exposure Fixture"],
                        "source_tool": "controlled_fixture",
                    },
                    evidence_urls=["https://example.org/controlled-breach-fixture"],
                ),
            ]
            entities = await persist_findings(str(investigation.id), findings, target, db)
            await db.commit()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://exposure-lite-smoke",
        ) as client:
            prefix = f"/api/v1/investigations/{investigation_id}"
            review_response = await client.get(prefix + "/review")
            assert review_response.status_code == 200, review_response.text
            review_ids = {candidate["id"] for candidate in review_response.json()["candidates"]}
            decisions = (
                (str(entities[1].id), "confirmed"),
                (str(entities[2].id), "rejected"),
                (str(entities[3].id), "uncertain"),
            )
            assert all(entity_id in review_ids for entity_id, _ in decisions)
            for entity_id, decision in decisions:
                response = await client.patch(
                    prefix + "/review/" + entity_id,
                    json={"decision": decision},
                )
                assert response.status_code == 200, response.text

            finalized = await client.post(prefix + "/review/finalize")
            assert finalized.status_code == 200, finalized.text
            dataset_response = await client.get(prefix + "/reviewed-footprint")
            assert dataset_response.status_code == 200, dataset_response.text
            dataset = ReviewedFootprintDataset.model_validate(dataset_response.json())
            eligible_accounts = [item for item in dataset.accounts if _is_attributed(item)]
            cache_hashes = {_unit_hash(item) for item in _units(dataset, eligible_accounts)}

            report_response = await client.post(prefix + "/exposure/analyze")
            assert report_response.status_code == 200, report_response.text
            report = report_response.json()
            assert report["status"] == "completed", report
            assert report["categories"]["alias_reuse"] >= 1, report["categories"]
            assert report["categories"]["content_disclosure"] >= 1, report["categories"]
            assert report["categories"]["breach_exposure"] >= 1, report["categories"]
            assert any("contraseñas únicas" in action
                       for finding in report["findings"]
                       for action in finding["recommendations"])
            alias_finding = next(item for item in report["findings"] if item["category"] == "alias_reuse")
            assert "2 plataformas atribuidas" in alias_finding["summary"]
            serialized = str(report)
            assert str(entities[2].id) not in serialized
            assert str(entities[3].id) not in serialized
            assert report["categories"]["education_work_context"] >= 1
            assert report["categories"]["location_disclosure"] >= 1
            assert report["categories"]["temporal_exposure"] >= 1
            assert "Universidad del Norte" in serialized
            for forbidden in ("lupus", "08:10", "Calle Olivos 123", "todos los martes"):
                assert forbidden not in serialized
            async with factory() as db:
                saved = (await db.scalars(select(ExposureRun).where(
                    ExposureRun.investigation_id == investigation_id
                ))).one()
                caches = (await db.scalars(select(ExposureContentCache).where(
                    ExposureContentCache.content_hash.in_(cache_hashes)
                ))).all()
                persisted = str([saved.findings, saved.top_exposures, *[c.result for c in caches]])
                for forbidden in ("lupus", "08:10", "Calle Olivos 123", "todos los martes"):
                    assert forbidden not in persisted

        async with factory() as db:
            fixture_cache = (await db.scalars(select(ExposureContentCache).where(
                ExposureContentCache.content_hash.in_(cache_hashes)
            ))).all() if cache_hashes else []
            if fixture_cache:
                await db.execute(delete(ExposureContentCache).where(
                    ExposureContentCache.id.in_([item.id for item in fixture_cache])
                ))
            await db.commit()
        print(
            "SMOKE OK: Target → Fair review → finalized footprint → alias/content/breach findings; "
            "rejected and uncertain accounts excluded."
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
        if target_id is not None:
            async with factory() as db:
                await db.execute(delete(Target).where(Target.id == target_id))
                await db.commit()
                remaining_runs = (await db.scalars(
                    select(ExposureRun).where(ExposureRun.investigation_id == investigation_id)
                )).all()
                assert not remaining_runs
                remaining_decisions = (await db.scalars(
                    select(ReviewDecision).where(ReviewDecision.investigation_id == investigation_id)
                )).all()
                assert not remaining_decisions
        if cache_hashes:
            async with factory() as db:
                await db.execute(delete(ExposureContentCache).where(
                    ExposureContentCache.content_hash.in_(cache_hashes)
                ))
                await db.commit()
        await engine.dispose()


def _database_dependency(factory):
    async def dependency():
        async with factory() as db:
            yield db
    return dependency


if __name__ == "__main__":
    asyncio.run(run_smoke())
