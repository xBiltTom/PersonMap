"""Durable, paginated changes for external agents; cursors survive server restarts."""
import asyncio
import base64
import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.engine.trace import trace_recorder
from app.models.analysis_note import AnalysisNote
from app.models.entity import Entity
from app.models.investigation_trace_event import InvestigationTraceEvent
from app.models.tool_execution import ToolExecution
from app.schemas.entity import EntityRead
from app.schemas.workspace import NoteRead
from app.schemas.trace import ToolExecutionRead


def compact_finding(entity):
    finding = EntityRead.model_validate(entity).model_dump(mode="json")
    metadata = finding["metadata_info"]
    omitted = [key for key in ("page_text", "raw_content", "document_text") if key in metadata]
    for key in omitted:
        metadata.pop(key)
    if omitted:
        metadata["content_available"] = True
    return finding


def encode_cursor(investigation_id, revision, offset=0):
    return base64.urlsafe_b64encode(json.dumps([str(investigation_id), revision, offset]).encode()).decode()


def decode_cursor(cursor, investigation_id):
    try:
        if len(cursor) > 256:
            raise ValueError
        case, revision, offset = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if case != str(investigation_id) or type(revision) is not int or type(offset) is not int or min(revision, offset) < 0:
            raise ValueError
        return revision, offset
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(422, "Cursor inválido o de otro expediente") from None


class WorkspaceUpdates:
    async def _record_change(self, db, inv, *, entities=(), executions=(), notes=()):
        if inv.execution_mode != "external":
            return
        await db.flush()
        await trace_recorder.record_event(db, investigation_id=str(inv.id), event_type="workspace_change",
            engine="external", data={"revision": inv.revision, "status": inv.status,
                "entities": list(dict.fromkeys(str(value) for value in entities)),
                "executions": list(dict.fromkeys(str(value) for value in executions)),
                "notes": list(dict.fromkeys(str(value) for value in notes))})

    async def updates(self, investigation_id, since_revision, *, cursor=None, limit=20, wait_seconds=0):
        if not 1 <= limit <= 50 or not 0 <= wait_seconds <= 20 or since_revision < 0:
            raise HTTPException(422, "Usa limit 1–50, espera 0–20 y revisión no negativa")
        revision, offset = decode_cursor(cursor, investigation_id) if cursor else (since_revision, 0)
        result = await self._updates_page(investigation_id, revision, offset, limit)
        if not result["changes"] and wait_seconds:
            pending = [task for execution_id, task in self.tasks.items()
                       if str(execution_id) in result["active_execution_ids"]]
            if pending:
                await asyncio.wait(pending, timeout=wait_seconds, return_when=asyncio.FIRST_COMPLETED)
                result = await self._updates_page(investigation_id, revision, offset, limit)
        return result

    async def _updates_page(self, investigation_id, revision, offset, limit):
        async with self.session_factory() as db:
            # Writers use this same lock, so the revision and changes form one committed view.
            inv = await self._investigation(db, investigation_id, lock=True)
            if inv.execution_mode != "external":
                raise HTTPException(409, "Las actualizaciones incrementales requieren un expediente externo")
            if revision > inv.revision:
                raise HTTPException(422, "El cursor supera la revisión actual")
            event_revision = InvestigationTraceEvent.data["revision"].as_integer()
            condition = event_revision >= revision if offset else event_revision > revision
            events = list((await db.scalars(select(InvestigationTraceEvent).where(
                InvestigationTraceEvent.investigation_id == inv.id,
                InvestigationTraceEvent.event_type == "workspace_change", condition)
                .order_by(event_revision).limit(limit + 1))).all())
            selected = []
            for event in events:
                version = event.data["revision"]
                items = [("state", {"status": event.data["status"]})]
                for kind, key in (("execution", "executions"), ("finding", "entities"), ("note", "notes")):
                    items.extend((kind, value) for value in event.data[key])
                start = offset if version == revision else 0
                if start >= len(items):
                    raise HTTPException(422, "Posición de cursor inválida")
                for index in range(start, len(items)):
                    selected.append((version, index, len(items), *items[index]))
                    if len(selected) > limit:
                        break
                if len(selected) > limit:
                    break
            if offset and (not events or events[0].data["revision"] != revision):
                raise HTTPException(422, "Revisión de cursor no encontrada")
            has_more = len(selected) > limit
            selected = selected[:limit]
            records = {}
            for kind, model, schema in (("finding", Entity, EntityRead), ("execution", ToolExecution, ToolExecutionRead),
                                        ("note", AnalysisNote, NoteRead)):
                ids = {UUID(item[4]) for item in selected if item[3] == kind}
                if not ids:
                    continue
                rows = (await db.scalars(select(model).where(model.investigation_id == inv.id, model.id.in_(ids)))).all()
                for row in rows:
                    data = compact_finding(row) if kind == "finding" else schema.model_validate(row).model_dump(mode="json")
                    if kind == "note":
                        details = data.pop("details", {})
                        if details.get("record_type") == "correlation_assessment":
                            data["assessment"] = {key: details.get(key) for key in
                                ("verdict", "supporting_urls", "contradicting_urls", "supersedes_note_id")}
                        data["content_available"] = True
                        data["content"] = data["content"][:1500]
                    records[kind, str(row.id)] = data
            changes = [{"revision": version, "kind": kind,
                        "data": value if kind == "state" else records.get((kind, value), {"id": value, "unavailable": True})}
                       for version, _, _, kind, value in selected]
            if selected:
                version, index, count, _, _ = selected[-1]
                next_revision, next_offset = (version, index + 1) if index + 1 < count else (version, 0)
            else:
                next_revision, next_offset = inv.revision, 0
            active_ids = list((await db.scalars(select(ToolExecution.id).where(
                ToolExecution.investigation_id == inv.id, ToolExecution.status == "running"))).all())
            return {"changes": changes, "next_cursor": encode_cursor(inv.id, next_revision, next_offset),
                "has_more": has_more, "revision": inv.revision, "status": inv.status,
                "active_execution_ids": [str(value) for value in active_ids],
                "next_poll_seconds": 5 if active_ids else None}
