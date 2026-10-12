"""Shared dossier operations for REST and MCP, with incremental durable results."""
import asyncio
import hashlib
import json
import logging
import time
from copy import deepcopy
from collections import OrderedDict
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.agent.tool_dispatch import build_call_context
from app.core.database import async_session_maker
from app.core.config import settings
from app.core.events import event_bus
from app.core.fingerprint import run_fingerprint
from app.engine.persistence import build_relationships, persist_findings
from app.engine.pivot_rules import extract_and_apply_pivots
from app.engine.trace import PendingObservation, trace_recorder
from app.core.runtime import durable_runtime, search_limit
from app.identity.resolver import correlation_resolver
from app.models.analysis_note import AnalysisNote
from app.models.correlation_group import CorrelationGroup
from app.models.entity import Entity
from app.models.entity_observation import EntityObservation
from app.models.investigation import Investigation
from app.models.investigation_session import InvestigationSession
from app.models.relationship import Relationship
from app.models.target import Target
from app.models.tool_execution import ToolExecution
from app.schemas.entity import EntityRead
from app.schemas.investigation import InvestigationCreate, InvestigationDetail, InvestigationRead
from app.schemas.trace import ToolExecutionRead
from app.schemas.workspace import CorrelationAssessmentCreate, NoteCreate, NoteRead, SessionCreate, SessionRead, ToolRequest
from app.tools.base import TargetContext, ToolFinding
from app.tools.public_page_reader import PublicPageReaderTool
from app.tools.registry import tool_registry
from app.tools.search_dorker import name_search_variants
from app.services.workspace_updates import WorkspaceUpdates, compact_finding
from app.services.external_evidence import ExternalEvidenceImport, IMPORT_TOOL

logger = logging.getLogger(__name__)
EXTERNAL_TOOLS = {tool.name: tool for tool in tool_registry.get_all()}
EXTERNAL_TOOLS["public_page_reader"] = PublicPageReaderTool()


def parallel_limit():
    return max(1, min(6, settings.mcp_max_parallel_tools))


def merge_runtime(current, baseline, incoming, *, extent=False, counter=False):
    """Apply a task's changes to the latest context without erasing concurrent work."""
    result = deepcopy(current)
    for key, value in incoming.items():
        if key in baseline and value == baseline[key]:
            continue
        prior = baseline.get(key)
        latest = result.get(key)
        if isinstance(value, dict):
            result[key] = merge_runtime(latest if isinstance(latest, dict) else {},
                                        prior if isinstance(prior, dict) else {}, value,
                                        extent=extent or key == "username_finder_coverage",
                                        counter=counter or key == "stats" or key.endswith(("_stats", "_attempts")))
        elif isinstance(value, set):
            result[key] = (latest if isinstance(latest, set) else set(latest or [])) | value
        elif isinstance(value, list):
            combined = list(latest) if isinstance(latest, list) else []
            for item in value:
                if item not in combined:
                    combined.append(deepcopy(item))
            result[key] = combined
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and isinstance(latest, (int, float)) and not isinstance(latest, bool):
            # Counts accumulate; catalogue coverage is a monotonically increasing extent.
            if extent:
                result[key] = max(latest, value)
            elif counter or key == "search_queries_used":
                result[key] = latest + value - (prior or 0)
            else:
                result[key] = value
        else:
            result[key] = deepcopy(value)
    return result


def call_fingerprint(tool_name: str, context: TargetContext) -> str:
    # Only actual inputs; never ephemeral caches, secrets, budgets or event IDs.
    tool = EXTERNAL_TOOLS[tool_name]
    values = {}
    for field in tool.required_inputs:
        if field == "username":
            value = context.all_usernames()
        elif field == "email":
            value = context.all_emails()
        elif field == "phone":
            value = context.all_phones()
        else:
            value = getattr(context, field, context.extra.get(field))
        values[field] = sorted(value) if isinstance(value, list) else value
    if tool_name == "domain_finder":
        values["candidate_urls"] = sorted(context.extra.get("personal_domain_urls", []))
    values["self_consent"] = bool(context.extra.get("self_consent"))
    if tool_name == "search_dorker":
        if context.extra.get("search_queries"):
            values = {"queries": [{"query": q["query"], "include_domains": sorted(q["include_domains"])}
                                  for q in context.extra["search_queries"]]}
        else:
            values["university"] = context.university
            values["discovered_names"] = context.discovered_names
    if tool_name == "username_finder":
        values["scan_mode"] = context.extra.get("username_scan_mode", "deep")
        values["site_limit"] = max(1, settings.username_scan_max_sites)
        if values["scan_mode"] == "fast":
            values["site_limit"] = min(values["site_limit"], max(1, settings.mcp_username_fast_sites))
    return hashlib.sha256(json.dumps([tool_name, values], sort_keys=True).encode()).hexdigest()


class WorkspaceService(WorkspaceUpdates, ExternalEvidenceImport):
    def __init__(self, session_factory=async_session_maker):
        self.session_factory = session_factory
        self.tasks: dict[UUID, asyncio.Task] = {}
        self.contexts: OrderedDict[UUID, TargetContext] = OrderedDict()

    async def _investigation(self, db, investigation_id: UUID, *, lock=False):
        stmt = select(Investigation).where(Investigation.id == investigation_id).options(selectinload(Investigation.target))
        if lock:
            stmt = stmt.with_for_update()
        inv = (await db.scalars(stmt)).one_or_none()
        if not inv:
            raise HTTPException(404, "Expediente no encontrado")
        return inv

    async def create(self, payload: InvestigationCreate, db):
        target = Target(**payload.target.model_dump(exclude={"extra_data"}), extra_data={
            **(payload.target.extra_data or {}), "self_consent": payload.self_consent,
        })
        db.add(target)
        await db.flush()
        inv = Investigation(target_id=target.id, target=target, strategy=payload.strategy,
                            execution_mode=payload.execution_mode, status="pending")
        if payload.execution_mode == "external":
            inv.metrics = {"engine_used": "external", "execution_mode": "external"}
        db.add(inv)
        await db.commit()
        await db.refresh(inv)
        inv.target = target
        await event_bus.publish("registry", {"type": "investigation_created", "investigation_id": str(inv.id), "timestamp": time.time()})
        return inv

    async def detail(self, investigation_id: UUID) -> dict:
        async with self.session_factory() as db:
            stmt = select(Investigation).where(Investigation.id == investigation_id).options(
                selectinload(Investigation.target), selectinload(Investigation.entities),
                selectinload(Investigation.correlation_groups), selectinload(Investigation.analysis_notes),
                selectinload(Investigation.sessions))
            inv = (await db.scalars(stmt)).one_or_none()
            if not inv:
                raise HTTPException(404, "Expediente no encontrado")
            result = InvestigationDetail.model_validate(inv).model_dump(mode="json")
            result["analysis_notes"].sort(key=lambda n: n["created_at"])
            result["sessions"].sort(key=lambda s: s["started_at"])
            return result

    async def create_review(self, source_id: UUID) -> dict:
        """Fork completed rule evidence atomically; the control dossier stays unchanged."""
        async with self.session_factory() as db:
            source = await self._investigation(db, source_id, lock=True)
            if (source.execution_mode != "internal" or source.status != "completed"
                    or (source.metrics or {}).get("engine_used", source.strategy) not in {"rules", "rule_based"}):
                raise HTTPException(409, "La revisión requiere un barrido de reglas terminado")
            target = Target(**{column.name: deepcopy(getattr(source.target, column.name))
                               for column in Target.__table__.columns if column.name not in {"id", "created_at"}})
            target.extra_data = target.extra_data or {}
            db.add(target)
            await db.flush()
            runtime = deepcopy((source.metrics or {}).get("collection_runtime", {}))
            current_config = run_fingerprint()
            coverage_known = "username_finder_coverage" in runtime and all(
                (source.metrics or {}).get(f"config_{key}") == current_config[key]
                for key in ("username_scan_engine_version", "username_catalog_scanned", "maigret_commit"))
            if not coverage_known:
                for key in ("username_finder_coverage", "username_finder_scanned", "username_finder_stats"):
                    runtime.pop(key, None)
            # Review is an additional, explicit phase with its own small query budget.
            for key in ("search_queries_used", "search_queries_executed", "search_provider_attempts",
                        "search_disabled_backends", "search_diagnostics"):
                runtime.pop(key, None)
            runtime["search_query_limit"] = max(0, min(settings.search_query_budget, settings.mcp_review_max_queries))
            review = Investigation(target=target, strategy="auto", execution_mode="external", status="pending",
                metrics={"engine_used": "external", "execution_mode": "external",
                         "review_baseline": {"investigation_id": str(source.id), "metrics": deepcopy(source.metrics or {}),
                                             "coverage_known": coverage_known},
                         "external_runtime": runtime})
            db.add(review)
            await db.flush()
            entity_map, execution_map = {}, {}

            def copy_columns(row):
                return {column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns
                        if column.name not in {"id", "investigation_id"}}

            entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == source.id))).all())
            for entity in entities:
                new_id = uuid4()
                entity_map[entity.id] = new_id
                values = copy_columns(entity)
                values["metadata_info"] = {**(values["metadata_info"] or {}), "imported_from_entity_id": str(entity.id)}
                db.add(Entity(id=new_id, investigation_id=review.id, **values))
            executions = list((await db.scalars(select(ToolExecution).where(ToolExecution.investigation_id == source.id))).all())
            for execution in executions:
                new_id = uuid4()
                execution_map[execution.id] = new_id
                values = copy_columns(execution)
                values["session_id"] = None
                if execution.tool_name == "username_finder" and not coverage_known:
                    values["input_fingerprint"] = None
                values["input_summary"] = {**(values["input_summary"] or {}),
                                           "imported_from_execution_id": str(execution.id)}
                db.add(ToolExecution(id=new_id, investigation_id=review.id, **values))
            await db.flush()

            def remap(value):
                if isinstance(value, dict):
                    return {key: remap(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [remap(item) for item in value]
                if isinstance(value, str):
                    try:
                        return str(entity_map.get(UUID(value), execution_map.get(UUID(value), UUID(value))))
                    except ValueError:
                        pass
                return deepcopy(value)

            for model in (EntityObservation, Relationship, CorrelationGroup):
                rows = list((await db.scalars(select(model).where(model.investigation_id == source.id))).all())
                for row in rows:
                    values = copy_columns(row)
                    for field in ("entity_id", "source_entity_id", "target_entity_id"):
                        if field in values:
                            values[field] = entity_map[values[field]]
                    if "tool_execution_id" in values:
                        values["tool_execution_id"] = execution_map[values["tool_execution_id"]]
                    for field in ("evidence", "entity_ids"):
                        if field in values:
                            values[field] = remap(values[field])
                    db.add(model(investigation_id=review.id, **values))
            review.metrics = {**review.metrics, "imported_findings": len(entities), "imported_executions": len(executions)}
            await trace_recorder.record_event(db, investigation_id=str(review.id), event_type="baseline_import",
                engine="external", data={"source_investigation_id": str(source.id), "entities_count": len(entities)})
            await db.commit()
            await self._publish(review, "workspace_snapshot", "Barrido importado; listo para revisión por agente.")
            await event_bus.publish("registry", {"type": "investigation_created", "investigation_id": str(review.id), "timestamp": time.time()})
            return {"id": str(review.id), "source_investigation_id": str(source.id), "status": review.status,
                    "web_url": f"{settings.frontend_url.rstrip('/')}/investigation/{review.id}",
                    "imported_findings": len(entities), "imported_executions": len(executions),
                    "coverage_known": coverage_known, "review_query_budget": runtime["search_query_limit"]}

    async def context(self, investigation_id: UUID) -> dict:
        async with self.session_factory() as db:
            inv = await self._investigation(db, investigation_id)
            entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == investigation_id))).all())
            context = self._context(inv, entities)
            executions = list((await db.scalars(select(ToolExecution).where(ToolExecution.investigation_id == investigation_id)
                                               .order_by(ToolExecution.started_at.desc()).limit(50))).all())
            active_tools = list((await db.scalars(select(ToolExecution.tool_name).where(
                ToolExecution.investigation_id == investigation_id, ToolExecution.status == "running"))).all())
            notes = list((await db.scalars(select(AnalysisNote).where(AnalysisNote.investigation_id == investigation_id)
                                          .order_by(AnalysisNote.created_at.desc()).limit(20))).all())
            sessions = list((await db.scalars(select(InvestigationSession).where(InvestigationSession.investigation_id == investigation_id)
                                             .order_by(InvestigationSession.started_at.desc()).limit(20))).all())
            return {"investigation": InvestigationRead.model_validate(inv).model_dump(mode="json"),
                    "review_baseline": (inv.metrics or {}).get("review_baseline"),
                    "known_identifiers": context.model_dump(exclude={"extra"}),
                    "name_search_variants": name_search_variants(context.full_name or ""),
                    "reported_candidates": [{"entity_id": str(entity.id), "source_url": report["source_url"],
                        "observed_at": report["observed_at"], "identifier": identifier}
                        for entity in entities for report in (entity.metadata_info or {}).get("external_reports", [])
                        if report["evidence_level"] == "page_content" for identifier in report.get("identifiers", [])][:100],
                    "candidate_urls": context.extra.get("candidate_urls", [])[:100],
                    "executions": [ToolExecutionRead.model_validate(e).model_dump(mode="json") for e in executions],
                    "notes": [NoteRead.model_validate(n).model_dump(mode="json") for n in notes],
                    "sessions": [SessionRead.model_validate(s).model_dump(mode="json") for s in sessions],
                    "total_findings": len(entities),
                    "execution_policy": {"max_parallel_tools": parallel_limit(),
                        "new_execution_requires_pivot": bool((inv.metrics or {}).get("review_baseline")),
                        "external_evidence_batch_limit": 10,
                        "external_candidates_automatically_promoted": False,
                        "pivot_fields": ["question", "expected_signal", "stop_condition"],
                        "active_tools": active_tools,
                        "username_default_mode": "fast", "fast_sites": max(1, settings.mcp_username_fast_sites),
                        "deep_sites": max(1, settings.username_scan_max_sites),
                        "search_queries_remaining": max(0, search_limit(context, settings.search_query_budget) - context.extra.get("search_queries_used", len(context.extra.get("search_queries_executed", []))))},
                    "tool_readiness": [{"name": tool.name, "can_run": tool.can_run(context),
                        "running": tool.name in active_tools}
                        for tool in EXTERNAL_TOOLS.values()],
                    "scan_coverage": context.extra.get("username_finder_coverage", {}),
                    "search_coverage": tool_registry.get_tool("search_dorker").coverage(context)}

    def _context(self, inv, entities, *, use_cached=True):
        ctx = build_call_context({}, inv.target)
        saved = self.contexts.get(inv.id)
        if use_cached:
            if saved:
                ctx.extra.update(deepcopy(saved.extra))
            ctx.extra.update(deepcopy((inv.metrics or {}).get("external_runtime", {})))
            if "username_finder_scanned" in ctx.extra:
                ctx.extra["username_finder_scanned"] = set(ctx.extra["username_finder_scanned"])
        findings = [ToolFinding(entity_type=e.entity_type, platform=e.platform, value=e.value,
                                display_name=e.display_name, metadata_info=dict(e.metadata_info or {})) for e in entities]
        extract_and_apply_pivots(findings, ctx)
        ctx.extra["investigation_id"] = str(inv.id)
        return ctx

    async def _active_session(self, db, inv, session_id):
        session = await db.get(InvestigationSession, session_id)
        if not session or session.investigation_id != inv.id:
            raise HTTPException(404, "Sesión no encontrada en este expediente")
        if inv.execution_mode != "external" or session.status != "active":
            raise HTTPException(409, "La sesión externa no está activa")
        return session

    async def _validate_references(self, db, investigation_id, entity_ids=(), execution_ids=()):
        for model, values in ((Entity, entity_ids), (ToolExecution, execution_ids)):
            if values:
                found = set((await db.scalars(select(model.id).where(model.investigation_id == investigation_id, model.id.in_(values)))).all())
                if found != set(values):
                    raise HTTPException(422, "Las referencias deben pertenecer al mismo expediente")

    async def _publish(self, inv, event_type, message, **data):
        event = {"type": event_type, "investigation_id": str(inv.id), "revision": inv.revision,
                 "message": message, "timestamp": time.time(), "engine": "external", **data}
        await event_bus.publish(str(inv.id), event)
        await event_bus.publish("registry", {"type": "investigation_updated", "investigation_id": str(inv.id),
                                            "revision": inv.revision, "timestamp": event["timestamp"]})

    async def open_session(self, investigation_id: UUID, payload: SessionCreate) -> dict:
        async with self.session_factory() as db:
            inv = await self._investigation(db, investigation_id, lock=True)
            if inv.execution_mode != "external":
                raise HTTPException(409, "El expediente usa el motor interno; crea uno en modo externo")
            active = (await db.scalars(select(InvestigationSession).where(
                InvestigationSession.investigation_id == inv.id, InvestigationSession.status == "active"))).one_or_none()
            if active:
                if active.client != payload.client or active.model != payload.model:
                    raise HTTPException(409, "Otro cliente tiene una sesión activa en el expediente")
                return SessionRead.model_validate(active).model_dump(mode="json")
            session = InvestigationSession(investigation_id=inv.id, **payload.model_dump())
            db.add(session)
            inv.status = "running"
            inv.completed_at = None
            inv.revision += 1
            await trace_recorder.record_event(db, investigation_id=str(inv.id), event_type="session_start",
                                            engine="external", data={"client": payload.client, "model": payload.model})
            await self._record_change(db, inv)
            await db.commit()
            await self._publish(inv, "session_start", f"Sesión externa iniciada: {payload.client}.")
            return SessionRead.model_validate(session).model_dump(mode="json")

    async def add_note(self, investigation_id: UUID, payload: NoteCreate, session_id: UUID | None = None) -> dict:
        async with self.session_factory() as db:
            inv = await self._investigation(db, investigation_id, lock=True)
            session = await self._active_session(db, inv, session_id) if session_id else None
            await self._validate_references(db, inv.id, payload.entity_ids, payload.execution_ids)
            note = AnalysisNote(investigation_id=inv.id, session_id=session_id,
                                author=session.client if session else "Analista", author_type="agent" if session else "analyst",
                                **payload.model_dump(mode="json"))
            db.add(note)
            inv.revision += 1
            if session:
                session.updated_at = datetime.now(timezone.utc)
            await trace_recorder.record_event(db, investigation_id=str(inv.id), event_type="analysis_note",
                                            engine="external" if session else "analyst", data={"kind": note.kind, "title": note.title})
            await db.flush()
            await self._record_change(db, inv, notes=[note.id])
            await db.commit()
            await self._publish(inv, "analysis_note", f"Análisis guardado: {note.title}.")
            return NoteRead.model_validate(note).model_dump(mode="json")

    async def add_assessment(self, investigation_id: UUID, session_id: UUID, payload: CorrelationAssessmentCreate):
        # Assessments are append-only authored hypotheses, never graph/identity merges.
        async with self.session_factory() as db:
            inv = await self._investigation(db, investigation_id)
            await self._active_session(db, inv, session_id)
            await self._validate_references(db, inv.id, payload.entity_ids, payload.execution_ids)
            if payload.supersedes_note_id:
                previous = await db.get(AnalysisNote, payload.supersedes_note_id)
                if (not previous or previous.investigation_id != inv.id
                        or previous.details.get("record_type") != "correlation_assessment"):
                    raise HTTPException(422, "La revisión debe referenciar una evaluación de este expediente")
                if set(previous.entity_ids) != {str(value) for value in payload.entity_ids}:
                    raise HTTPException(422, "La revisión debe evaluar las mismas entidades")
        label = {"candidate": "candidata", "supported": "respaldada", "refuted": "refutada", "inconclusive": "inconclusa"}[payload.verdict]
        return await self.add_note(investigation_id, NoteCreate(kind="hypothesis",
            title=f"Evaluación de correlación: {label}", content=payload.reasoning,
            entity_ids=payload.entity_ids, execution_ids=payload.execution_ids,
            evidence_urls=[*payload.supporting_urls, *payload.contradicting_urls],
            details={"record_type": "correlation_assessment", **payload.model_dump(mode="json", exclude={"reasoning", "entity_ids", "execution_ids"})}), session_id)

    async def submit_tool(self, investigation_id: UUID, session_id: UUID, payload: ToolRequest) -> dict:
        tool = EXTERNAL_TOOLS.get(payload.tool_name)
        if not tool:
            raise HTTPException(422, "Herramienta OSINT desconocida")
        async with self.session_factory() as db:
            inv = await self._investigation(db, investigation_id, lock=True)
            session = await self._active_session(db, inv, session_id)
            await self._validate_references(db, inv.id, payload.source_entity_ids)
            entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == inv.id))).all())
            base_context = self._context(inv, entities)
            # A forced repeat refreshes only this tool's cache, preserving other tools' work.
            # Search retains its budgets even when repeating an explicit query.
            if payload.force and tool.name != "search_dorker":
                for key in list(base_context.extra):
                    if key.startswith(getattr(tool, "cache_prefix", tool.name + "_")):
                        base_context.extra.pop(key)
            inputs = payload.inputs.model_dump(exclude_none=True)
            context = build_call_context(inputs, inv.target, base_context)
            # Per-call planning is isolated from caches shared by concurrent jobs.
            context.extra.pop("search_queries", None)
            context.extra.pop("username_scan_mode", None)
            context.extra.pop("search_force", None)
            if tool.name == "search_dorker":
                context.extra["search_force"] = payload.force
            if payload.inputs.queries:
                if tool.name != "search_dorker":
                    raise HTTPException(422, "queries solo está disponible en search_dorker")
                context.extra["search_queries"] = [q.model_dump() for q in payload.inputs.queries]
            if payload.inputs.scan_mode and tool.name != "username_finder":
                raise HTTPException(422, "scan_mode solo está disponible en username_finder")
            if tool.name == "username_finder":
                context.extra["username_scan_mode"] = payload.inputs.scan_mode or "fast"
            for field, discovered in (("username", "discovered_usernames"), ("email", "discovered_emails"),
                                      ("phone", "discovered_phones"), ("full_name", "discovered_names")):
                if getattr(payload.inputs, field):
                    setattr(context, discovered, [])
            # Explicit URL selection avoids scraping every accumulated candidate again.
            if payload.inputs.candidate_urls:
                context.extra["candidate_urls"] = payload.inputs.candidate_urls
                if tool.name == "domain_finder":
                    context.extra["personal_domain_urls"] = payload.inputs.candidate_urls
            context.extra["investigation_id"] = str(inv.id)
            if not tool.can_run(context):
                raise HTTPException(422, "Faltan entradas requeridas para la herramienta")
            if tool.name == "public_page_reader" and not payload.inputs.candidate_urls:
                raise HTTPException(422, "Selecciona explícitamente las URLs que se leerán")
            if tool.name == "public_page_reader" and len(payload.inputs.candidate_urls) > 3:
                raise HTTPException(422, "Lee como máximo tres páginas por ejecución")
            fingerprint = call_fingerprint(tool.name, context)
            previous = (await db.scalars(select(ToolExecution).where(
                ToolExecution.investigation_id == inv.id, ToolExecution.input_fingerprint == fingerprint,
                ToolExecution.status.in_(["running", "completed"])).order_by(ToolExecution.started_at.desc()).limit(1))).first()
            if previous and (previous.status == "running" or not payload.force):
                return {**ToolExecutionRead.model_validate(previous).model_dump(mode="json"), "reused": True}
            if (inv.metrics or {}).get("review_baseline") and not payload.force:
                supplied = payload.inputs.model_dump(exclude_none=True, exclude_defaults=True)
                supplied.pop("scan_mode", None)
                inherited = (await db.scalars(select(ToolExecution.id).where(
                    ToolExecution.investigation_id == inv.id, ToolExecution.tool_name == tool.name,
                    ToolExecution.engine != "external", ToolExecution.status == "completed").limit(1))).first()
                if inherited and not supplied:
                    raise HTTPException(409, "El barrido ya ejecutó esta herramienta; selecciona entradas para una subbúsqueda o usa force")
            if (inv.metrics or {}).get("review_baseline") and not payload.pivot:
                raise HTTPException(422, "Una nueva subbúsqueda de revisión requiere pivot, entidades de origen y justificación")
            running = list((await db.scalars(select(ToolExecution).where(
                ToolExecution.investigation_id == inv.id, ToolExecution.status == "running"))).all())
            if len(running) >= parallel_limit():
                raise HTTPException(409, f"Se alcanzó el límite de {parallel_limit()} herramientas simultáneas")
            if any(item.tool_name == tool.name for item in running):
                raise HTTPException(409, "Espera a que termine la ejecución activa de esta misma herramienta")
            execution = await trace_recorder.start_tool(db, investigation_id=str(inv.id), tool=tool,
                                                       engine="external", engine_layer="external", context=context)
            execution.session_id = session.id
            execution.input_fingerprint = fingerprint
            execution.input_summary = {**execution.input_summary, "rationale": payload.rationale,
                                       "source_entity_ids": [str(i) for i in payload.source_entity_ids]}
            if payload.pivot:
                execution.input_summary["pivot"] = payload.pivot.model_dump()
            if tool.name == "search_dorker" and payload.inputs.queries:
                execution.input_summary["queries"] = context.extra["search_queries"]
            if tool.name == "username_finder":
                execution.input_summary["scan_mode"] = context.extra["username_scan_mode"]
                execution.input_summary["site_limit"] = min(max(1, settings.username_scan_max_sites), max(1, settings.mcp_username_fast_sites)) if context.extra["username_scan_mode"] == "fast" else max(1, settings.username_scan_max_sites)
            session.updated_at = datetime.now(timezone.utc)
            inv.metrics = {**(inv.metrics or {}), "external_peak_parallel_tools":
                max((inv.metrics or {}).get("external_peak_parallel_tools", 0), len(running) + 1)}
            inv.revision += 1
            await self._record_change(db, inv, executions=[execution.id])
            await db.commit()
            await self._publish(inv, "tool_start", f"Ejecutando {tool.name}.", tool=tool.name, tool_execution_id=str(execution.id))
            task = asyncio.create_task(self._run_tool(inv.id, execution.id, tool, context, deepcopy(context.extra)))
            self.tasks[execution.id] = task
            task.add_done_callback(lambda _: self.tasks.pop(execution.id, None))
            return {**ToolExecutionRead.model_validate(execution).model_dump(mode="json"), "reused": False}

    async def _run_tool(self, investigation_id, execution_id, tool, context, baseline):
        findings, error = [], None
        try:
            async with asyncio.timeout(600):
                findings = await tool.execute(context)
            for finding in findings:
                finding.metadata_info.update({"source_tool": tool.name, "engine_layer": "external"})
        except asyncio.CancelledError:
            error = "Ejecución interrumpida al detener el servidor; puedes reintentarlo."
        except Exception:
            logger.exception("External OSINT execution failed: %s", execution_id)
            error = "La herramienta no pudo completar la ejecución."
        try:
            async with self.session_factory() as db:
                inv = await self._investigation(db, investigation_id, lock=True)
                execution = await db.get(ToolExecution, execution_id)
                entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == inv.id))).all())
                execution.completed_at = datetime.now(timezone.utc)
                execution.status = "failed" if error else "completed"
                execution.error_summary = error
                execution.findings_count = len(findings)
                if tool.name == "search_dorker":
                    execution.input_summary = {**execution.input_summary,
                        "search_status": context.extra.get("search_last_status"),
                        "search_diagnostics": context.extra.get("search_diagnostics", [])[-15:],
                        "search_queries_remaining": max(0, search_limit(context, settings.search_query_budget) - context.extra.get("search_queries_used", len(context.extra.get("search_queries_executed", []))))}
                if tool.name == "public_page_reader":
                    execution.input_summary = {**execution.input_summary,
                        "page_errors": context.extra.get("public_page_reader_errors", [])}
                if not error:
                    changed = await persist_findings(str(inv.id), findings, inv.target, db, existing_entities=entities)
                    await trace_recorder.link_observations(db, investigation_id=str(inv.id),
                        pending=[PendingObservation(f, execution.id, execution.completed_at) for f in findings], entities=changed)
                    all_entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == inv.id))).all())
                    await db.execute(delete(Relationship).where(Relationship.investigation_id == inv.id))
                    await db.execute(delete(CorrelationGroup).where(CorrelationGroup.investigation_id == inv.id))
                    relationships = await build_relationships(str(inv.id), all_entities, db)
                    groups = await correlation_resolver.resolve_groups(inv.id, all_entities, relationships)
                    db.add_all(groups)
                    latest = self._context(inv, all_entities)
                    latest.extra = merge_runtime(latest.extra, baseline, context.extra)
                    latest.extra.pop("search_queries", None)
                    latest.extra.pop("username_scan_mode", None)
                    latest.extra.pop("search_force", None)
                    before = len(latest.extra.get("candidate_urls", []))
                    extract_and_apply_pivots(findings, latest)
                    await trace_recorder.record_event(db, investigation_id=str(inv.id), event_type="pivot", engine="external",
                        data={"source_execution_id": str(execution.id), "source_entity_ids": [str(e.id) for e in changed],
                              "candidate_urls_added": max(0, len(latest.extra.get("candidate_urls", [])) - before)})
                else:
                    latest = self._context(inv, entities)
                    latest.extra = merge_runtime(latest.extra, baseline, context.extra)
                    latest.extra.pop("search_queries", None)
                    latest.extra.pop("username_scan_mode", None)
                    latest.extra.pop("search_force", None)
                inv.metrics = {**(inv.metrics or {}), "external_runtime": durable_runtime(latest.extra)}
                inv.revision += 1
                await self._record_change(db, inv, executions=[execution.id],
                                          entities=[entity.id for entity in changed] if not error else [])
                await db.commit()
                self.contexts[inv.id] = latest
                self.contexts.move_to_end(inv.id)
                while len(self.contexts) > 100:
                    self.contexts.popitem(last=False)
                await self._publish(inv, "tool_error" if error else "tool_complete",
                    error or f"{tool.name}: {len(findings)} observaciones guardadas.",
                    tool=tool.name, tool_execution_id=str(execution.id), findings_count=len(findings))
        except HTTPException as exc:
            if exc.status_code != 404:
                logger.exception("Could not persist external execution")
        except Exception:
            logger.exception("Could not persist external execution: %s", execution_id)
            # Persist failure in a fresh transaction, so a failed flush does not leave a running job forever.
            async with self.session_factory() as db:
                inv = await self._investigation(db, investigation_id, lock=True)
                execution = await db.get(ToolExecution, execution_id)
                if execution:
                    execution.status = "failed"
                    execution.completed_at = datetime.now(timezone.utc)
                    execution.error_summary = "No se pudieron guardar los resultados de la herramienta."
                    inv.revision += 1
                    await self._record_change(db, inv, executions=[execution.id])
                    await db.commit()

    async def execution(self, investigation_id: UUID, execution_id: UUID) -> dict:
        async with self.session_factory() as db:
            execution = await db.get(ToolExecution, execution_id)
            if not execution or execution.investigation_id != investigation_id:
                raise HTTPException(404, "Ejecución no encontrada en este expediente")
            ids = list((await db.scalars(select(EntityObservation.entity_id).where(EntityObservation.tool_execution_id == execution.id))).all())
            return {**ToolExecutionRead.model_validate(execution).model_dump(mode="json"), "entity_ids": [str(i) for i in ids]}

    async def submit_batch(self, investigation_id: UUID, session_id: UUID, requests: list[ToolRequest]):
        # Each item commits independently; report every accepted or rejected item explicitly.
        results = []
        for request in requests:
            try:
                result = await self.submit_tool(investigation_id, session_id, request)
                results.append({"tool_name": request.tool_name, "accepted": True, "execution": result})
            except HTTPException as exc:
                results.append({"tool_name": request.tool_name, "accepted": False,
                                "status_code": exc.status_code, "error": exc.detail})
        return {"results": results, "max_parallel_tools": parallel_limit()}

    async def executions(self, investigation_id: UUID, execution_ids: list[UUID], wait_seconds: float = 0):
        results = [await self.execution(investigation_id, execution_id) for execution_id in execution_ids]
        pending = [self.tasks[UUID(item["id"])] for item in results
                   if item["status"] == "running" and UUID(item["id"]) in self.tasks]
        if wait_seconds and pending:
            # Waiting is bounded and never cancels the job on client disconnect or timeout.
            await asyncio.wait(pending, timeout=wait_seconds, return_when=asyncio.FIRST_COMPLETED)
            results = [await self.execution(investigation_id, execution_id) for execution_id in execution_ids]
        running = sum(item["status"] == "running" for item in results)
        return {"executions": results, "running_count": running, "next_poll_seconds": 5 if running else None}

    async def findings(self, investigation_id: UUID, limit=20, offset=0, entity_id: UUID | None = None, *, include_content=False):
        async with self.session_factory() as db:
            await self._investigation(db, investigation_id)
            stmt = select(Entity).where(Entity.investigation_id == investigation_id)
            if entity_id:
                stmt = stmt.where(Entity.id == entity_id)
            rows = list((await db.scalars(stmt.order_by(Entity.discovered_at, Entity.id).offset(offset).limit(limit + 1))).all())
            if entity_id and not rows:
                raise HTTPException(404, "Hallazgo no encontrado")
            findings = [(EntityRead.model_validate(e).model_dump(mode="json") if include_content else compact_finding(e))
                        for e in rows[:limit]]
            return {"findings": findings,
                    "next_offset": offset + limit if len(rows) > limit else None}

    async def close_session(self, investigation_id: UUID, session_id: UUID, action: str, summary: str | None = None):
        async with self.session_factory() as db:
            inv = await self._investigation(db, investigation_id, lock=True)
            session = await self._active_session(db, inv, session_id)
            running = (await db.scalars(select(ToolExecution.id).where(
                ToolExecution.investigation_id == inv.id, ToolExecution.status == "running").limit(1))).first()
            if running:
                raise HTTPException(409, "La herramienta sigue ejecutándose; consulta su progreso antes de cerrar la sesión")
            now = datetime.now(timezone.utc)
            session.status = "completed" if action == "finish" else "paused"
            session.ended_at = session.updated_at = now
            inv.status = "completed" if action == "finish" else "paused"
            inv.completed_at = now if action == "finish" else None
            if summary:
                inv.summary = summary
                summary_note = AnalysisNote(investigation_id=inv.id, session_id=session.id, author=session.client,
                                   author_type="agent", kind="summary", title="Resumen de sesión", content=summary)
                db.add(summary_note)
            executions = list((await db.scalars(select(ToolExecution).where(ToolExecution.investigation_id == inv.id))).all())
            imports = [e for e in executions if e.engine == "external" and e.tool_name == IMPORT_TOOL]
            external_executions = [e for e in executions if e.engine == "external" and e.tool_name != IMPORT_TOOL]
            sessions = list((await db.scalars(select(InvestigationSession).where(InvestigationSession.investigation_id == inv.id))).all())
            entities = list((await db.scalars(select(Entity.id).where(Entity.investigation_id == inv.id))).all())
            groups = list((await db.scalars(select(CorrelationGroup.id).where(CorrelationGroup.investigation_id == inv.id))).all())
            inv.metrics = {**(inv.metrics or {}), "engine_used": "external", "execution_mode": "external",
                "external_client": session.client, "external_model_declared": session.model,
                "external_sessions": len(sessions), "external_tools_registered": len(EXTERNAL_TOOLS),
                "external_scan_coverage": (inv.metrics or {}).get("external_runtime", {}).get("username_finder_coverage", {}),
                "tools_executed": len(external_executions), "entities_discovered": len(entities), "correlation_groups": len(groups),
                "external_import_batches": len(imports), "external_import_observations": sum(e.findings_count for e in imports),
                "external_import_seconds": sum(max(0, (e.completed_at - e.started_at).total_seconds()) for e in imports if e.completed_at),
                "external_acquisition_time_measured": False,
                "new_findings": max(0, len(entities) - (inv.metrics or {}).get("imported_findings", 0)),
                "tool_execution_seconds": sum(max(0, (e.completed_at - e.started_at).total_seconds()) for e in external_executions if e.completed_at),
                "execution_time_seconds": sum(max(0, ((s.ended_at or now) - s.started_at).total_seconds()) for s in sessions),
                "elapsed_wall_seconds": max(0, (now - inv.created_at).total_seconds()),
                **{f"config_{k}": v for k, v in run_fingerprint().items()}}
            inv.revision += 1
            await trace_recorder.record_event(db, investigation_id=str(inv.id), event_type="session_complete" if action == "finish" else "session_pause",
                                            engine="external", data={"session_id": str(session.id)})
            await db.flush()
            await self._record_change(db, inv, notes=[summary_note.id] if summary else [])
            await db.commit()
            self.contexts.pop(inv.id, None)
            await self._publish(inv, "session_complete" if action == "finish" else "session_pause",
                                "Sesión finalizada." if action == "finish" else "Sesión pausada; el expediente conserva sus resultados.")
            return SessionRead.model_validate(session).model_dump(mode="json")

    async def recover_sessions(self):
        """A process restart cannot resume in-memory jobs; mark them explicitly."""
        async with self.session_factory() as db:
            now = datetime.now(timezone.utc)
            executions = list((await db.scalars(select(ToolExecution).where(ToolExecution.engine == "external", ToolExecution.status == "running"))).all())
            for execution in executions:
                execution.status = "failed"
                execution.completed_at = now
                execution.error_summary = "Interrumpida por reinicio del servidor; la llamada puede reintentarse."
            sessions = list((await db.scalars(select(InvestigationSession).where(InvestigationSession.status == "active"))).all())
            for session in sessions:
                session.status = "paused"
                session.ended_at = session.updated_at = now
                inv = await self._investigation(db, session.investigation_id, lock=True)
                if inv:
                    inv.status = "paused"
                    inv.revision += 1
                    await self._record_change(db, inv, executions=[execution.id for execution in executions
                                                                 if execution.investigation_id == inv.id])
            await db.commit()

    async def shutdown(self):
        pending = list(self.tasks.values())
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self.recover_sessions()


workspace = WorkspaceService()
