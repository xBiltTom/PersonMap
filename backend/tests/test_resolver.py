"""
Tests de la agrupación en clusters de identidad.

Cubren la propiedad que da sentido al clustering frente a clasificar cada
entidad por separado: la evidencia directa es **transitiva**. Si A está probado
y B está unido a A por un correo compartido, B queda confirmado aunque su
puntuación aislada no alcance el umbral.
"""

import uuid

import pytest

from app.identity.resolver import UnionFind, identity_resolver
from app.models.entity import Entity
from app.models.relationship import Relationship
from app.models.target import Target


def _entity(identity_score: float, *, verified: bool = False, platform: str = "github") -> Entity:
    return Entity(
        id=uuid.uuid4(),
        investigation_id=uuid.uuid4(),
        entity_type="social_account",
        platform=platform,
        value=f"https://{platform}.com/u{uuid.uuid4().hex[:6]}",
        display_name="perfil",
        metadata_info={},
        confidence=identity_score,
        identity_score=identity_score,
        existence_confidence=0.9,
        verified=verified,
        source_tool="test",
    )


def _rel(a: Entity, b: Entity, relation_type: str) -> Relationship:
    return Relationship(
        id=uuid.uuid4(),
        investigation_id=a.investigation_id,
        source_entity_id=a.id,
        target_entity_id=b.id,
        relation_type=relation_type,
        strength=0.95,
    )


def _labels(clusters) -> dict:
    return {c.scoring_breakdown["status"]: c for c in clusters}


# --- Union-find ----------------------------------------------------------


def test_union_find_is_transitive():
    uf = UnionFind(["a", "b", "c", "d"])
    uf.union("a", "b")
    uf.union("b", "c")

    groups = {frozenset(g) for g in uf.groups().values()}
    assert frozenset({"a", "b", "c"}) in groups
    assert frozenset({"d"}) in groups


def test_union_find_ignores_unknown_items():
    uf = UnionFind(["a"])
    uf.union("a", "inexistente")
    assert len(uf.groups()) == 1


# --- Agrupación ----------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_evidence_propagates_certainty():
    """
    El caso que justifica el clustering: una cuenta con evidencia débil por sí
    sola queda confirmada si está unida por evidencia directa a otra probada.
    """
    probado = _entity(0.95, platform="keybase")
    debil = _entity(0.45, platform="reddit")
    target = Target(full_name="Ana Ramirez")

    clusters = await identity_resolver.resolve_clusters(
        uuid.uuid4(), [probado, debil], target, [_rel(probado, debil, "uses_email")]
    )

    confirmed = _labels(clusters)["confirmed"]
    assert {str(probado.id), str(debil.id)} == set(confirmed.entity_ids)
    assert "unidos por evidencia directa" in confirmed.reasoning


@pytest.mark.asyncio
async def test_same_username_does_not_merge_identities():
    """
    Compartir alias NO es evidencia de identidad: es exactamente el escenario
    del homónimo que el sistema debe separar. Solo `uses_email`, `linked_to` y
    `same_avatar` unen componentes.
    """
    probado = _entity(0.95)
    homonimo = _entity(0.20, platform="instagram")
    target = Target(full_name="Ana Ramirez")

    clusters = await identity_resolver.resolve_clusters(
        uuid.uuid4(), [probado, homonimo], target, [_rel(probado, homonimo, "same_username")]
    )

    by_status = _labels(clusters)
    assert by_status["confirmed"].entity_ids == [str(probado.id)]
    assert by_status["homonym_discarded"].entity_ids == [str(homonimo.id)]


@pytest.mark.asyncio
async def test_clusters_use_identity_score_not_tool_confidence():
    """
    Agrupar por `confidence` dejaba la decisión en manos de la constante que
    cada herramienta escribe a mano. Debe mandar `identity_score`.
    """
    entity = _entity(0.10)
    entity.confidence = 0.99  # lo que reportaría una tool optimista
    entity.existence_confidence = 0.99

    clusters = await identity_resolver.resolve_clusters(
        uuid.uuid4(), [entity], Target(full_name="Ana Ramirez"), []
    )

    assert _labels(clusters).keys() == {"homonym_discarded"}


@pytest.mark.asyncio
async def test_manual_verification_overrides_the_model():
    entity = _entity(0.05, verified=True)

    clusters = await identity_resolver.resolve_clusters(
        uuid.uuid4(), [entity], Target(full_name="Ana Ramirez"), []
    )

    assert _labels(clusters)["confirmed"].entity_ids == [str(entity.id)]


@pytest.mark.asyncio
async def test_cluster_reports_attribution_statistics():
    """El desglose alimenta la distribución de puntuaciones del artículo."""
    clusters = await identity_resolver.resolve_clusters(
        uuid.uuid4(),
        [_entity(0.95), _entity(0.75)],
        Target(full_name="Ana Ramirez"),
        [],
    )

    breakdown = _labels(clusters)["confirmed"].scoring_breakdown
    assert breakdown["attribution_min"] == 0.75
    assert breakdown["attribution_max"] == 0.95
    assert breakdown["attribution_mean"] == 0.85


@pytest.mark.asyncio
async def test_no_entities_yields_no_clusters():
    assert await identity_resolver.resolve_clusters(uuid.uuid4(), [], Target(), []) == []
