"""
Tests del motor híbrido, la tercera estrategia del orquestador.

Todos en memoria: el LLM se sustituye por un doble que devuelve las
`tool_calls` que quiera el caso, y el despacho real de herramientas se
intercepta, de modo que la suite rápida los ejecuta sin red ni PostgreSQL.

Lo que se protege aquí es lo que distingue al híbrido del agente autónomo: que
la capa de IA **no repita** lo que ya hizo el barrido heurístico, que los
hallazgos queden etiquetados por capa, y que sin LLM configurado la
investigación se contabilice como lo que realmente fue (una corrida de reglas)
y no como híbrida.
"""

import importlib
import json
import uuid
from types import SimpleNamespace

import pytest

from app.api.v1.metrics import engine_of
from app.engine import hybrid_engine as hybrid_module
from app.engine.hybrid_engine import HEURISTIC_LAYER, REFINEMENT_LAYER, HybridEngine
from app.engine.persistence import dedupe_findings, normalize_source_tool
from app.engine.rule_engine import SweepResult, rule_engine
from app.models.entity import Entity
from app.models.target import Target
from app.tools.base import TargetContext, ToolFinding
from app.tools.registry import tool_registry

# El módulo, no la instancia homónima que exporta `app/agent/__init__.py`.
llm_client_module = importlib.import_module("app.agent.llm_client")


def _target(**kwargs) -> Target:
    defaults = dict(
        full_name="Juan Pérez",
        email="jperez@uni.edu.pe",
        username="jperez",
        phone=None,
        dni=None,
        university="UNMSM",
        description=None,
    )
    defaults.update(kwargs)
    return Target(**defaults)


def _sweep(findings=None, context=None, executed=None, rounds=1) -> SweepResult:
    return SweepResult(
        findings=list(findings or []),
        context=context or TargetContext(username="jperez", email="jperez@uni.edu.pe"),
        executed_runs=set(executed or []),
        rounds=rounds,
    )


def _tool_call(name: str, args: dict, call_id: str = "call_1") -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _llm_reply(tool_calls=None, content=None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


# --- Anti-repetición: la clave de ejecución ------------------------------


def test_run_key_matches_the_heuristic_sweep_for_the_same_call():
    """
    La capa 2 solo puede saltarse trabajo ya hecho si su clave de ejecución es
    la MISMA que registró la capa 1. Si las dos claves divergieran, el filtro
    quedaría mudo y el refinamiento repetiría el barrido entero.
    """
    engine = HybridEngine()
    tool = tool_registry.get_tool("username_finder")
    context = TargetContext(username="jperez")

    heuristic_key = rule_engine._get_tool_run_key(tool, context)
    llm_key = engine._run_key("username_finder", {"username": "jperez"}, context)

    assert llm_key == heuristic_key


def test_run_key_differs_for_a_username_the_sweep_never_tried():
    engine = HybridEngine()
    context = TargetContext(username="jperez")

    already = engine._run_key("username_finder", {"username": "jperez"}, context)
    novel = engine._run_key("username_finder", {"username": "juan.perez.dev"}, context)

    assert already != novel


def test_run_key_resolves_legacy_llm_aliases():
    """Un modelo entrenado con los prompts antiguos puede pedir `check_username`."""
    engine = HybridEngine()
    context = TargetContext(username="jperez")

    assert engine._run_key("check_username", {"username": "jperez"}, context) == (
        engine._run_key("username_finder", {"username": "jperez"}, context)
    )


# --- Capa 2: refinamiento ------------------------------------------------


@pytest.mark.asyncio
async def test_refinement_skips_calls_already_made_by_the_heuristic_sweep(monkeypatch):
    engine = HybridEngine()
    target = _target()
    context = TargetContext(username="jperez")
    tool = tool_registry.get_tool("username_finder")
    sweep = _sweep(
        context=context,
        executed=[rule_engine._get_tool_run_key(tool, context)],
    )

    dispatched: list[str] = []

    async def fake_dispatch(name, args, tgt, **kwargs):
        dispatched.append(args.get("username", ""))
        return [
            ToolFinding(
                entity_type="social_account",
                platform="mastodon",
                value="https://mastodon.social/@juan.perez.dev",
                confidence=0.8,
                metadata_info={"engine_layer": kwargs.get("engine_layer")},
            )
        ]

    replies = iter([
        _llm_reply(tool_calls=[
            # Ya la hizo la capa 1: debe descartarse sin gastar red.
            _tool_call("username_finder", {"username": "jperez"}, "c1"),
            # Variante nueva: debe ejecutarse.
            _tool_call("username_finder", {"username": "juan.perez.dev"}, "c2"),
        ]),
        _llm_reply(content="Sin más huecos que cubrir."),
    ])

    async def fake_acompletion(**kwargs):
        return next(replies)

    monkeypatch.setattr(hybrid_module, "dispatch_tool_call", fake_dispatch)
    monkeypatch.setattr(llm_client_module.litellm, "acompletion",fake_acompletion)
    monkeypatch.setattr(hybrid_module.settings, "llm_model", "test/model")
    monkeypatch.setattr(hybrid_module.settings, "llm_api_key", "k")
    monkeypatch.setattr(hybrid_module.settings, "hybrid_max_refinement_turns", 2)

    findings, turns, requested, skipped = await engine._refine_with_llm(
        "inv-1", target, sweep
    )

    assert dispatched == ["juan.perez.dev"], "la llamada repetida no debía ejecutarse"
    assert (requested, skipped) == (2, 1)
    assert turns == 2
    assert len(findings) == 1
    assert findings[0].metadata_info["engine_layer"] == REFINEMENT_LAYER


@pytest.mark.asyncio
async def test_refinement_stops_when_the_model_asks_for_nothing(monkeypatch):
    """Quedarse corto es preferible a añadir ruido: sin tool_calls, se cierra."""
    engine = HybridEngine()

    calls = {"n": 0}

    async def fake_acompletion(**kwargs):
        calls["n"] += 1
        return _llm_reply(content="El barrido heurístico ya es suficiente.")

    monkeypatch.setattr(llm_client_module.litellm, "acompletion",fake_acompletion)
    monkeypatch.setattr(hybrid_module.settings, "llm_model", "test/model")
    monkeypatch.setattr(hybrid_module.settings, "llm_api_key", "k")
    monkeypatch.setattr(hybrid_module.settings, "hybrid_max_refinement_turns", 3)

    findings, turns, requested, skipped = await engine._refine_with_llm(
        "inv-1", _target(), _sweep()
    )

    assert findings == []
    assert (turns, requested, skipped) == (1, 0, 0)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_refinement_failure_never_loses_the_heuristic_result(monkeypatch):
    """
    Si el proveedor del LLM cae, la capa 2 se abandona en silencio controlado.
    Lo que no puede pasar es que arrastre consigo el barrido de la capa 1.
    """
    engine = HybridEngine()

    async def exploding_acompletion(**kwargs):
        raise RuntimeError("429 rate limit")

    monkeypatch.setattr(llm_client_module.litellm, "acompletion",exploding_acompletion)
    monkeypatch.setattr(hybrid_module.settings, "llm_model", "test/model")
    monkeypatch.setattr(hybrid_module.settings, "llm_api_key", "k")

    findings, turns, requested, skipped = await engine._refine_with_llm(
        "inv-1", _target(), _sweep(findings=[_finding()])
    )

    assert findings == []
    assert requested == 0


def _finding(**kwargs) -> ToolFinding:
    defaults = dict(
        entity_type="social_account",
        platform="github",
        value="https://github.com/jperez",
        confidence=0.85,
        metadata_info={},
    )
    defaults.update(kwargs)
    return ToolFinding(**defaults)


# --- Resumen entregado al modelo -----------------------------------------


def test_digest_names_the_tools_that_already_ran_and_the_ones_that_did_not():
    engine = HybridEngine()
    context = TargetContext(username="jperez", discovered_emails=["otro@gmail.com"])
    sweep = _sweep(
        findings=[_finding()],
        context=context,
        executed=["username_finder|u:jperez"],
        rounds=2,
    )

    digest = engine._build_digest(_target(), sweep)

    assert "username_finder" in digest
    assert "HERRAMIENTAS QUE NO LLEGARON A EJECUTARSE" in digest
    assert "otro@gmail.com" in digest
    assert "2 ronda(s)" in digest


# --- Procedencia por capa ------------------------------------------------


def test_dedupe_keeps_both_layers_when_the_two_find_the_same_profile():
    """
    Un perfil hallado por las dos capas es UNA entidad, pero su procedencia debe
    recordar que ambas lo vieron: sin eso no se puede medir qué aporta la IA.
    """
    findings = [
        _finding(confidence=0.70, metadata_info={
            "source_tool": "username_finder",
            "engine_layer": HEURISTIC_LAYER,
        }),
        _finding(confidence=0.90, metadata_info={
            "source_tool": "social_verifier",
            "engine_layer": REFINEMENT_LAYER,
        }),
    ]

    deduped = dedupe_findings(findings)

    assert len(deduped) == 1
    assert deduped[0].metadata_info["engine_layers"] == [HEURISTIC_LAYER, REFINEMENT_LAYER]
    assert deduped[0].metadata_info["source_tools"] == ["username_finder", "social_verifier"]


@pytest.mark.asyncio
async def test_the_agentic_engine_does_not_claim_a_hybrid_layer(monkeypatch):
    """
    "Capa" significa exactamente "una de las dos mitades del motor híbrido". El
    agente autónomo tiene una sola, así que no debe etiquetar `engine_layer`: su
    procedencia va en el prefijo `agent:` del `source_tool`.
    """
    from app.agent.autonomous_agent import autonomous_agent
    from app.agent import tool_dispatch

    async def fake_execute(ctx):
        return [_finding(metadata_info={})]

    tool = tool_registry.get_tool("username_finder")
    monkeypatch.setattr(tool, "execute", fake_execute)

    findings = await autonomous_agent._execute_agent_tool(
        "inv-test", "username_finder", {"username": "jperez"}, _target()
    )

    assert findings[0].metadata_info["source_tool"] == "agent:username_finder"
    assert "engine_layer" not in findings[0].metadata_info


def test_dedupe_marks_a_profile_that_only_the_llm_found():
    findings = [
        _finding(metadata_info={"source_tool": "social_verifier", "engine_layer": REFINEMENT_LAYER})
    ]

    deduped = dedupe_findings(findings)

    assert deduped[0].metadata_info["engine_layers"] == [REFINEMENT_LAYER]


def test_source_tool_normalisation_survives_any_engine_prefix():
    """
    La guardia contra aristas tautológicas compara nombres de herramienta. Si un
    prefijo nuevo (`agent:`, `hybrid:`...) escapara sin normalizar, dos hermanos
    de enumeración dejarían de reconocerse y volverían las 3.835 aristas
    `same_username` que se eliminaron en la Fase 2.
    """
    assert normalize_source_tool("agent:username_finder") == "username_finder"
    assert normalize_source_tool("username_finder") == "username_finder"
    assert normalize_source_tool(None) == ""


# --- Clasificación por motor real ----------------------------------------


def _investigation(strategy: str, metrics: dict):
    return SimpleNamespace(id=uuid.uuid4(), strategy=strategy, metrics=metrics)


def test_engine_of_prefers_the_engine_that_actually_ran():
    inv = _investigation("hybrid", {"engine_used": "hybrid"})
    assert engine_of(inv) == "hybrid"


def test_engine_of_reclassifies_auto_without_llm_as_rules():
    """
    Ésta es la métrica que estaba mal: `auto` se contaba como agéntica aunque el
    orquestador hubiera caído al motor de reglas por no haber LLM.
    """
    assert engine_of(_investigation("auto", {"ai_enhanced": False})) == "rules"
    assert engine_of(_investigation("auto", {"ai_enhanced": True})) == "agentic"


def test_engine_of_does_not_credit_the_hybrid_when_it_degraded():
    assert engine_of(_investigation("hybrid", {"ai_enhanced": False})) == "rules"


def test_engine_of_handles_legacy_rows_without_metrics():
    assert engine_of(_investigation("rule_based", {})) == "rules"
    assert engine_of(_investigation("agentic", {})) == "rules"


# --- Arbitraje opcional --------------------------------------------------


def _entity(score: float, **kwargs) -> Entity:
    defaults = dict(
        id=uuid.uuid4(),
        investigation_id=uuid.uuid4(),
        entity_type="social_account",
        platform="github",
        value="https://github.com/jperez",
        display_name="jperez",
        metadata_info={},
        confidence=score,
        identity_score=score,
        verified=False,
        source_tool="username_finder",
    )
    defaults.update(kwargs)
    return Entity(**defaults)


def test_arbitration_only_considers_the_ambiguous_band():
    from app.identity.arbitration import select_ambiguous

    entities = [_entity(0.10), _entity(0.45), _entity(0.65), _entity(0.90)]

    picked = select_ambiguous(entities, limit=10)

    assert [e.identity_score for e in picked] == [0.65, 0.45]


def test_arbitration_never_second_guesses_a_manual_verification():
    from app.identity.arbitration import select_ambiguous

    entities = [_entity(0.50, verified=True), _entity(0.50)]

    assert len(select_ambiguous(entities, limit=10)) == 1


def test_arbitration_parses_a_json_wrapped_in_a_code_fence():
    from app.identity.arbitration import _parse_verdicts

    content = (
        '```json\n{"verdicts": [{"id": "abc", "verdict": "match", '
        '"rationale": "La bio cita la UNMSM."}]}\n```'
    )

    parsed = _parse_verdicts(content)

    assert parsed["abc"]["verdict"] == "match"


def test_arbitration_downgrades_an_unknown_verdict_to_uncertain():
    from app.identity.arbitration import _parse_verdicts

    parsed = _parse_verdicts('{"verdicts": [{"id": "x", "verdict": "quizá"}]}')

    assert parsed["x"]["verdict"] == "uncertain"


def test_arbitration_verdict_drives_clustering_without_touching_the_model_score():
    """
    El score persistido tiene que seguir siendo Fellegi-Sunter puro: es lo que
    miden el histograma y la curva de calibración del artículo. El arbitraje
    actúa como puntuación EFECTIVA solo para agrupar.
    """
    from app.identity.resolver import identity_resolver

    entity = _entity(0.55, metadata_info={
        "llm_arbitration": {"verdict": "match", "applied_score": 0.72, "model_score": 0.55}
    })

    assert identity_resolver._attribution(entity) == 0.72
    assert entity.identity_score == 0.55


def test_an_uncertain_verdict_leaves_the_model_in_charge():
    from app.identity.resolver import identity_resolver

    entity = _entity(0.55, metadata_info={
        "llm_arbitration": {"verdict": "uncertain", "applied_score": None}
    })

    assert identity_resolver._attribution(entity) == 0.55


# --- Contrato de la API ---------------------------------------------------


def test_hybrid_is_an_accepted_strategy():
    from app.schemas.investigation import InvestigationCreate

    payload = InvestigationCreate(target={"username": "jperez"}, strategy="hybrid")

    assert payload.strategy == "hybrid"


def test_the_three_original_strategies_still_validate():
    from app.schemas.investigation import InvestigationCreate

    for strategy in ("auto", "rule_based", "agentic"):
        assert InvestigationCreate(
            target={"username": "jperez"}, strategy=strategy
        ).strategy == strategy


def test_a_misspelled_strategy_is_rejected_instead_of_silently_downgraded():
    """
    Antes `strategy` era un `str` libre: "hybird" devolvía HTTP 201 y la
    investigación caía al motor de reglas, contaminando la muestra del artículo
    con una condición experimental que nadie pidió.
    """
    from app.schemas.investigation import InvestigationCreate

    with pytest.raises(ValueError):
        InvestigationCreate(target={"username": "jperez"}, strategy="hybird")
