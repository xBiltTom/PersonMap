"""
Tests del modelo de resolución de identidad (Fellegi-Sunter de tres estados).

El conjunto etiquetado de `fixtures/identity_ground_truth.json` cumple aquí dos
funciones: es el test de regresión que protege cualquier recalibrado del scorer
y es la fuente de la tabla de precisión/exhaustividad reportable en el artículo.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from app.identity.scorer import (
    PRIOR_MATCH_PROBABILITY,
    SCORER_VERSION,
    SIGNALS,
    compute_identity_score,
)
from app.models.target import Target

GROUND_TRUTH = json.loads(
    (Path(__file__).parent / "fixtures" / "identity_ground_truth.json").read_text(
        encoding="utf-8"
    )
)

# Umbral de decisión: por encima, el hallazgo se atribuye al objetivo. Es el
# mismo `CONFIRMED_THRESHOLD` que usa el resolutor para formar clusters.
DECISION_THRESHOLD = 0.70


def _target(key: str) -> Target:
    spec = GROUND_TRUTH["targets"][key]
    return Target(**{k: v for k, v in spec.items() if v is not None})


def _score_case(case: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    return compute_identity_score(
        display_name=case.get("display_name"),
        value=case["value"],
        metadata=case.get("metadata", {}),
        target=_target(case["target"]),
    )


def _all_cases() -> List[Dict[str, Any]]:
    return GROUND_TRUTH["cases"]


# --- Corrección estructural del modelo -----------------------------------


def test_no_evidence_yields_the_prior():
    """
    Sin ninguna señal evaluable, la probabilidad posterior debe ser la previa.

    Es la propiedad que rompía el modelo anterior: codificaba "dato ausente"
    como "desacuerdo", de modo que el caso base sumaba -31.6 bits y caía al
    suelo del recorte (0.05) en lugar de quedarse en 0.02.
    """
    target = Target(full_name=None, email=None, username=None, university=None, phone=None)
    score, breakdown = compute_identity_score(None, "https://ejemplo.pe", {}, target)

    assert breakdown["signals_evaluated"] == 0
    assert breakdown["log_likelihood_ratio"] == 0.0
    assert score == pytest.approx(PRIOR_MATCH_PROBABILITY, abs=0.01)


def test_missing_field_is_not_a_disagreement():
    """
    Un objetivo sin teléfono no debe ser penalizado por la señal de teléfono.

    Antes `phone_match` valía 0.0 y restaba 4.32 bits aunque no hubiera nada que
    comparar.
    """
    sin_telefono = Target(full_name="Ana Ramirez", university="UNMSM")
    metadata = {"og_title": "Ana Ramirez", "bio": "Estudiante en UNMSM"}

    _, breakdown = compute_identity_score("Ana Ramirez", "https://x.pe/ana", metadata, sin_telefono)

    assert breakdown["phone_match_applicable"] is False
    assert breakdown["phone_match_weight"] == 0.0


def test_enumerated_username_is_not_evidence():
    """
    Si el hallazgo viene de enumerar el alias del objetivo en cientos de
    plataformas, la coincidencia está garantizada por el método de búsqueda.
    Tratarla como evidencia hacía que las cuentas de la cola larga heredaran una
    confianza que nadie había demostrado.
    """
    target = _target("estudiante_unt")
    metadata = {"source_tool": "username_finder", "username": "cmendoza_dev"}

    _, breakdown = compute_identity_score(
        "cmendoza_dev", "https://foro.example/cmendoza_dev", metadata, target
    )

    assert breakdown["username_match_applicable"] is False

    # La misma coincidencia hallada por otra vía SÍ es evidencia.
    metadata_independiente = {"source_tool": "social_verifier", "username": "cmendoza_dev"}
    _, breakdown2 = compute_identity_score(
        "cmendoza_dev", "https://foro.example/cmendoza_dev", metadata_independiente, target
    )
    assert breakdown2["username_match_applicable"] is True
    assert breakdown2["username_match"] == 1.0


def test_scores_are_not_trimodal():
    """
    La distribución debe ser continua.

    El modelo anterior solo producía {0.05, 0.45, 0.95} porque los atajos
    `max(posterior, ...)` aplastaban todo lo intermedio, dejando inalcanzable el
    umbral de 0.70 del resolutor por la vía del modelo.
    """
    scores = {_score_case(c)[0] for c in _all_cases()}
    assert len(scores) >= 6, f"distribucion demasiado discreta: {sorted(scores)}"


def test_breakdown_is_self_describing():
    score, breakdown = _score_case(_all_cases()[0])

    assert breakdown["scorer_version"] == SCORER_VERSION
    assert 0.0 <= score <= 1.0
    for signal in SIGNALS:
        assert f"{signal.name}_applicable" in breakdown
        assert f"{signal.name}_weight" in breakdown


def test_signal_parameters_are_valid_probabilities():
    for signal in SIGNALS:
        assert 0.0 < signal.u < signal.m < 1.0, f"{signal.name}: m debe superar a u"
        # Una señal con poder discriminante nulo o negativo no aporta nada.
        assert signal.weight_agree > 0, f"{signal.name} no discrimina"


# --- Evaluación contra el conjunto etiquetado ----------------------------


@pytest.mark.parametrize("case", _all_cases(), ids=lambda c: c["id"])
def test_ground_truth_case(case: Dict[str, Any]):
    """Cada caso etiquetado debe caer del lado correcto del umbral de decisión."""
    score, breakdown = _score_case(case)

    if case["is_match"]:
        assert score >= DECISION_THRESHOLD, (
            f"falso negativo en '{case['id']}' (score {score}): {case['rationale']}"
        )
    else:
        assert score < DECISION_THRESHOLD, (
            f"falso positivo en '{case['id']}' (score {score}): {case['rationale']}"
        )


def test_ground_truth_precision_and_recall():
    """
    Métrica agregada del conjunto etiquetado; es la tabla que va al artículo.

    Se exige perfección porque el conjunto es pequeño y curado a mano: cualquier
    error indica una regresión real del modelo, no ruido estadístico.
    """
    tp = fp = tn = fn = 0
    for case in _all_cases():
        predicted = _score_case(case)[0] >= DECISION_THRESHOLD
        actual = case["is_match"]
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    print(
        f"\n[ground truth] n={tp + fp + tn + fn} "
        f"TP={tp} FP={fp} TN={tn} FN={fn} "
        f"precision={precision:.2f} recall={recall:.2f}"
    )

    assert precision == 1.0, f"{fp} falso(s) positivo(s)"
    assert recall == 1.0, f"{fn} falso(s) negativo(s)"
