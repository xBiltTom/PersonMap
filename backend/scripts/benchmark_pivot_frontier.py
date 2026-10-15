"""Offline, reproducible admission benchmark against a real baseline RuleEngine.

Run from backend: .venv/bin/python scripts/benchmark_pivot_frontier.py
All requests go through MockTransport. Results are fixture observations, never
measurements of live OSINT coverage or identity attribution.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types
from statistics import median
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import httpx
from app.core.config import settings
from app.engine.pivot_frontier import PivotFrontier, context_inputs, pivot_id
from app.engine.rule_engine import RuleEngine
from app.models.target import Target
from app.tools.base import TargetContext, ToolFinding
from app.tools.registry import tool_registry

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def load_scenario():
    scenario = json.loads((FIXTURES / "pivot_frontier_scenario.json").read_text())
    reference = json.loads((FIXTURES / scenario["base_fixture"]).read_text())
    record = next(c for c in reference["cases"] if c["id"] == scenario["profile_case"])
    email = record["metadata"]["emails"][0]
    target = Target(username=reference["targets"][scenario["target_key"]]["username"])
    findings = [
        ToolFinding(entity_type="search_mention", value=scenario["weak_source"], metadata_info={
            "extracted_emails": [scenario["weak_email"]]}),
        ToolFinding(entity_type="document", value=scenario["contextual_source"], metadata_info={
            "source_kind": "public_document", "extracted_emails": [scenario["contextual_email"]]}),
        ToolFinding(entity_type="social_account", value=record["value"], metadata_info={
            **record["metadata"], "profile_email": email, "verification_status": "verified"}),
    ]
    return scenario, target, findings, email


def baseline_engine(ref):
    code = subprocess.check_output(["git", "show", f"{ref}:backend/app/engine/rule_engine.py"], text=True)
    module = types.ModuleType("personmap_baseline_rule_engine")
    sys.modules[module.__name__] = module
    exec(compile(code, f"git:{ref}:rule_engine.py", "exec"), module.__dict__)
    return module.RuleEngine(), hashlib.sha256(code.encode()).hexdigest()


class Discovery:
    name = "fixture_discovery"
    description = "Recorded discovery observations"
    required_inputs = ["username"]

    def __init__(self, findings):
        self.findings = findings

    def can_run(self, context):
        return bool(context.all_usernames())

    async def execute(self, context):
        return [f.model_copy(deep=True) for f in self.findings]


class Lookup:
    name = "fixture_lookup"
    description = "One mocked API lookup per email with a shared request cap"
    required_inputs = ["email"]

    def __init__(self, scenario, strong_email):
        self.scenario, self.strong_email = scenario, strong_email
        self.checked, self.order, self.requests = set(), [], 0

    def can_run(self, context):
        return len(self.checked) < self.scenario["lookup_request_budget"] and any(e not in self.checked for e in context.all_emails())

    async def execute(self, context):
        findings = []
        def reply(request):
            self.requests += 1
            return httpx.Response(200, json={"observed": True})
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            for email in context.all_emails():
                if len(self.checked) >= self.scenario["lookup_request_budget"]:
                    break
                if email in self.checked:
                    continue
                await client.get("https://lookup.example/public", params={"email": email})
                self.checked.add(email)
                self.order.append(email)
                level = "strong" if email == self.strong_email else "weak" if email == self.scenario["weak_email"] else "contextual"
                findings.append(ToolFinding(entity_type="email", value=email, metadata_info={"fixture_evidence": level}))
        return findings


async def run(engine, enabled):
    scenario, target, discoveries, strong_email = load_scenario()
    lookup, source = Lookup(scenario, strong_email), Discovery(discoveries)
    tools = {tool.name: tool for tool in (source, lookup)}
    with patch.object(tool_registry, "_tools", tools), patch.object(settings, "pivot_frontier_enabled", enabled), \
         patch.object(settings, "pivot_max_per_round", scenario["max_pivots_per_round"]), \
         patch.object(settings, "pivot_max_weak_per_round", 0), \
         patch.object(settings, "pivot_max_total", 128), patch.object(settings, "pivot_min_priority", 0), \
         patch.object(settings, "pivot_round_cost_budget", 100), patch.object(settings, "pivot_corroboration_bonus", 30):
        started = time.perf_counter()
        result = await engine.collect_findings("offline-frontier-benchmark", target)
        elapsed = round(time.perf_counter() - started, 6)
        frontier = PivotFrontier(result.context)
        frontier.sync(result.rounds)
        unique = {pivot_id(kind, value) for kind, value in context_inputs(result.context)}
        # Count actual lookup inputs, rather than equating dispatch with proof
        # that every tool consumed every supplied input.
        return {"tool_executions": len(result.executed_runs), "requests": lookup.requests,
            "runtime_seconds": elapsed, "unique_pivots_discovered": len(unique) - 1,
            "total_pivots_including_seed": len(unique),
            "pivots_explored": len(lookup.checked) + 1, "pivots_deferred": len(unique) - len(lookup.checked) - 1,
            "strong_findings": sum(f.metadata_info.get("fixture_evidence") == "strong" for f in result.findings),
            "weak_findings": sum(f.metadata_info.get("fixture_evidence") == "weak" for f in result.findings),
            "contextual_findings": sum(f.metadata_info.get("fixture_evidence") == "contextual" for f in result.findings),
            "duplicate_executions_avoided": frontier.duplicate_executions_avoided if enabled else None,
            "lookup_order": lookup.order, "frontier_summary": frontier.snapshot()["summary"] if enabled else None,
            "retained_emails": result.context.all_emails()}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-ref", default="3f054bf")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    original, sha = baseline_engine(args.baseline_ref)
    # Warm the shared URL-template catalog outside both timing windows.
    from app.tools.maigret_ids import identifiers_from_url
    identifiers_from_url("https://github.com/cmendoza_dev")
    before, after = [], []
    for _ in range(3):
        before.append(await run(original, False))
        after.append(await run(RuleEngine(), True))
    def measured(trials):
        return {**trials[-1], "runtime_seconds": round(median(t["runtime_seconds"] for t in trials), 6),
                "runtime_trials_seconds": [t["runtime_seconds"] for t in trials]}
    report = {"baseline_ref": args.baseline_ref, "baseline_rule_engine_sha256": sha,
        "after_ref": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "frontier_implementation_sha256": hashlib.sha256((Path(__file__).resolve().parents[1] /
            "app/engine/pivot_frontier.py").read_bytes()).hexdigest(),
        "fixture": "tests/fixtures/pivot_frontier_scenario.json", "network": "httpx.MockTransport only",
        "semantics": "ordering under identical two-request lookup budgets; fixture labels are evidence roles, not ownership",
        "notes": ["Median of three warm alternating runs; local fixture timings are not production latency.",
                  "strong/weak/contextual findings count follow-up lookup results, excluding discovery observations shared by both conditions.",
                  "pivots_deferred counts retained unqueried inputs, including URL pivots without a fixture consumer.",
                  "The baseline did not instrument duplicate-execution avoidance; null means not measured."],
        "before": measured(before), "after": measured(after)}
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(content)
    print(content, end="")


if __name__ == "__main__":
    asyncio.run(main())
