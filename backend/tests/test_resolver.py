"""Tests de grupos de evidencia sin atribución de identidad."""

import uuid

import pytest

from app.identity.resolver import UnionFind, correlation_resolver
from app.models.entity import Entity
from app.models.relationship import Relationship


def _entity(entity_type: str = "social_account") -> Entity:
    return Entity(
        id=uuid.uuid4(),
        investigation_id=uuid.uuid4(),
        entity_type=entity_type,
        platform="github",
        value=f"https://example.test/{uuid.uuid4().hex}",
        display_name="observación",
        metadata_info={},
        source_tool="test",
    )


def _relationship(left: Entity, right: Entity, *, supports_group: bool) -> Relationship:
    return Relationship(
        id=uuid.uuid4(),
        investigation_id=left.investigation_id,
        source_entity_id=left.id,
        target_entity_id=right.id,
        relation_type="shares_declared_email",
        supports_group=supports_group,
        evidence={"email": "ana@example.test"},
    )


def test_union_find_is_transitive():
    union_find = UnionFind(["a", "b", "c", "d"])
    union_find.union("a", "b")
    union_find.union("b", "c")
    groups = {frozenset(group) for group in union_find.groups().values()}
    assert frozenset({"a", "b", "c"}) in groups
    assert frozenset({"d"}) in groups


@pytest.mark.asyncio
async def test_explicit_evidence_creates_one_visual_group():
    left, right = _entity(), _entity()
    groups = await correlation_resolver.resolve_groups(
        uuid.uuid4(), [left, right], [_relationship(left, right, supports_group=True)]
    )
    assert len(groups) == 1
    assert set(groups[0].entity_ids) == {str(left.id), str(right.id)}
    assert groups[0].label == "Grupo 01"
    assert groups[0].evidence["edges"][0]["evidence"]["email"] == "ana@example.test"


@pytest.mark.asyncio
async def test_contextual_relation_does_not_merge_observations():
    left, right = _entity(), _entity()
    groups = await correlation_resolver.resolve_groups(
        uuid.uuid4(), [left, right], [_relationship(left, right, supports_group=False)]
    )
    assert len(groups) == 2
    assert all(len(group.entity_ids) == 1 for group in groups)


@pytest.mark.asyncio
async def test_identifier_bound_records_are_separated_from_groups():
    profile, record = _entity(), _entity("infostealer")
    groups = await correlation_resolver.resolve_groups(uuid.uuid4(), [profile, record], [])
    by_label = {group.label: group for group in groups}
    assert str(profile.id) in by_label["Grupo 01"].entity_ids
    assert str(record.id) in by_label["Registros del identificador consultado"].entity_ids
