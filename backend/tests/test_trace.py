"""Trazabilidad estructurada: conserva observaciones sin romper deduplicación."""

from datetime import datetime, timezone
import uuid

import pytest

from app.engine.trace import PendingObservation, safe_input_summary, trace_recorder
from app.models.entity import Entity
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
