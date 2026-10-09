"""Real PostgreSQL migrations and MCP/REST interoperability in a disposable schema.

Run explicitly: .venv/bin/python -m pytest tests/test_mcp_workspace_db.py -m db -q
No external OSINT requests; tools use controlled fixtures. Existing dossiers are untouched.
"""
import asyncio
import json
import uuid
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import get_db
from app.core.events import event_bus
from app.models.entity import Entity
from app.models.entity_observation import EntityObservation
from app.models.investigation import Investigation
from app.models.investigation_session import InvestigationSession
from app.models.tool_execution import ToolExecution
from app.schemas.investigation import InvestigationCreate
from app.schemas.target import TargetCreate
from app.schemas.workspace import NoteCreate, SearchQuery, SessionCreate, ToolInputs, ToolRequest
from app.services.workspace import EXTERNAL_TOOLS, WorkspaceService
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding

pytestmark = pytest.mark.db


@pytest_asyncio.fixture
async def isolated_workspace(monkeypatch):
    schema = "mcp_test_" + uuid.uuid4().hex
    bootstrap = create_async_engine(settings.database_url, poolclass=NullPool, connect_args={"timeout": 5})
    async with bootstrap.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(settings.database_url, poolclass=NullPool,
                                connect_args={"timeout": 5, "server_settings": {"search_path": schema}})
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))

    def migrate(conn, revision):
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, revision)

    service = WorkspaceService(async_sessionmaker(engine, expire_on_commit=False))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(migrate, "bc71a90de452")
            target_id, inv_id = uuid.uuid4(), uuid.uuid4()
            await conn.execute(text("INSERT INTO targets (id, username, created_at) VALUES (:id, 'legacy', now())"), {"id": target_id})
            await conn.execute(text("INSERT INTO investigations (id, target_id, strategy, status, created_at) VALUES (:id, :target, 'rule_based', 'pending', now())"), {"id": inv_id, "target": target_id})
            await conn.run_sync(migrate, "head")
        monkeypatch.setattr(settings, "mcp_api_key", SecretStr("integration-token"))
        monkeypatch.setattr(settings, "mcp_enabled", True)
        yield service, inv_id
    finally:
        await service.shutdown()
        await engine.dispose()
        async with bootstrap.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap.dispose()


class FixtureTool(BaseTool):
    name = "username_finder"
    description = "Controlled username fixture"
    category = ToolCategory.USERNAME
    required_inputs = ["username"]

    async def execute(self, context: TargetContext):
        if context.extra.get("username_finder_fixture_scanned"):
            return []
        context.extra["username_finder_fixture_scanned"] = True
        return [ToolFinding(entity_type="social_account", platform="github", value="https://github.com/fixture",
                            metadata_info={"username": "fixture", "bio": "Public fixture biography"},
                            evidence_urls=["https://example.test/source"])]


@pytest.mark.asyncio
async def test_mcp_results_notes_and_sessions_are_visible_in_web_api(isolated_workspace, monkeypatch):
    import app.api.v1.investigations as investigations_api
    import app.api.v1.workspace as notes_api
    import app.mcp.server as mcp_module
    import app.main as main
    import app.api.v1.stream as stream_api
    from app.api.v1.metrics import engine_of

    service, legacy_id = isolated_workspace
    async with service.session_factory() as db:
        legacy = await db.get(Investigation, legacy_id)
        assert legacy.execution_mode == "internal" and legacy.revision == 0
    monkeypatch.setattr(mcp_module, "workspace", service)
    monkeypatch.setattr(investigations_api, "workspace", service)
    monkeypatch.setattr(notes_api, "workspace", service)
    monkeypatch.setattr(stream_api, "async_session_maker", service.session_factory)
    monkeypatch.setitem(EXTERNAL_TOOLS, "username_finder", FixtureTool())
    async def get_test_db():
        async with service.session_factory() as db:
            yield db
    main.app.dependency_overrides[get_db] = get_test_db

    try:
        async with mcp_module.mcp.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://127.0.0.1:8000",
                headers={"Authorization": "Bearer integration-token", "Accept": "application/json, text/event-stream"}) as client:
                counter = 0
                async def call(name, arguments):
                    nonlocal counter
                    counter += 1
                    response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": counter, "method": "tools/call",
                                                              "params": {"name": name, "arguments": arguments}})
                    assert response.status_code == 200, response.text
                    result = response.json()["result"]
                    assert not result.get("isError"), result
                    return result["structuredContent"]

                created = await call("create_investigation", {"target": {"username": "fixture"}})
                inv_id = created["id"]
                assert created["execution_mode"] == "external" and created["status"] == "pending"
                assert created["web_url"].endswith(inv_id)
                session = await call("open_session", {"investigation_id": inv_id, "client": "codex-fixture", "model": "declared-test-model"})
                args = {"investigation_id": inv_id, "session_id": session["id"], "inputs": {"username": "fixture"}, "rationale": "Verify public candidate"}
                execution = await call("username_finder", args)
                await service.tasks[uuid.UUID(execution["id"])]
                status = await call("get_execution", {"investigation_id": inv_id, "execution_id": execution["id"]})
                assert status["status"] == "completed" and len(status["entity_ids"]) == 1
                entity_id = status["entity_ids"][0]
                reused = await call("username_finder", args)
                assert reused["id"] == execution["id"] and reused["reused"] is True
                refreshed = await call("username_finder", {**args, "force": True})
                await service.tasks[uuid.UUID(refreshed["id"])]
                async with service.session_factory() as db:
                    entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == uuid.UUID(inv_id)))).all())
                    observations = list((await db.scalars(select(EntityObservation).where(EntityObservation.investigation_id == uuid.UUID(inv_id)))).all())
                    assert len(entities) == 1 and str(entities[0].id) == entity_id and len(observations) == 2

                note = await call("add_analysis_note", {"investigation_id": inv_id, "session_id": session["id"],
                    "note": {"kind": "insight", "title": "Evidence worth reviewing", "content": "A public biography gives a useful next step.",
                             "entity_ids": [entity_id], "execution_ids": [execution["id"]], "evidence_urls": ["https://example.test/source"],
                             "details": {"next_question": "Does the public profile link another account?"}}})
                assert note["author"] == "codex-fixture" and note["author_type"] == "agent"
                web = (await client.get(f"/api/v1/investigations/{inv_id}")).json()
                assert len(web["entities"]) == 1 and web["analysis_notes"][0]["id"] == note["id"]
                assert web["revision"] >= 5 and web["sessions"][0]["model"] == "declared-test-model"
                graph = (await client.get(f"/api/v1/investigations/{inv_id}/graph")).json()
                assert len(graph["nodes"]) == 2
                trace = (await client.get(f"/api/v1/investigations/{inv_id}/trace")).json()
                assert len(trace["observations"]) == 2
                assert all(item["session_id"] == session["id"] for item in trace["executions"])
                analyst = await client.post(f"/api/v1/investigations/{inv_id}/notes", json={"title": "Human review", "content": "Review recorded."})
                assert analyst.status_code == 201 and analyst.json()["author_type"] == "analyst"
                await call("finish_session", {"investigation_id": inv_id, "session_id": session["id"], "summary": "Authored summary with public evidence."})
                completed = (await client.get(f"/api/v1/investigations/{inv_id}")).json()
                assert completed["status"] == "completed" and completed["metrics"]["engine_used"] == "external"
                assert completed["summary"] == "Authored summary with public evidence."
                assert completed["metrics"]["external_sessions"] == 1
                assert 0 <= completed["metrics"]["execution_time_seconds"] <= completed["metrics"]["elapsed_wall_seconds"]
                async with service.session_factory() as db:
                    assert engine_of(await db.get(Investigation, uuid.UUID(inv_id))) == "external"

                # A completed external dossier stays subscribed: a new session can update an open web page.
                streamed = await stream_api.stream_investigation_events(uuid.UUID(inv_id))
                generator = streamed.body_iterator
                assert '"connected"' in await anext(generator)
                assert '"workspace_snapshot"' in await anext(generator)
                for _ in range(len(event_bus.get_history(inv_id))):
                    await anext(generator)
                continued = await call("open_session", {"investigation_id": inv_id, "client": "claude-fixture"})
                assert continued["id"] != session["id"]
                assert '"session_start"' in await asyncio.wait_for(anext(generator), timeout=2)
                await generator.aclose()
                await call("pause_session", {"investigation_id": inv_id, "session_id": continued["id"]})
                reopened = await call("get_investigation_context", {"investigation_id": inv_id})
                assert reopened["total_findings"] == 1 and len(reopened["notes"]) == 3
                assert reopened["investigation"]["status"] == "paused"
                assert reopened["investigation"]["metrics"]["external_sessions"] == 2
    finally:
        main.app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_session_conflicts_reference_isolation_and_restart_recovery(isolated_workspace, monkeypatch):
    from fastapi import HTTPException
    service, _ = isolated_workspace
    async with service.session_factory() as db:
        one = await service.create(InvestigationCreate(target=TargetCreate(username="one"), execution_mode="external"), db)
        two = await service.create(InvestigationCreate(target=TargetCreate(username="two"), execution_mode="external"), db)
    session = await service.open_session(one.id, SessionCreate(client="codex"))
    with pytest.raises(HTTPException) as conflict:
        await service.open_session(one.id, SessionCreate(client="claude"))
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException) as missing:
        await service.add_note(one.id, NoteCreate(title="Invalid reference", content="Must not cross dossiers.", entity_ids=[uuid.uuid4()]), uuid.UUID(session["id"]))
    assert missing.value.status_code == 422
    with pytest.raises(HTTPException) as cross:
        await service.submit_tool(two.id, uuid.UUID(session["id"]), ToolRequest(tool_name="username_finder"))
    assert cross.value.status_code == 404

    class SlowTool(FixtureTool):
        async def execute(self, context):
            await asyncio.Event().wait()
    monkeypatch.setitem(EXTERNAL_TOOLS, "username_finder", SlowTool())
    execution = await service.submit_tool(one.id, uuid.UUID(session["id"]), ToolRequest(tool_name="username_finder"))
    with pytest.raises(HTTPException) as busy:
        await service.close_session(one.id, uuid.UUID(session["id"]), "finish")
    assert busy.value.status_code == 409
    await asyncio.sleep(0)  # Allow the background coroutine to enter its cancellation handler.
    await service.shutdown()
    persisted = await service.execution(one.id, uuid.UUID(execution["id"]))
    assert persisted["status"] == "failed" and persisted["completed_at"]
    async with service.session_factory() as db:
        assert (await db.get(Investigation, one.id)).status == "paused"
        assert (await db.get(InvestigationSession, uuid.UUID(session["id"]))).status == "paused"
    assert (await service.open_session(one.id, SessionCreate(client="codex")))["id"] != session["id"]


@pytest.mark.asyncio
async def test_parallel_batch_preserves_evidence_runtime_and_web_state(isolated_workspace, monkeypatch):
    from fastapi import HTTPException
    service, _ = isolated_workspace
    monkeypatch.setattr(settings, "mcp_max_parallel_tools", 3)
    async with service.session_factory() as db:
        inv = await service.create(InvestigationCreate(target=TargetCreate(username="fixture"), execution_mode="external"), db)
    session = await service.open_session(inv.id, SessionCreate(client="codex"))
    session_id = uuid.UUID(session["id"])
    release = asyncio.Event()
    ready = asyncio.Event()
    started = set()

    class ConcurrentTool(FixtureTool):
        def __init__(self, name):
            self.name = name
        async def execute(self, context):
            started.add(self.name)
            if len(started) == 3:
                ready.set()
            await release.wait()
            context.extra[f"{self.name}_cache"] = {"done": 1}
            if self.name == "username_finder":
                assert context.extra["username_scan_mode"] == "fast"
                context.extra["username_finder_coverage"] = {"fixture": 2}
                context.extra["username_finder_scanned"] = {"fixture"}
            if self.name == "search_dorker":
                q = context.extra["search_queries"][0]
                assert q["include_domains"] == ["github.com"]
                context.extra["search_queries_executed"] = [[q["query"], q["include_domains"]]]
                context.extra["search_queries_used"] = 1
            return [ToolFinding(entity_type="social_account", platform="github", value="https://github.com/fixture",
                                metadata_info={f"from_{self.name}": True, "page_text": "Captured public body", "page_excerpt": "Public excerpt"},
                                evidence_urls=[f"https://example.test/{self.name}"])]

    for name in ("username_finder", "social_verifier", "search_dorker", "email_checker"):
        monkeypatch.setitem(EXTERNAL_TOOLS, name, ConcurrentTool(name))
    requests = [ToolRequest(tool_name="username_finder"), ToolRequest(tool_name="social_verifier"),
                ToolRequest(tool_name="search_dorker", inputs=ToolInputs(queries=[
                    SearchQuery(query='"fixture" publication', rationale="Follow observed profile", include_domains=["github.com"])]))]
    batch = await service.submit_batch(inv.id, session_id, requests)
    assert all(item["accepted"] for item in batch["results"])
    execution_ids = [uuid.UUID(item["execution"]["id"]) for item in batch["results"]]
    await asyncio.wait_for(ready.wait(), 2)  # All three execute concurrently, not just queued.
    pending = await service.executions(inv.id, execution_ids)
    assert pending["running_count"] == 3
    reused = await service.submit_tool(inv.id, session_id, requests[0])
    assert reused["reused"] and uuid.UUID(reused["id"]) == execution_ids[0]
    rejected = await service.submit_batch(inv.id, session_id, [ToolRequest(tool_name="email_checker")])
    assert rejected["results"][0]["accepted"] is False and rejected["results"][0]["status_code"] == 409
    with pytest.raises(HTTPException) as busy:
        await service.close_session(inv.id, session_id, "finish")
    assert busy.value.status_code == 409
    await service.add_note(inv.id, NoteCreate(title="Work in progress", content="Reviewing evidence while tools run."), session_id)
    waiting = asyncio.create_task(service.executions(inv.id, execution_ids, wait_seconds=2))
    tasks = [service.tasks[execution_id] for execution_id in execution_ids]
    release.set()
    await asyncio.gather(*tasks)
    await waiting
    completed = await service.executions(inv.id, execution_ids)
    assert completed["running_count"] == 0 and all(item["status"] == "completed" for item in completed["executions"])

    web = await service.detail(inv.id)
    assert len(web["entities"]) == 1
    entity = web["entities"][0]
    assert set(entity["metadata_info"]["source_tools"]) == {request.tool_name for request in requests}
    assert len(entity["metadata_info"]["evidence_urls"]) == 3
    assert web["analysis_notes"][0]["title"] == "Work in progress"
    assert web["metrics"]["external_peak_parallel_tools"] == 3
    async with service.session_factory() as db:
        observations = list((await db.scalars(select(EntityObservation).where(EntityObservation.investigation_id == inv.id))).all())
        assert len(observations) == 3 and len({item.entity_id for item in observations}) == 1
    runtime = service.contexts[inv.id].extra
    assert all(runtime[f"{name}_cache"]["done"] == 1 for name in started)
    compact = (await service.findings(inv.id))["findings"][0]["metadata_info"]
    assert "page_text" not in compact and compact["content_available"]
    full = await service.findings(inv.id, entity_id=uuid.UUID(entity["id"]), include_content=True)
    assert full["findings"][0]["metadata_info"]["page_text"] == "Captured public body"
    await service.close_session(inv.id, session_id, "pause")
    service.contexts.clear()  # Simulate losing in-memory caches on restart.
    resumed = await service.context(inv.id)
    assert resumed["scan_coverage"] == {"fixture": 2}
    assert resumed["execution_policy"]["search_queries_remaining"] == settings.tavily_max_queries - 1
    assert not resumed["execution_policy"]["active_tools"]

    # When there is free capacity, overlapping the same tool is still rejected.
    second = await service.open_session(inv.id, SessionCreate(client="codex"))
    release.clear()
    next_job = await service.submit_tool(inv.id, uuid.UUID(second["id"]), ToolRequest(tool_name="username_finder", inputs=ToolInputs(username="another")))
    with pytest.raises(HTTPException) as same_tool:
        await service.submit_tool(inv.id, uuid.UUID(second["id"]), ToolRequest(tool_name="username_finder", inputs=ToolInputs(username="different")))
    assert same_tool.value.status_code == 409
    release.set()
    await service.tasks[uuid.UUID(next_job["id"])]
