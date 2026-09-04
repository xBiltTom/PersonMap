"""
Tests del scorecard de exposición.

Cubren en particular la regla del proyecto de que **todo `entity_type` nuevo
debe ponderar en el riesgo y llevar su recomendación pedagógica**: hasta ahora
`image_match`, `google_account` y `academic_profile` -- que el backend ya
emitía -- sumaban exactamente cero al score y no generaban ningún consejo.
"""

import uuid

from app.identity.risk import calculate_risk_score
from app.models.entity import Entity
from app.models.target import Target


def _entity(entity_type: str, metadata: dict | None = None, confidence: float = 0.9) -> Entity:
    return Entity(
        id=uuid.uuid4(),
        investigation_id=uuid.uuid4(),
        entity_type=entity_type,
        platform=None,
        value="valor",
        display_name="valor",
        metadata_info=metadata or {},
        confidence=confidence,
        verified=False,
        source_tool="test",
    )


def _target() -> Target:
    return Target(full_name="Juan Perez", email="jperez@uni.edu.pe")


def _titles(recommendations) -> list[str]:
    return [r["title"] for r in recommendations]


def test_baseline_without_findings():
    score, level, recs = calculate_risk_score([], _target())
    assert score == 10
    assert level == "BAJO"
    # Siempre hay al menos una recomendación, aunque sea la de higiene.
    assert _titles(recs) == ["Huella Digital Controlada"]


def test_every_recommendation_has_the_expected_shape():
    entities = [
        _entity("breach", {"breaches": ["LinkedIn"]}),
        _entity("phone"),
        _entity("google_account"),
        _entity("image_match"),
        _entity("academic_profile"),
        _entity("domain"),
        _entity("infostealer", {"computer_name": "DESKTOP-X", "total_user_services": 32}),
    ]
    _, _, recs = calculate_risk_score(entities, _target())

    assert recs, "deberia emitirse al menos una recomendacion"
    for rec in recs:
        assert set(rec.keys()) == {"title", "category", "impact", "description", "advice"}
        assert all(isinstance(v, str) and v for v in rec.values())
        assert rec["impact"] in {"Crítico", "Alto", "Medio", "Bajo"}


def test_orphan_entity_types_now_affect_the_score():
    """Antes estos tres tipos no aparecían en ninguna rama de puntuación."""
    target = _target()
    baseline, _, _ = calculate_risk_score([], target)

    for entity_type in ("google_account", "image_match", "academic_profile", "domain"):
        score, _, recs = calculate_risk_score([_entity(entity_type)], target)
        assert score > baseline, f"{entity_type} no altera el score"
        assert len(recs) >= 1
        assert _titles(recs) != ["Huella Digital Controlada"], (
            f"{entity_type} no genera recomendacion propia"
        )


def test_infostealer_is_more_severe_than_a_breach():
    """
    Un infostealer implica un equipo comprometido y contraseñas en claro; una
    brecha, solo que un tercero perdió una base de datos.
    """
    target = _target()
    breach_score, _, _ = calculate_risk_score(
        [_entity("breach", {"breaches": ["Adobe"]})], target
    )
    stealer_score, stealer_level, recs = calculate_risk_score(
        [_entity("infostealer", {"computer_name": "DESKTOP-X", "total_user_services": 32})],
        target,
    )

    assert stealer_score > breach_score
    assert stealer_level in {"ALTO", "CRÍTICO"}
    # La recomendación del infostealer debe ir la primera, por gravedad.
    assert recs[0]["title"].startswith("Credenciales Robadas por Malware")
    assert recs[0]["impact"] == "Crítico"


def test_infostealer_recommendation_mentions_session_cookies():
    """
    El consejo clave y contraintuitivo: cambiar la contraseña no basta, porque
    la cookie de sesión robada sigue siendo válida.
    """
    _, _, recs = calculate_risk_score(
        [_entity("infostealer", {"computer_name": "PC-AULA", "total_user_services": 12})],
        _target(),
    )
    advice = recs[0]["advice"].lower()
    assert "cookie" in advice
    assert "sesion" in advice or "sesión" in advice


def test_score_is_capped_at_100():
    entities = [_entity("infostealer", {"total_user_services": 99})]
    entities += [_entity("breach", {"breaches": ["A", "B", "C"]}) for _ in range(5)]
    entities += [_entity("social_account") for _ in range(20)]
    entities += [_entity("email", {"is_academic": True}) for _ in range(10)]

    score, level, _ = calculate_risk_score(entities, _target())

    assert score == 100
    assert level == "CRÍTICO"
