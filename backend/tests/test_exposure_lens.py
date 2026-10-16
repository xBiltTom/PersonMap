"""PostgreSQL/REST coverage; set EXPOSURE_LENS_TEST_DATABASE_URL to personmap_lite."""

import json
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
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import get_db
from app.models.entity import Entity
from app.models.exposure_run import ExposureContentCache, ExposureRun
from app.models.investigation import Investigation
from app.models.relationship import Relationship
from app.models.review_decision import ReviewDecision
from app.models.target import Target
from app.schemas.target import TargetCreate

pytestmark = pytest.mark.db


def _provenance(status: str) -> dict:
    return {
        "origin": "automatic",
        "status": status,
        "subject_asserted": status == "confirmed",
        "evidence_urls": [],
        "matches_declared_identifier": False,
    }


@pytest_asyncio.fixture
async def exposure_workspace(monkeypatch):
    database_url = os.getenv("EXPOSURE_LENS_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("Configura EXPOSURE_LENS_TEST_DATABASE_URL con la base Lite.")
    parsed_url = make_url(database_url)
    if parsed_url.database != "personmap_lite":
        raise RuntimeError("Exposure Lens DB tests only run against personmap_lite.")

    monkeypatch.setattr(settings, "exposure_ai_enabled", False)
    schema = "exposure_" + uuid.uuid4().hex
    bootstrap = create_async_engine(database_url, poolclass=NullPool)
    async with bootstrap.begin() as connection:
        actual_database = (await connection.execute(text("SELECT current_database()"))).scalar_one()
        if actual_database != "personmap_lite":
            raise RuntimeError("Connected database is not personmap_lite.")
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))

    def migrate(connection):
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    async with engine.begin() as connection:
        await connection.run_sync(migrate)

    payload = TargetCreate(
        input_version=2,
        given_names="Lite",
        family_names="Subject",
        emails=["lite@example.org"],
        usernames=[{"username": "lens_shared", "platform": "instagram"}],
    )
    target = Target(**payload.persistence_values())
    target.extra_data["subject_consent"] = True
    now = datetime.now(timezone.utc)
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

    async with factory() as db:
        db.add(investigation)
        await db.flush()

        declared = Entity(
            investigation_id=investigation.id,
            entity_type="social_account",
            platform="instagram",
            value="https://www.instagram.com/lens_shared/",
            display_name="Lite Subject",
            source_tool="controlled_fixture",
            metadata_info={
                "username": "lens_shared",
                "bio": "Contact lite@example.org · https://www.tiktok.com/@lens_shared",
                "profile_url": "https://www.instagram.com/lens_shared/",
                "source_tool": "controlled_fixture",
                "provenance": _provenance("discovered"),
                "evidence_urls": ["https://www.instagram.com/lens_shared/"],
            },
        )
        confirmed = Entity(
            investigation_id=investigation.id,
            entity_type="social_account",
            platform="tiktok",
            value="https://www.tiktok.com/@lens_shared",
            display_name="Lite Subject",
            source_tool="controlled_fixture",
            metadata_info={
                "username": "lens_shared",
                "bio": "Contact lite@example.org · https://www.instagram.com/lens_shared/",
                "profile_url": "https://www.tiktok.com/@lens_shared",
                "source_tool": "controlled_fixture",
                "provenance": _provenance("confirmed"),
                "evidence_urls": ["https://www.tiktok.com/@lens_shared"],
                "public_content": [
                    {
                        "id": "lite-post-context",
                        "url": "https://www.tiktok.com/@lens_shared/video/lite-context",
                        "caption": "Visiting Lima tomorrow for Universidad del Norte. Contact lite@example.org. Every Tuesday at 8.",
                        "posted_at": "2026-10-01T17:32:00Z",
                        "origin": "automatic",
                    },
                    {
                        "id": "lite-post-address",
                        "url": "https://www.tiktok.com/@lens_shared/video/lite-address",
                        "caption": "Meet me at Av. Los Olivos 123, every Tuesday at 8.",
                        "posted_at": "2026-10-02T17:32:00Z",
                        "origin": "automatic",
                    },
                ],
            },
        )
        rejected = Entity(
            investigation_id=investigation.id,
            entity_type="social_account",
            platform="youtube",
            value="https://www.youtube.com/@lens_shared",
            display_name="Rejected profile",
            source_tool="controlled_fixture",
            metadata_info={
                "username": "lens_shared",
                "bio": "Av. Los Olivos 123 · every Tuesday at 8 · public-rejected@example.net",
                "provenance": _provenance("rejected"),
                "evidence_urls": ["https://www.youtube.com/@lens_rejected"],
            },
        )
        uncertain = Entity(
            investigation_id=investigation.id,
            entity_type="social_account",
            platform="github",
            value="https://github.com/lens_shared",
            display_name="Uncertain profile",
            source_tool="controlled_fixture",
            metadata_info={
                "username": "lens_shared",
                "bio": "public-uncertain@example.net",
                "provenance": _provenance("uncertain"),
                "evidence_urls": ["https://github.com/lens_uncertain"],
            },
        )
        academic_profile = Entity(
            investigation_id=investigation.id,
            entity_type="academic",
            platform="openalex_author",
            value="https://openalex.org/A123",
            display_name="Lite Subject",
            source_tool="controlled_fixture",
            metadata_info={
                "source_tool": "controlled_fixture",
                "provenance": _provenance("confirmed"),
                "evidence_urls": ["https://openalex.org/A123"],
            },
        )
        paper = Entity(
            investigation_id=investigation.id,
            entity_type="academic",
            platform="research_paper",
            value="Public research at Universidad del Norte",
            display_name="Lite public paper",
            source_tool="controlled_fixture",
            metadata_info={
                "source_tool": "controlled_fixture",
                "evidence_urls": ["https://example.org/lite-paper.pdf"],
            },
        )
        breach = Entity(
            investigation_id=investigation.id,
            entity_type="breach",
            platform="data_leak",
            value="lite@example.org",
            source_tool="controlled_fixture",
            metadata_info={
                "email": "lite@example.org",
                "breaches": ["Controlled Breach 2025"],
                "evidence_urls": ["https://example.org/breach-record"],
            },
        )
        db.add_all([declared, confirmed, rejected, uncertain, academic_profile, paper, breach])
        await db.flush()
        db.add(Relationship(
            investigation_id=investigation.id,
            source_entity_id=academic_profile.id,
            target_entity_id=paper.id,
            relation_type="authored_work",
            supports_group=False,
            evidence={"source": "controlled_fixture"},
        ))
        db.add_all([
            ReviewDecision(investigation_id=investigation.id, entity_id=confirmed.id, decision="confirmed",
                           decided_at=now, history=[]),
            ReviewDecision(investigation_id=investigation.id, entity_id=rejected.id, decision="rejected",
                           decided_at=now, history=[]),
            ReviewDecision(investigation_id=investigation.id, entity_id=uncertain.id, decision="uncertain",
                           decided_at=now, history=[]),
            ReviewDecision(investigation_id=investigation.id, entity_id=academic_profile.id, decision="confirmed",
                           decided_at=now, history=[]),
        ])
        await db.commit()
        workspace = {
            "investigation_id": investigation.id,
            "target_id": target.id,
            "confirmed_id": confirmed.id,
            "rejected_id": rejected.id,
            "uncertain_id": uncertain.id,
            "declared_id": declared.id,
            "factory": factory,
            "engine": engine,
            "bootstrap": bootstrap,
            "schema": schema,
        }

    from app.main import app

    async def get_test_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://exposure-lite-test",
        ) as client:
            workspace["client"] = client
            yield workspace
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
        async with bootstrap.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap.dispose()


async def _finalize(workspace):
    response = await workspace["client"].post(
        f"/api/v1/investigations/{workspace['investigation_id']}/review/finalize"
    )
    assert response.status_code == 200, response.text
    return response


@pytest.mark.asyncio
async def test_exposure_requires_finalized_verification_gate(exposure_workspace):
    workspace = exposure_workspace
    response = await workspace["client"].post(
        f"/api/v1/investigations/{workspace['investigation_id']}/exposure/analyze"
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "review_not_finalized"


@pytest.mark.asyncio
async def test_confirmed_only_categories_breach_documents_recommendations_and_cache(exposure_workspace):
    workspace = exposure_workspace
    await _finalize(workspace)
    base = f"/api/v1/investigations/{workspace['investigation_id']}/exposure"
    analyzed = await workspace["client"].post(base + "/analyze")
    assert analyzed.status_code == 200, analyzed.text
    report = analyzed.json()

    assert report["status"] == "completed"
    assert report["dataset_hash"] and report["summary"]["high"] >= 1
    assert report["categories"]["alias_reuse"] == 1
    assert report["categories"]["cross_platform_correlation"] >= 1
    assert report["categories"]["contact_exposure"] >= 1
    assert report["categories"]["breach_exposure"] == 1
    assert report["categories"]["public_documents"] == 1
    assert report["categories"]["content_disclosure"] >= 1
    assert report["categories"]["location_disclosure"] >= 1
    assert report["categories"]["temporal_exposure"] >= 1
    assert report["categories"]["education_work_context"] >= 1
    assert report["analyzed_content_count"] >= 3
    assert any("contraseñas únicas" in recommendation
               for finding in report["findings"]
               for recommendation in finding["recommendations"])

    serialized = json.dumps(report, ensure_ascii=False)
    assert str(workspace["rejected_id"]) not in serialized
    assert str(workspace["uncertain_id"]) not in serialized
    assert "public-rejected@example.net" not in serialized
    assert "public-uncertain@example.net" not in serialized
    alias = next(item for item in report["findings"] if item["category"] == "alias_reuse")
    assert "2 plataformas atribuidas" in alias["summary"]
    assert {item["platform"] for item in alias["evidence"]} == {"instagram", "tiktok"}
    assert "Los Olivos 123" not in serialized and "Av." not in serialized
    assert "Tuesday at 8" not in serialized
    assert "politic" not in serialized.lower()
    assert "identity confidence" not in serialized.lower()

    cached = await workspace["client"].post(base + "/analyze")
    assert cached.status_code == 200
    assert cached.json()["cache_hit"] is True
    restored = await workspace["client"].get(base)
    assert restored.status_code == 200 and restored.json()["dataset_hash"] == report["dataset_hash"]
    async with workspace["factory"]() as db:
        runs = (await db.scalars(select(ExposureRun))).all()
        cache = (await db.scalars(select(ExposureContentCache))).all()
        assert len(runs) == 1
        assert len(cache) >= 1


@pytest.mark.asyncio
async def test_dataset_change_marks_saved_report_stale(exposure_workspace):
    workspace = exposure_workspace
    await _finalize(workspace)
    path = f"/api/v1/investigations/{workspace['investigation_id']}/exposure"
    old = await workspace["client"].post(path + "/analyze")
    assert old.status_code == 200
    old_hash = old.json()["dataset_hash"]

    changed = await workspace["client"].patch(
        f"/api/v1/investigations/{workspace['investigation_id']}/review/{workspace['confirmed_id']}",
        json={"decision": "rejected"},
    )
    assert changed.status_code == 200
    await _finalize(workspace)
    latest = await workspace["client"].get(path)
    assert latest.status_code == 200
    assert latest.json()["stale"] is True
    assert latest.json()["dataset_hash"] == old_hash
    assert latest.json()["current_dataset_hash"] != old_hash


@pytest.mark.asyncio
async def test_ai_failure_keeps_deterministic_findings_and_returns_partial(exposure_workspace, monkeypatch):
    from app.services import exposure_lens

    workspace = exposure_workspace
    await _finalize(workspace)
    monkeypatch.setattr(settings, "exposure_ai_enabled", True)
    monkeypatch.setattr(settings, "exposure_ai_model", "fixture/exposure-model")

    async def fail_classifier(*args, **kwargs):
        raise RuntimeError("controlled model failure")

    monkeypatch.setattr(exposure_lens.exposure_ai, "classify_batch", fail_classifier)
    response = await workspace["client"].post(
        f"/api/v1/investigations/{workspace['investigation_id']}/exposure/analyze"
    )
    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "partial"
    assert report["partial_reasons"] == ["ai_failure"]
    assert report["categories"]["alias_reuse"] == 1
    assert report["categories"]["breach_exposure"] == 1
    async with workspace["factory"]() as db:
        assert not (await db.scalars(select(ExposureContentCache))).all()


@pytest.mark.asyncio
async def test_partial_fair_source_coverage_is_not_presented_as_complete(exposure_workspace):
    workspace = exposure_workspace
    async with workspace["factory"]() as db:
        investigation = await db.get(Investigation, workspace["investigation_id"])
        metrics = dict(investigation.metrics)
        snapshot = dict(metrics["fair_snapshot"])
        snapshot["execution"] = {**snapshot["execution"], "partial": True}
        metrics["fair_snapshot"] = snapshot
        investigation.metrics = metrics
        await db.commit()

    await _finalize(workspace)
    response = await workspace["client"].post(
        f"/api/v1/investigations/{workspace['investigation_id']}/exposure/analyze"
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "partial"
    assert report["partial_reasons"] == ["acquisition_partial"]
    restored = await workspace["client"].get(
        f"/api/v1/investigations/{workspace['investigation_id']}/exposure"
    )
    assert restored.json()["partial_reasons"] == ["acquisition_partial"]


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['active', 'abandoned', 'failed'])
async def test_running_lease_and_failed_retry(exposure_workspace, monkeypatch, state):
    from datetime import timedelta
    from app.services import exposure_lens
    ws = exposure_workspace
    await _finalize(ws)
    path = f"/api/v1/investigations/{ws['investigation_id']}/exposure"
    assert (await ws['client'].post(path + '/analyze')).status_code == 200
    async with ws['factory']() as db:
        run = (await db.scalars(select(ExposureRun))).one()
        run_id = run.id
        run.status = 'failed' if state == 'failed' else 'running'
        run.started_at = datetime.now(timezone.utc) - timedelta(
            seconds=settings.exposure_run_lease_seconds + 1 if state == 'abandoned' else 0)
        run.completed_at = None
        cache_ids = (await db.scalars(select(ExposureContentCache.id))).all()
        await db.commit()
    original = exposure_lens._build_analysis
    calls = 0
    async def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)
    monkeypatch.setattr(exposure_lens, '_build_analysis', counted)
    observed = await ws['client'].get(path)
    assert observed.json()['status'] == ('failed' if state in {'abandoned', 'failed'} else 'running')
    assert calls == 0
    response = await ws['client'].post(path + '/analyze')
    assert response.status_code == 200, response.text
    assert response.json()['status'] == ('running' if state == 'active' else 'completed')
    assert calls == (0 if state == 'active' else 1)
    async with ws['factory']() as db:
        runs = (await db.scalars(select(ExposureRun))).all()
        assert [r.id for r in runs] == [run_id]
        assert set((await db.scalars(select(ExposureContentCache.id))).all()) == set(cache_ids)
    if state != 'active':
        assert response.json()['cache_hit'] is True


@pytest.mark.asyncio
async def test_concurrent_post_claims_one_analysis(exposure_workspace, monkeypatch):
    import asyncio
    from app.services import exposure_lens
    ws = exposure_workspace
    await _finalize(ws)
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0
    original = exposure_lens._build_analysis
    async def blocked(*args, **kwargs):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(exposure_lens, '_build_analysis', blocked)
    path = f"/api/v1/investigations/{ws['investigation_id']}/exposure/analyze"
    async def follower():
        await asyncio.wait_for(started.wait(), 10)
        try:
            response = await asyncio.wait_for(ws['client'].post(path), 10)
            assert response.status_code == 200, response.text
            assert response.json()['status'] == 'running'
            return response
        finally:
            release.set()
    first, second = await asyncio.gather(ws['client'].post(path), follower())
    assert first.status_code == second.status_code == 200
    assert calls == 1
    async with ws['factory']() as db:
        assert len((await db.scalars(select(ExposureRun))).all()) == 1


@pytest.mark.asyncio
async def test_analysis_exception_is_failed_then_retryable(exposure_workspace, monkeypatch):
    from app.services import exposure_lens
    ws = exposure_workspace
    await _finalize(ws)
    original = exposure_lens._build_analysis
    async def broken(*args, **kwargs):
        raise RuntimeError('controlled failure')
    monkeypatch.setattr(exposure_lens, '_build_analysis', broken)
    path = f"/api/v1/investigations/{ws['investigation_id']}/exposure/analyze"
    with pytest.raises(RuntimeError, match='controlled failure'):
        await ws['client'].post(path)
    async with ws['factory']() as db:
        run = (await db.scalars(select(ExposureRun))).one()
        run_id = run.id
        assert run.status == 'failed' and run.completed_at is not None
    monkeypatch.setattr(exposure_lens, '_build_analysis', original)
    assert (await ws['client'].post(path)).json()['status'] == 'completed'
    async with ws['factory']() as db:
        assert [r.id for r in (await db.scalars(select(ExposureRun))).all()] == [run_id]


@pytest.mark.asyncio
async def test_ai_excerpts_are_rebuilt_before_cache_and_persistence(exposure_workspace, monkeypatch):
    from app.services import exposure_lens
    ws = exposure_workspace
    await _finalize(ws)
    monkeypatch.setattr(settings, 'exposure_ai_enabled', True)
    monkeypatch.setattr(settings, 'exposure_ai_model', 'fixture/model')
    async def classifier(model, items, **kwargs):
        return {item['content_id']: [{
            'category': 'biographical_identifiers', 'severity': 'high',
            'evidence_excerpt': 'Tengo lupus y soy adventista; Calle Olivos 123 a las 08:10',
        }] for item in items}
    monkeypatch.setattr(exposure_lens.exposure_ai, 'classify_batch', classifier)
    path = f"/api/v1/investigations/{ws['investigation_id']}/exposure/analyze"
    response = await ws['client'].post(path)
    assert response.status_code == 200, response.text
    report = response.json()
    assert all(f['severity'] == 'low' for f in report['findings']
               if f['analysis_method'] == 'ai' and f['category'] == 'biographical_identifiers')
    async with ws['factory']() as db:
        run = (await db.scalars(select(ExposureRun))).one()
        caches = (await db.scalars(select(ExposureContentCache))).all()
        persisted = json.dumps([run.findings, run.top_exposures, *[c.result for c in caches]])
        for forbidden in ('lupus', 'adventista', 'Olivos 123', '08:10'):
            assert forbidden not in persisted


@pytest.mark.asyncio
@pytest.mark.parametrize("old_fails", [False, True])
async def test_expired_worker_cannot_overwrite_replacement(exposure_workspace, monkeypatch, old_fails):
    import asyncio
    from datetime import timedelta
    from app.services import exposure_lens
    ws = exposure_workspace
    await _finalize(ws)
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0
    original = exposure_lens._build_analysis
    async def blocked(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            if old_fails:
                raise RuntimeError('expired worker')
        return await original(*args, **kwargs)
    monkeypatch.setattr(exposure_lens, '_build_analysis', blocked)
    path = f"/api/v1/investigations/{ws['investigation_id']}/exposure/analyze"
    first = asyncio.create_task(ws['client'].post(path))
    try:
        await asyncio.wait_for(started.wait(), 10)
        async with ws['factory']() as db:
            run = (await db.scalars(select(ExposureRun))).one()
            run.started_at -= timedelta(seconds=settings.exposure_run_lease_seconds + 1)
            await db.commit()
        second = await ws['client'].post(path)
        assert second.status_code == 200 and second.json()['status'] == 'completed'
    finally:
        release.set()
        if old_fails:
            with pytest.raises(RuntimeError, match='expired worker'):
                await first
        else:
            assert (await first).json()['status'] == 'completed'
    async with ws['factory']() as db:
        assert (await db.scalars(select(ExposureRun))).one().status == 'completed'


@pytest.mark.asyncio
async def test_partial_ai_failure_is_retryable_on_the_same_run(exposure_workspace, monkeypatch):
    from app.exposure import ai as exposure_ai
    ws = exposure_workspace
    await _finalize(ws)
    monkeypatch.setattr(settings, 'exposure_ai_enabled', True)
    monkeypatch.setattr(settings, 'exposure_ai_model', 'fixture/model')
    attempts = []
    async def classify(model, items, **kwargs):
        attempts.append(len(items))
        if len(attempts) == 1:
            raise ValueError('synthetic failure')
        return {item['content_id']: [] for item in items}
    monkeypatch.setattr(exposure_ai, 'classify_batch', classify)
    path = f"/api/v1/investigations/{ws['investigation_id']}/exposure/analyze"
    first = (await ws['client'].post(path)).json()
    assert 'ai_failure' in first['partial_reasons']
    second = (await ws['client'].post(path)).json()
    assert 'ai_failure' not in second['partial_reasons']
    assert second['config']['ai_processing']['processed'] > 0
    async with ws['factory']() as db:
        rows = (await db.scalars(select(ExposureRun).where(ExposureRun.investigation_id == ws['investigation_id']))).all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_ai_retry_reuses_successful_batches(exposure_workspace, monkeypatch):
    from app.exposure import ai as exposure_ai
    ws = exposure_workspace
    await _finalize(ws)
    monkeypatch.setattr(settings, 'exposure_ai_enabled', True)
    monkeypatch.setattr(settings, 'exposure_ai_model', 'fixture/model')
    monkeypatch.setattr(settings, 'exposure_batch_size', 1)
    calls = []
    async def classify(model, items, **kwargs):
        calls.append(items[0]['content_id'])
        if len(calls) == 1:
            raise ValueError('synthetic one-batch failure')
        return {item['content_id']: [] for item in items}
    monkeypatch.setattr(exposure_ai, 'classify_batch', classify)
    path = f"/api/v1/investigations/{ws['investigation_id']}/exposure/analyze"
    first = (await ws['client'].post(path)).json()
    count = len(calls)
    assert first['config']['ai_processing']['failed_batches'] == 1
    second = (await ws['client'].post(path)).json()
    assert len(calls) == count + 1
    assert 'ai_failure' not in second['partial_reasons']
    assert second['config']['ai_processing']['cached'] > 0
