"""Atomic import of externally acquired evidence; never impersonates a collector."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, delete

from app.core.runtime import durable_runtime
from app.engine.persistence import persist_findings, build_relationships, entity_dedupe_key, finding_dedupe_key
from app.identity.resolver import correlation_resolver
from app.models.entity import Entity
from app.models.entity_observation import EntityObservation
from app.models.tool_execution import ToolExecution
from app.models.relationship import Relationship
from app.models.correlation_group import CorrelationGroup
from app.schemas.external_evidence import ExternalEvidenceBatch
from app.tools.base import ToolFinding
from app.tools.search_dorker import SearchDorkerTool
from app.services.workspace_updates import compact_finding

IMPORT_TOOL = "external_evidence_import"


class ExternalEvidenceImport:
    async def import_evidence(self, investigation_id, session_id, payload: ExternalEvidenceBatch):
        encoded = json.dumps(payload.model_dump(mode="json", exclude={"idempotency_key"}), sort_keys=True)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        fingerprint = hashlib.sha256(("key:" + payload.idempotency_key if payload.idempotency_key else "payload:" + digest).encode()).hexdigest()
        async with self.session_factory() as db:
            inv = await self._investigation(db, investigation_id, lock=True)
            session = await self._active_session(db, inv, session_id)
            await self._validate_references(db, inv.id, payload.source_entity_ids)
            previous = (await db.scalars(select(ToolExecution).where(
                ToolExecution.investigation_id == inv.id, ToolExecution.tool_name == IMPORT_TOOL,
                ToolExecution.input_fingerprint == fingerprint))).first()
            if previous:
                if previous.input_summary["payload_fingerprint"] != digest:
                    raise HTTPException(409, "La clave de idempotencia ya identifica otro contenido")
                observations = list((await db.scalars(select(EntityObservation).where(
                    EntityObservation.tool_execution_id == previous.id))).all())
                return {"execution_id": str(previous.id), "entity_ids": list(dict.fromkeys(str(obs.entity_id) for obs in observations)),
                    "observation_ids": [str(obs.id) for obs in observations], "reused": True,
                    "acquisition_scope": "client_reported", "server_fetched_sources": False}
            execution = ToolExecution(investigation_id=inv.id, session_id=session.id, tool_name=IMPORT_TOOL,
                tool_description="Importación de evidencia declarada por el agente externo",
                engine="external", engine_layer="external_import", status="running", input_fingerprint=fingerprint,
                input_summary={"rationale": payload.rationale, "source_entity_ids": [str(value) for value in payload.source_entity_ids],
                    "payload_fingerprint": digest, "acquisition_scope": "client_reported",
                    "duration_scope": "persistence_only", "server_fetched_sources": False})
            db.add(execution)
            await db.flush()
            findings = []
            report_ids = [uuid4() for record in payload.records]
            for report_id, record in zip(report_ids, payload.records):
                findings.append(ToolFinding(entity_type=record.entity_type,
                    platform=SearchDorkerTool()._detect_platform(record.url), value=record.url, display_name=record.title,
                    confidence=0.4, evidence_urls=[record.source_url], metadata_info={
                        "source_tool": IMPORT_TOOL, "engine_layer": "external_import", "ownership_status": "unverified",
                        "external_evidence": True, "external_reports": [{**record.model_dump(mode="json"),
                            "observation_id": str(report_id),
                            "server_verified": False, "reported_by": session.client, "reported_session_id": str(session.id)}]}))
            existing = list((await db.scalars(select(Entity).where(Entity.investigation_id == inv.id))).all())
            changed = await persist_findings(str(inv.id), findings, inv.target, db, existing_entities=existing)
            by_key = {entity_dedupe_key(entity): entity for entity in changed}
            observations = [EntityObservation(id=report_id, investigation_id=inv.id,
                entity_id=by_key[finding_dedupe_key(finding)].id, tool_execution_id=execution.id,
                source_url=record.source_url, evidence_urls=[record.source_url], observed_at=record.observed_at)
                for report_id, finding, record in zip(report_ids, findings, payload.records)]
            db.add_all(observations)
            # Persist per-observation provenance even when two reports collapse to one entity.
            execution.input_summary = {**execution.input_summary, "reported_records": [
                {"observation_id": str(obs.id), "entity_id": str(obs.entity_id),
                 "acquisition_method": record.acquisition_method, "evidence_level": record.evidence_level}
                for record, obs in zip(payload.records, observations)]}
            all_entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == inv.id))).all())
            await db.execute(delete(Relationship).where(Relationship.investigation_id == inv.id))
            await db.execute(delete(CorrelationGroup).where(CorrelationGroup.investigation_id == inv.id))
            relationships = await build_relationships(str(inv.id), all_entities, db)
            db.add_all(await correlation_resolver.resolve_groups(inv.id, all_entities, relationships))
            execution.status = "completed"
            execution.findings_count = len(payload.records)
            execution.completed_at = session.updated_at = datetime.now(timezone.utc)
            inv.revision += 1
            context = self._context(inv, all_entities)
            inv.metrics = {**(inv.metrics or {}), "external_runtime": durable_runtime(context.extra)}
            await self._record_change(db, inv, entities=[entity.id for entity in changed], executions=[execution.id])
            await db.commit()
            self.contexts.pop(inv.id, None)
            await self._publish(inv, "tool_complete", f"Evidencia externa guardada: {len(payload.records)} observaciones declaradas.",
                tool=IMPORT_TOOL, tool_execution_id=str(execution.id), findings_count=len(payload.records))
            return {"execution_id": str(execution.id), "entity_ids": [str(entity.id) for entity in changed],
                "observation_ids": [str(obs.id) for obs in observations],
                "findings": [compact_finding(entity) for entity in changed], "reused": False,
                "acquisition_scope": "client_reported", "server_fetched_sources": False}
