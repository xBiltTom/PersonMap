"""Persistencia estructurada y segura de la trazabilidad de ejecución."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.persistence import entity_dedupe_key, finding_dedupe_key
from app.models.entity import Entity
from app.models.entity_observation import EntityObservation
from app.models.investigation_trace_event import InvestigationTraceEvent
from app.models.tool_execution import ToolExecution
from app.tools.base import TargetContext, ToolFinding


@dataclass(frozen=True)
class PendingObservation:
    """Observación en memoria hasta que la deduplicación asigne la entidad canónica."""

    finding: ToolFinding
    tool_execution_id: UUID
    observed_at: datetime


def safe_input_summary(tool: Any, context: Optional[TargetContext] = None) -> Dict[str, Any]:
    """Explica el tipo de contexto usado sin persistir identificadores ni secretos."""
    required_inputs = list(getattr(tool, "required_inputs", []) or [])
    summary: Dict[str, Any] = {"required_inputs": required_inputs}
    if context is not None:
        pivot_types: List[str] = []
        if context.discovered_emails:
            pivot_types.append("email")
        if context.discovered_usernames:
            pivot_types.append("username")
        if context.extra.get("candidate_urls"):
            pivot_types.append("url")
        if context.extra.get("avatar_urls"):
            pivot_types.append("avatar")
        summary["context_origin"] = "expanded" if pivot_types else "target"
        if pivot_types:
            summary["pivot_types_available"] = pivot_types
    return summary


def _safe_source_url(finding: ToolFinding) -> Optional[str]:
    metadata = finding.metadata_info or {}
    for candidate in (metadata.get("source_url"), metadata.get("profile_url"), metadata.get("url"), finding.value):
        if isinstance(candidate, str) and candidate.startswith(("https://", "http://")):
            return candidate[:2048]
    return None


class TraceRecorder:
    """Servicio compartido por los tres motores; no publica ni reemplaza EventBus."""

    async def start_tool(
        self,
        db: AsyncSession,
        *,
        investigation_id: str,
        tool: Any,
        engine: str,
        engine_layer: Optional[str],
        round_index: Optional[int] = None,
        turn_index: Optional[int] = None,
        context: Optional[TargetContext] = None,
    ) -> ToolExecution:
        execution = ToolExecution(
            investigation_id=investigation_id,
            tool_name=str(getattr(tool, "name", "herramienta")),
            tool_description=str(getattr(tool, "description", ""))[:255] or None,
            engine=engine,
            engine_layer=engine_layer,
            round_index=round_index,
            turn_index=turn_index,
            status="running",
            input_summary=safe_input_summary(tool, context),
        )
        db.add(execution)
        await db.flush()
        return execution

    async def complete_tool(
        self,
        execution: ToolExecution,
        *,
        findings_count: int,
        error: Optional[BaseException] = None,
    ) -> None:
        execution.completed_at = datetime.now(timezone.utc)
        execution.findings_count = findings_count
        execution.status = "failed" if error else "completed"
        execution.error_summary = str(error)[:500] if error else None

    async def record_event(
        self,
        db: AsyncSession,
        *,
        investigation_id: str,
        event_type: str,
        engine: str,
        engine_layer: Optional[str] = None,
        round_index: Optional[int] = None,
        turn_index: Optional[int] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> InvestigationTraceEvent:
        event = InvestigationTraceEvent(
            investigation_id=investigation_id,
            event_type=event_type,
            engine=engine,
            engine_layer=engine_layer,
            round_index=round_index,
            turn_index=turn_index,
            data=data or {},
        )
        db.add(event)
        await db.flush()
        return event

    async def record_pivot(
        self,
        db: AsyncSession,
        *,
        investigation_id: str,
        engine: str,
        engine_layer: Optional[str],
        round_index: int,
        additions: Dict[str, int],
    ) -> None:
        meaningful = {kind: count for kind, count in additions.items() if count > 0}
        if meaningful:
            await self.record_event(
                db,
                investigation_id=investigation_id,
                event_type="pivot",
                engine=engine,
                engine_layer=engine_layer,
                round_index=round_index,
                data={"additions": meaningful},
            )

    async def link_observations(
        self,
        db: AsyncSession,
        *,
        investigation_id: str,
        pending: Iterable[PendingObservation],
        entities: Iterable[Entity],
    ) -> List[EntityObservation]:
        """Conserva cada observación aun cuando varias terminen en una entidad deduplicada."""
        by_key = {entity_dedupe_key(entity): entity for entity in entities}
        observations: List[EntityObservation] = []
        seen_pairs: set[tuple[UUID, UUID]] = set()
        for item in pending:
            entity = by_key.get(finding_dedupe_key(item.finding))
            if not entity:
                continue
            pair = (item.tool_execution_id, entity.id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            observation = EntityObservation(
                investigation_id=investigation_id,
                entity_id=entity.id,
                tool_execution_id=item.tool_execution_id,
                observed_at=item.observed_at,
                source_url=_safe_source_url(item.finding),
                evidence_urls=list(dict.fromkeys(item.finding.evidence_urls))[:20],
            )
            db.add(observation)
            observations.append(observation)
        if observations:
            await db.flush()
        return observations


trace_recorder = TraceRecorder()
