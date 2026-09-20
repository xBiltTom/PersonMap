"""Trazabilidad estructurada: conserva observaciones sin romper deduplicación."""

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from app.engine.trace import PendingObservation, safe_input_summary, trace_recorder
from app.api.v1.stream import reconstruct_trace_logs
from app.models.entity import Entity
from app.models.investigation import Investigation
from app.models.investigation_trace_event import InvestigationTraceEvent
from app.models.tool_execution import ToolExecution
from app.tools.base import TargetContext, ToolFinding


class _MemorySession:
    def __init__(self):
        self.added = []

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        return None


def _entity(investigation_id: uuid.UUID) -> Entity:
    return Entity(
        id=uuid.uuid4(),
        investigation_id=investigation_id,
        entity_type="social_account",
        platform="github",
        value="https://github.com/jperez",
        display_name="jperez",
        metadata_info={},
        source_tool="username_finder",
    )


@pytest.mark.asyncio
async def test_a_deduplicated_entity_keeps_two_tool_observations():
    investigation_id = uuid.uuid4()
    entity = _entity(investigation_id)
    first = ToolFinding(entity_type="social_account", platform="github", value="https://github.com/jperez")
    second = ToolFinding(entity_type="social_account", platform="GitHub (User)", value="https://www.github.com/jperez/")
    now = datetime.now(timezone.utc)
    session = _MemorySession()

    observations = await trace_recorder.link_observations(
        session,
        investigation_id=str(investigation_id),
        pending=[
            PendingObservation(first, uuid.uuid4(), now),
            PendingObservation(second, uuid.uuid4(), now),
        ],
        entities=[entity],
    )

    assert len(observations) == 2
    assert {item.entity_id for item in observations} == {entity.id}
    assert len(session.added) == 2


def test_safe_input_summary_keeps_types_not_target_values():
    tool = type("Tool", (), {"required_inputs": ["username", "email"]})()
    context = TargetContext(
        username="jperez",
        discovered_emails=["personal@example.com"],
        extra={"candidate_urls": ["https://example.com/jperez"]},
    )

    summary = safe_input_summary(tool, context)

    assert summary == {
        "required_inputs": ["username", "email"],
        "context_origin": "expanded",
        "pivot_types_available": ["email", "url"],
    }
    assert "jperez" not in str(summary)
    assert "personal@example.com" not in str(summary)


def test_reconstructed_console_uses_structured_trace_not_progress_logs():
    investigation_id = uuid.uuid4()
    started = datetime(2026, 9, 20, 14, 22, 2, tzinfo=timezone.utc)
    completed = datetime(2026, 9, 20, 14, 22, 16, tzinfo=timezone.utc)
    investigation = Investigation(
        id=investigation_id,
        target_id=uuid.uuid4(),
        strategy="hybrid",
        status="completed",
        completed_at=completed,
    )
    execution = ToolExecution(
        id=uuid.uuid4(),
        investigation_id=investigation_id,
        tool_name="username_finder",
        engine="hybrid",
        engine_layer="heuristic",
        round_index=1,
        started_at=started,
        completed_at=completed,
        status="completed",
        findings_count=18,
    )
    pivot = InvestigationTraceEvent(
        id=uuid.uuid4(),
        investigation_id=investigation_id,
        event_type="pivot",
        engine="hybrid",
        engine_layer="heuristic",
        round_index=1,
        created_at=completed + timedelta(seconds=1),
        data={"additions": {"emails": 2, "usernames": 1, "urls": 4}},
    )

    logs = reconstruct_trace_logs(investigation, [execution], [pivot])

    assert [log["type"] for log in logs] == ["tool_start", "tool_complete", "log", "investigation_complete"]
    assert logs[0]["tool_execution_id"] == str(execution.id)
    assert logs[1]["duration_seconds"] == 14.0
    assert logs[2]["phase"] == "pivot"
    assert "+2 emails" in logs[2]["message"]
    assert all(log.get("phase") != "progress" for log in logs)


def test_reconstructed_console_keeps_failed_tool_error_summary():
    investigation_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    investigation = Investigation(id=investigation_id, target_id=uuid.uuid4(), strategy="rule_based", status="failed")
    failed = ToolExecution(
        id=uuid.uuid4(), investigation_id=investigation_id, tool_name="github_scanner",
        engine="rules", engine_layer="heuristic", started_at=now, completed_at=now,
        status="failed", findings_count=0, error_summary="timeout",
    )

    logs = reconstruct_trace_logs(investigation, [failed], [])

    assert logs[-1]["type"] == "tool_error"
    assert logs[-1]["error"] == "timeout"
