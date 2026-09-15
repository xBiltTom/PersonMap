"""
Qué pasa cuando el proveedor de IA no responde.

Caso real (investigación c79b9d92, 2026-09-10): Gemini devolvió 503 "This model
is currently experiencing high demand" en el primer turno del agente. La consola
decía "Aplicando motor heurístico complementario..." pero no se aplicaba nada:
la investigación terminó sin ejecutar una sola herramienta, con 0 hallazgos,
riesgo BAJO y la recomendación "Huella Digital Controlada".
"""

import importlib

import pytest

from app.agent import autonomous_agent as agent_module
from app.engine.rule_engine import SweepResult, rule_engine
from app.models.target import Target
from app.tools.base import ToolFinding

# El módulo, no la instancia: `app/agent/__init__.py` exporta el objeto
# `llm_client` con el mismo nombre y `from app.agent import llm_client` lo devuelve.
llm_module = importlib.import_module("app.agent.llm_client")


class Saturated(Exception):
    """Lo mínimo de un 503 de LiteLLM que mira el cliente: el código."""

    status_code = 503


@pytest.fixture
def no_waiting(monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_DELAYS_SECONDS", (0.0, 0.0))


@pytest.mark.asyncio
async def test_transient_error_is_retried_before_giving_up(monkeypatch, no_waiting):
    calls = []

    async def acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            raise Saturated("This model is currently experiencing high demand")
        return "respuesta"

    monkeypatch.setattr(llm_module.litellm, "acompletion", acompletion)
    retries = []

    async def on_retry(attempt, delay, err):
        retries.append(attempt)

    result = await llm_module.complete_with_retries(model="m", messages=[], on_retry=on_retry)

    assert result == "respuesta"
    assert len(calls) == 3
    assert retries == [1, 2]
    # `on_retry` es del cliente, no un parámetro para el proveedor.
    assert all("on_retry" not in c for c in calls)


@pytest.mark.asyncio
async def test_request_errors_are_not_retried(monkeypatch, no_waiting):
    """Una clave inválida no se arregla esperando: se avisa a la primera."""
    calls = []

    async def acompletion(**kwargs):
        calls.append(kwargs)
        raise ValueError("API key not valid")

    monkeypatch.setattr(llm_module.litellm, "acompletion", acompletion)

    with pytest.raises(ValueError):
        await llm_module.complete_with_retries(model="m", messages=[])
    assert len(calls) == 1


def test_error_is_described_in_one_readable_line():
    assert llm_module.describe_llm_error(Saturated('{\n "error": {\n  "code": 503')) == (
        "el modelo de IA está saturado (503)"
    )


@pytest.mark.asyncio
async def test_agent_runs_the_heuristic_sweep_when_the_llm_stays_down(monkeypatch, no_waiting):
    async def saturated(**kwargs):
        raise Saturated("This model is currently experiencing high demand")

    monkeypatch.setattr(llm_module.litellm, "acompletion", saturated)
    monkeypatch.setattr(agent_module.settings, "llm_model", "gemini/test")
    monkeypatch.setattr(agent_module.settings, "llm_api_key", "clave-de-prueba")

    events = []

    async def publish(investigation_id, event):
        events.append(event)

    monkeypatch.setattr(agent_module.event_bus, "publish", publish)

    finding = ToolFinding(
        entity_type="social_account",
        platform="github",
        value="https://github.com/JorgeWueder",
        confidence=0.95,
        metadata_info={"source_tool": "github_deep_scanner"},
    )

    async def sweep(investigation_id, target):
        return SweepResult(findings=[finding], rounds=1)

    monkeypatch.setattr(rule_engine, "collect_findings", sweep)

    persisted = []

    async def persist(**kwargs):
        persisted.extend(kwargs["findings"])
        return ["entidad"]

    async def relationships(*args, **kwargs):
        return []

    monkeypatch.setattr(agent_module, "persist_findings", persist)
    monkeypatch.setattr(agent_module, "build_relationships", relationships)

    run = await agent_module.autonomous_agent.run(
        "inv-test", Target(full_name="Jorge Wueder", username="JorgeWueder"), db=None
    )

    assert persisted == [finding]
    assert run.entities == ["entidad"]
    assert run.stats["agent_fallback_to_rules"] is True
    assert run.stats["agent_tools_executed"] == 0
    assert run.stats["agent_llm_error"] == "el modelo de IA está saturado (503)"

    phases = [e.get("phase") for e in events]
    assert phases.count("agent_retry") == 2
    assert "agent_fallback" in phases
