"""Repeat an existing database target through the real traditional orchestrator.

Selection/inspection are read-only. Running creates a separate investigation;
reports omit email addresses, phone numbers, DNI and exposure content.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from uuid import UUID

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload
from app.core.config import settings
from app.core.database import engine, async_session_maker
from app.core.events import event_bus
from app.models.entity import Entity
from app.models.investigation import Investigation
from app.models.tool_execution import ToolExecution


async def select_candidates():
    async with asyncio.timeout(15), engine.connect() as connection:
        rows = await connection.execute(text("""
            SELECT i.id::text, i.strategy, i.execution_mode, i.created_at::text,
                   t.full_name, t.username,
                   i.metrics->>'entities_discovered' AS entities,
                   i.metrics->>'execution_time_seconds' AS elapsed,
                   i.metrics->>'engine_used' AS engine_used,
                   (SELECT count(*) FROM entities e WHERE e.investigation_id=i.id
                       AND e.source_tool LIKE '%username_finder') AS finder_entities,
                   (SELECT count(*) FROM entities e WHERE e.investigation_id=i.id
                       AND e.metadata_info->>'verification_status'='verified') AS verified
            FROM investigations i JOIN targets t ON t.id=i.target_id
            WHERE i.status='completed' AND t.username IS NOT NULL
            ORDER BY finder_entities DESC, verified DESC LIMIT 15
        """))
        return [dict(row) for row in rows.mappings()]


async def snapshot(investigation_id):
    async with async_session_maker() as db:
        investigation = await db.scalar(select(Investigation).where(Investigation.id == investigation_id)
                                       .options(selectinload(Investigation.target)))
        if investigation is None:
            raise ValueError("Investigation not found")
        entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == investigation_id))).all())
        executions = list((await db.scalars(select(ToolExecution).where(ToolExecution.investigation_id == investigation_id)
                                           .order_by(ToolExecution.started_at))).all())
        profiles = [entity for entity in entities if entity.entity_type in {"social_account", "sensitive_account"}]
        native = [entity for entity in profiles if (entity.metadata_info or {}).get("search_engine") == "maigret"]
        # Public account URLs only. Never copy the target's contact/identity inputs.
        def account(entity):
            meta = entity.metadata_info or {}
            return {"platform": entity.platform, "url": entity.value,
                    "sources": meta.get("source_tools", [entity.source_tool]),
                    "verification": meta.get("verification_status"),
                    "negative_control": meta.get("negative_control"),
                    "has_bio": bool(meta.get("bio")), "has_avatar": bool(meta.get("avatar_url")),
                    "has_links": bool(meta.get("linked_profiles")),
                    "extractor": (meta.get("maigret_data") or {}).get("_extractor")}
        keys = ("engine_used", "execution_time_seconds", "entities_discovered", "correlation_groups",
                "ai_enhanced", "config_username_scan_engine_version", "config_username_catalog_scanned",
                "config_username_catalog_available", "config_maigret_version", "config_maigret_catalog_sha256",
                "config_catalog_from_maigret", "config_catalog_from_whatsmyname")
        runtime = (investigation.metrics or {}).get("collection_runtime", {})
        runtime = {key: runtime[key] for key in ("username_finder_coverage", "username_finder_scanned",
                    "username_finder_stats", "username_finder_catalog_id", "username_finder_outcomes",
                    "search_queries_used", "maigret_enricher_scanned", "maigret_enricher_parsed",
                    "maigret_enricher_diagnostics", "maigret_enricher_url_attempts") if key in runtime}
        return {"id": str(investigation.id), "status": investigation.status,
                "strategy": investigation.strategy, "username": investigation.target.username,
                "metrics": {key: investigation.metrics.get(key) for key in keys},
                "runtime": runtime,
                "entity_types": dict(Counter(e.entity_type for e in entities)),
                "profiles": [account(e) for e in profiles], "native_profiles": [account(e) for e in native],
                "tools": [{"id": str(e.id), "name": e.tool_name, "status": e.status, "findings": e.findings_count,
                           "round": e.round_index, "elapsed": (e.completed_at-e.started_at).total_seconds() if e.completed_at else None,
                           "error": e.error_summary} for e in executions]}


async def run(source_id, output):
    # This changes only the validation process, never .env or the server.
    settings.llm_model = settings.llm_api_key = None
    from app.engine.orchestrator import orchestrator
    from app.schemas.investigation import InvestigationCreate
    from app.schemas.target import TargetCreate
    from app.services.workspace import workspace
    baseline = await snapshot(source_id)
    async with async_session_maker() as db:
        source = await db.scalar(select(Investigation).where(Investigation.id == source_id)
                                 .options(selectinload(Investigation.target)))
        target = source.target
        fields = {name: getattr(target, name) for name in (
            "full_name", "email", "username", "phone", "dni", "university", "description")}
        consent = bool((target.extra_data or {}).get("self_consent"))
        payload = InvestigationCreate(target=TargetCreate(**fields, extra_data={
            **(target.extra_data or {}), "validation_source_id": str(source_id)},
            identifiers=(target.extra_data or {}).get("identifiers", [])),
            strategy="rule_based", execution_mode="internal", self_consent=consent)
        created = await workspace.create(payload, db)
        new_id = created.id
    print(json.dumps({"event": "created", "id": str(new_id), "source": str(source_id),
                      "username": baseline["username"], "strategy": "rule_based"}), flush=True)
    queue = await event_bus.subscribe(str(new_id))
    durations = {}

    async def progress():
        while True:
            event = await queue.get()
            if event.get("tool_execution_id") and event.get("duration_seconds") is not None:
                durations[event["tool_execution_id"]] = event["duration_seconds"]
            if event.get("type") in {"tool_start", "tool_complete", "tool_error", "investigation_complete", "investigation_error"}:
                safe = {key: event[key] for key in ("type", "tool", "duration_seconds", "findings_count", "status", "entities_count") if key in event}
                print(json.dumps(safe), flush=True)
            elif event.get("tool") == "username_finder" and event.get("checked") is not None:
                print(json.dumps({key: event.get(key) for key in ("tool", "phase", "checked", "total", "pct", "subject")}), flush=True)
    monitor = asyncio.create_task(progress())
    try:
        await orchestrator.run_investigation(new_id)
        current = await snapshot(new_id)
        for execution in current["tools"]:
            execution["actual_duration_seconds"] = durations.get(execution["id"])
        old_urls = {item["url"].rstrip("/").lower() for item in baseline["profiles"]}
        new_urls = {item["url"].rstrip("/").lower() for item in current["profiles"]}
        report = {"generated_at": datetime.now(timezone.utc).isoformat(),
                  "baseline": baseline, "current": current,
                  "comparison": {"old_profiles": len(old_urls), "new_profiles": len(new_urls),
                                 "shared": sorted(old_urls & new_urls), "new": sorted(new_urls-old_urls),
                                 "not_recovered": sorted(old_urls-new_urls)}}
        from app.tools.maigret_catalog import capabilities
        report["capabilities"] = capabilities()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"event": "finished", "id": str(new_id), "status": current["status"],
                          "entities": sum(current["entity_types"].values()), "native_profiles": len(current["native_profiles"]),
                          "elapsed": current["metrics"].get("execution_time_seconds"), "report": str(output)}), flush=True)
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
        await event_bus.unsubscribe(str(new_id), queue)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["select", "inspect", "run"])
    parser.add_argument("--source", type=UUID)
    parser.add_argument("--output", type=Path, default=Path("../docs/experiments/2026-10-12-maigret-live.json"))
    args = parser.parse_args()
    try:
        if args.mode == "select":
            print(json.dumps(await select_candidates(), ensure_ascii=False, indent=2))
        elif args.mode == "inspect":
            data = await snapshot(args.source)
            print(json.dumps({key: value for key, value in data.items() if key != "runtime"}, ensure_ascii=False, indent=2))
        else:
            await run(args.source, args.output)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
