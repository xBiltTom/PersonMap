"""Offline scheduling experiment: synthetic 1s/5s/slow sources, not a live SLA."""
import os
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import SecretStr
from app.core.config import settings
from app.engine.fair_engine import FairEngine
from app.engine.fair_plan import FairPlan, SourcePlan
from app.models.target import Target
from app.schemas.target import TargetCreate
from app.social.router import SocialSourceRouter
from app.tools.base import BaseTool, ToolCategory, ToolFinding
from app.tools.registry import tool_registry


async def benchmark(scale=1):
    settings.apify_enabled = True
    settings.apify_token = SecretStr("offline_simulation_no_real_credential")
    settings.apify_platforms = ["instagram"]
    timeline = []
    started = perf_counter()
    class SyntheticSource(BaseTool):
        category = ToolCategory.SOCIAL
        description = "OFFLINE SIMULATION"
        required_inputs = ["username", "candidate_urls"]
        def __init__(self, name, delay):
            self.name, self.delay = name, delay
        def can_run(self, context):
            if self.name == "apify_social":
                return bool(SocialSourceRouter().enrichment_requests(context))
            return bool(context.all_usernames())
        def input_fingerprint(self, context):
            return json.dumps([r.url for r in SocialSourceRouter().enrichment_requests(context)])
        async def execute(self, context):
            timeline.append({"source": self.name, "event": "started", "elapsed": perf_counter()-started})
            try:
                await asyncio.sleep(self.delay * scale)
                if self.name in {"social_verifier", "apify_social"}:
                    return [ToolFinding(entity_type="social_account", platform="instagram",
                        value="https://instagram.com/benchmarkperson", metadata_info={
                            "username": "benchmarkperson", "verification_status": "verified",
                            "provider": "simulation", "public_content": []})]
                return []
            except asyncio.CancelledError:
                timeline.append({"source": self.name, "event": "cancelled", "elapsed": perf_counter()-started})
                raise
            finally:
                timeline.append({"source": self.name, "event": "finished", "elapsed": perf_counter()-started})
    tools = [SyntheticSource("social_verifier", 1), SyntheticSource("gravatar_deep", 5),
             SyntheticSource("username_finder", 20), SyntheticSource("apify_social", .5)]
    tool_registry._tools = {tool.name: tool for tool in tools}
    plan = FairPlan(deadline_seconds=7*scale, finalization_seconds=.3*scale, cancellation_seconds=.3*scale,
        checkpoint_seconds=.1*scale, progress_interval_seconds=.1*scale,
        sources=tuple(SourcePlan(tool.name, index, 30*scale, max_invocations=1) for index, tool in enumerate(tools)))
    target = Target(id=uuid4(), **TargetCreate(usernames=[{"username": "benchmarkperson"}]).persistence_values())
    target.extra_data["subject_consent"] = True
    run = await FairEngine(plan=plan).collect_findings(str(uuid4()), target)
    snapshot = run.snapshot()
    starts = [item["elapsed"] for item in timeline if item["event"] == "started" and item["source"] != "apify_social"]
    report = {"kind": "offline_simulation_not_operational_sla", "scale": scale,
        "synthetic_delays_seconds": {tool.name: tool.delay*scale for tool in tools},
        "elapsed_seconds": run.elapsed_seconds, "deadline_seconds": plan.deadline_seconds,
        "timeline": timeline, "sources": snapshot["sources"], "pivots": snapshot["pivots"],
        "checks": {"concurrent_start": max(starts)-min(starts) < .5*scale,
            "bounded_return": run.elapsed_seconds <= plan.deadline_seconds + .1,
            "slow_cancelled": run.sources["username_finder"]["status"] == "timeout",
            "partial_findings_survive": len(run.findings) >= 2,
            "pivot_enriched_wave_two": any(a["wave"] == 2 for a in run.sources["apify_social"]["attempts"])}}
    assert all(report["checks"].values()), report["checks"]
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", type=float, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not .1 <= args.scale <= 2:
        parser.error("scale must be between 0.1 and 2")
    result = asyncio.run(benchmark(args.scale))
    if args.output:
        args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({key: result[key] for key in ("kind", "elapsed_seconds", "deadline_seconds", "checks")}, indent=2))
