"""Bounded, event-driven acquisition using ordinary tools, Frontier and evidence tables."""
import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import httpx
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.core.events import event_bus
from app.core.config import settings
from app.core.runtime import durable_runtime, search_limit
from app.engine.fair_plan import FairPlan
from app.engine.persistence import finding_dedupe_key, entity_dedupe_key, persist_findings
from app.engine.pivot_frontier import PivotFrontier, pivot_id, context_inputs, tool_accepts, PRIMARY, DISCOVERED
from app.engine.pivot_rules import extract_and_apply_pivots
from app.engine.rule_engine import RuleEngine
from app.engine.trace import PendingObservation, safe_input_summary, trace_recorder
from app.schemas.fair import FairProgress, FairSnapshot
from app.tools.acquisition_observation import capture
from app.tools.base import TargetContext, ToolFinding
from app.tools.registry import tool_registry


FAILURE_STATES = {"partial", "timeout", "failed", "budget_exhausted", "provider_unavailable"}
PROVIDER_ERRORS = {"actor_build_not_found", "actor_access_denied", "disabled", "token_missing", "session_missing", "session_expired", "invalid_session",
    "runtime_missing", "session_not_configured", "dependency_missing", "authentication_failed", "access_denied", "quota_exhausted", "rate_limited", "blocked", "blocked_response", "http_401", "http_402", "http_403", "http_429", "http_432", "http_433"}
BUDGET_ERRORS = {"run_budget_exhausted", "actor_budget_exhausted", "charge_budget_exhausted",
    "profile_budget_exhausted", "budget_exhausted", "request_budget_exhausted", "time_budget_exhausted"}


def reference(key):
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:24]


def aggregate(state):
    attempts = state["attempts"]
    if any(item["status"] == "running" for item in attempts):
        return "running"
    statuses = {item["status"] for item in attempts}
    if not statuses:
        return state["status"]
    if statuses == {"completed"}:
        return "completed"
    if "completed" in statuses or state["findings_count"]:
        return "partial"
    return next((status for status in ("timeout", "failed", "provider_unavailable", "budget_exhausted", "skipped")
                 if status in statuses), "not_applicable")


def diagnostic_statuses(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"status", "error", "outcome"} and isinstance(item, str):
                yield item
            elif isinstance(item, (list, dict)):
                yield from diagnostic_statuses(item)
    elif isinstance(value, list):
        for item in value:
            yield from diagnostic_statuses(item)


def classify(tool, view, findings, health):
    codes, errors = health["statuses"], health["errors"]
    fields = {"apify_social": ("apify_runtime",), "ghunt": ("ghunt_diagnostics",),
        "academic_finder": ("academic_diagnostics",), "email_enumerator": ("email_enum_diagnostics",),
        "google_account_osint": ("google_public_diagnostics",),
        "search_dorker": ("search_diagnostics", "search_last_status")}.get(tool.name, (tool.name + "_diagnostics",))
    diagnostics = {key: view.extra[key] for key in fields if key in view.extra}
    states = set(diagnostic_statuses(diagnostics))
    if isinstance(view.extra.get("search_last_status"), str) and tool.name == "search_dorker":
        states.add(view.extra["search_last_status"])
    if codes.intersection({401, 402, 403, 429}) or states.intersection(PROVIDER_ERRORS):
        outcome = "provider_unavailable"
    elif any("Timeout" in error for error in errors):
        outcome = "timeout"
    elif any(code >= 500 for code in codes) or errors or states.intersection({"worker_error", "network_error", "upstream_error", "adapter_error", "request_error", "invalid_json", "invalid_payload",
        "start_uncertain", "abort_failed", "no_usable_public_rows", "empty_dataset", "actor_run_failed"}):
        outcome = "failed"
    elif tool.name == "ghunt" and len(view.all_emails()) > len(view.extra.get("ghunt_checked", [])):
        outcome = "budget_exhausted"
    elif tool.name == "search_dorker" and hasattr(tool, "pending_queries") and tool.pending_queries(view) and (
            view.extra.get("search_queries_used", 0) >= view.extra.get("search_query_limit", float("inf"))):
        outcome = "budget_exhausted"
    elif states.intersection(BUDGET_ERRORS):
        outcome = "budget_exhausted"
    elif states.intersection({"timeout", "batch_timeout", "batch_timeout_or_cancelled", "deadline_exceeded"}):
        outcome = "timeout"
    else:
        outcome = "completed"
    if outcome != "completed" and findings:
        return "partial", outcome
    return outcome, None if outcome == "completed" else outcome


@dataclass
class FairRun:
    context: TargetContext
    plan: FairPlan
    started: float
    findings: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)
    jobs: dict = field(default_factory=dict)
    entity_ids: dict = field(default_factory=dict)
    phase: str = "wave_0"
    deadline_reached: bool = False
    cleanup_pending: bool = False
    persistence: str = "not_requested"
    persistence_errors: int = 0
    elapsed_seconds: float = 0

    def progress(self):
        from app.social.capabilities import ACTORS
        social = {platform: {"status": "skipped", "reason": "not_in_fair_allowlist" if platform not in self.plan.apify_platforms
                  else "not_requested"} for platform in [*ACTORS, "reddit", "twitter", "facebook", "linkedin"]}
        from app.social.router import SocialSourceRouter
        from app.core.config import settings
        decisions = SocialSourceRouter().plan(PivotFrontier(self.context).execution_view())
        for decision in decisions:
            if decision.platform in ACTORS:
                parent = self.sources.get("apify_social", {})
                social[decision.platform] = {"status": parent.get("status", "skipped"), "reason": decision.reason}
        for record in self.context.extra.get("apify_runtime", {}).get("runs", {}).values():
            raw = record.get("outcome") or record.get("status")
            state = ("running" if raw in {"reserved", "READY", "RUNNING", "SUCCEEDED"} else "completed" if raw == "observed"
                     else "partial" if raw == "partial" else "timeout" if "timeout" in str(raw).lower()
                     else "failed")
            social[record["platform"]] = {"status": state, "reason": raw}
        if "search_dorker" in self.sources:
            self.sources["search_dorker"].update(queries_used=self.context.extra.get("search_queries_used", 0),
                query_budget=search_limit(self.context, settings.search_query_budget))
        return FairProgress(phase=self.phase, elapsed_seconds=self.elapsed_seconds,
            deadline_seconds=self.plan.deadline_seconds, sources=self.sources, social_sources=social).model_dump(mode="json")

    def snapshot(self, registry=tool_registry):
        refs = {}
        for finding in self.findings:
            key = reference(finding_dedupe_key(finding))
            item = refs.setdefault(key, {"key": key, "entity_id": self.entity_ids.get(key),
                "entity_type": finding.entity_type, "platform": finding.platform, "source_tools": [],
                "content_count": 0})
            tool = finding.metadata_info.get("source_tool")
            if tool and tool not in item["source_tools"]:
                item["source_tools"].append(tool)
            item["content_count"] = max(item["content_count"], len(finding.metadata_info.get("public_content", [])))
        items = list(refs.values())
        return FairSnapshot(declared=[seed.model_dump(mode="json") for seed in self.context.declared_seeds],
            findings=items, sources=self.sources, pivots=PivotFrontier(self.context).snapshot(),
            social_content=[dict(item, content_path="metadata_info.public_content") for item in items if item["content_count"]],
            breaches=[item for item in items if item["entity_type"] == "breach"],
            infostealers=[item for item in items if item["entity_type"] == "infostealer"],
            academic=[item for item in items if item["entity_type"] in {"paper", "academic", "academic_profile"}],
            documents=[item for item in items if item["entity_type"] in {"document", "search_mention"}],
            execution={"elapsed_seconds": self.elapsed_seconds, "deadline_seconds": self.plan.deadline_seconds,
                "deadline_reached": self.deadline_reached, "cleanup_pending": self.cleanup_pending,
                "partial": self.deadline_reached or self.persistence in {"failed", "partial"} or
                    any(state["status"] in FAILURE_STATES for state in self.sources.values()),
                "persistence": self.persistence, "persistence_errors": self.persistence_errors,
                "semantics": "discovery_not_attributed_dataset"}, plan=self.plan.inspect(registry)).model_dump(mode="json")


class FairEngine:
    def __init__(self, registry=tool_registry, plan=None):
        self.registry = registry
        self.plan = plan
        self.keys = RuleEngine()

    def _views(self, source, frontier):
        view = frontier.execution_view()
        if source.scope == "identifier":
            # One external lookup per task: completed records survive a later
            # timeout, and already queried identifiers are never replayed.
            for kind, values in (("email", view.all_emails()), ("username", view.all_usernames())):
                for value in values:
                    child = view.model_copy(deep=True)
                    for identifier_kind in ("email", "username"):
                        setattr(child, PRIMARY[identifier_kind], value if kind == identifier_kind else None)
                        setattr(child, DISCOVERED[identifier_kind], [])
                    child.declared_seeds = [seed for seed in child.declared_seeds
                        if seed.kind not in {"email", "username"} or (seed.kind == kind and seed.value == value)]
                    yield child
            return
        if source.scope == "context":
            yield view
            return
        kind = source.scope
        values = {"email": view.all_emails, "username": view.all_usernames, "phone": view.all_phones}[kind]()
        for value in values:
            child = view.model_copy(deep=True)
            setattr(child, PRIMARY[kind], value)
            setattr(child, DISCOVERED[kind], [])
            child.declared_seeds = [seed for seed in child.declared_seeds if seed.kind != kind or seed.value == value]
            yield child

    def _key(self, tool, view):
        return self.keys._get_tool_run_key(tool, view)

    def _not_ready(self, tool, view):
        if tool.name == "infostealer_checker" and not view.extra.get("self_consent"):
            return "skipped", "subject_consent_required"
        if tool.name == "apify_social" and (view.all_usernames() or view.extra.get("candidate_urls")):
            from app.social.capabilities import availability
            state = availability()
            if state != "configured_not_live_validated":
                return "provider_unavailable", state
            if hasattr(tool, "pending") and (pending := tool.pending(view)):
                rejected = view.extra.get("apify_runtime", {}).get("unavailable_actors", {})
                if all(request.actor in rejected for request in pending):
                    return "provider_unavailable", "actor_access_denied"
                return "budget_exhausted", "apify_reservation_limit"
        coverage = {"email_checker": "email_checker_checked", "email_enumerator": "email_enum_checked"}.get(tool.name)
        if coverage and view.extra.get(coverage) and any(email not in view.extra[coverage] for email in view.all_emails()):
            return "budget_exhausted", "provider_input_budget"
        if tool.name == "ghunt" and view.all_emails():
            from app.tools.ghunt_runtime import capabilities
            state = capabilities()["status"]
            if state != "configured":
                return "provider_unavailable", state
        return "not_applicable", "no_pending_compatible_input"

    async def collect_findings(self, investigation_id, target, *, initial_context=None, initial_findings=(), checkpoint=None, started_at=None):
        loop = asyncio.get_running_loop()
        plan = self.plan or FairPlan.configured()
        started = started_at if started_at is not None else loop.time()
        context = initial_context or TargetContext.from_target(target)
        context.extra.update(investigation_id=investigation_id, username_scan_mode="fast",
            username_site_limit=plan.username_sites, search_query_limit=plan.search_queries,
            apify_platform_allowlist=list(plan.apify_platforms), preserve_partial_on_cancel=True)
        context.extra["username_platform_priority"] = plan.maigret_options.get("names", [])
        context.extra["maigret_options"] = {**context.extra.get("maigret_options", {}), **plan.maigret_options}
        context.extra.setdefault("apify_runtime", {"version": 1, "runs": {}, "diagnostics": []})
        from app.tools.maigret_ids import add_identifiers
        add_identifiers(context, (target.extra_data or {}).get("identifiers", []), source_tool="target_input")
        frontier = PivotFrontier(context)
        frontier.seed(target)
        run = FairRun(context=context, plan=plan, started=started, findings=list(initial_findings),
            sources={source.tool: {"status": "pending" if source.enabled else "skipped", "critical": source.critical,
                "reason": source.reason if not source.enabled else None, "findings_count": 0, "attempts": []}
                for source in plan.sources})
        acquisition_end = started + plan.deadline_seconds - plan.finalization_seconds - plan.cancellation_seconds
        optional_end = started + (acquisition_end - started) * plan.optional_cutoff_fraction
        pivot_end = started + (acquisition_end - started) * plan.latest_pivot_fraction
        tasks, attempted, active_tools = {}, set(), set()
        limits = {**plan.frontier_limits, "max_discovered_round": plan.max_waves,
                  "allowed_tools": [s.tool for s in plan.sources if s.enabled], "ignore_readiness_errors": True}
        tick = plan.progress_interval_seconds
        last_checkpoint = started - plan.checkpoint_seconds
        checkpoint_task = None

        async def publish():
            run.elapsed_seconds = round(loop.time() - started, 4)
            await event_bus.publish(investigation_id, {"type": "fair_progress", **run.progress()})

        async def save():
            nonlocal last_checkpoint, checkpoint_task
            if checkpoint is None:
                return
            if checkpoint_task is not None:
                if not checkpoint_task.done():
                    run.persistence = "partial"
                    return  # No overlapping SQL session while cancellation cleans up.
                if not checkpoint_task.cancelled():
                    checkpoint_task.exception()
                checkpoint_task = None
            remaining = started + plan.deadline_seconds - loop.time()
            if remaining <= 0:
                run.persistence = "partial"
                return
            checkpoint_task = asyncio.create_task(checkpoint(run), name="fair:checkpoint")
            done, _ = await asyncio.wait({checkpoint_task}, timeout=min(plan.checkpoint_seconds, remaining))
            if not done:
                checkpoint_task.cancel()
                run.persistence_errors += 1
                run.persistence = "partial"
                checkpoint_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            else:
                if checkpoint_task.cancelled() or checkpoint_task.exception() is not None:
                    run.persistence_errors += 1
                    run.persistence = "partial"
                else:
                    run.persistence = "persisted"
                checkpoint_task = None
            last_checkpoint = loop.time()

        async def execute(tool, view, timeout):
            with capture() as health:
                try:
                    async with asyncio.timeout(timeout):
                        findings = await tool.execute(view)
                    if not isinstance(findings, list) or any(not isinstance(f, ToolFinding) for f in findings):
                        raise ValueError("tool_result_schema")
                    status, reason = classify(tool, view, findings, health)
                    return findings, status, reason
                except (TimeoutError, asyncio.CancelledError, httpx.TimeoutException):
                    return [], "timeout", "tool_or_global_deadline"
                except Exception as error:
                    return [], "failed", type(error).__name__

        def schedule():
            nonlocal frontier
            frontier = PivotFrontier(context)
            frontier.sync(max((job["wave"] for job in run.jobs.values()), default=0))
            index = min(plan.max_waves, 1 + max((c.discovered_round for c in frontier.candidates.values()), default=0))
            frontier.next(index, "fair", limits=limits)
            for source in sorted(plan.sources, key=lambda item: item.priority):
                state = run.sources[source.tool]
                if not source.enabled or source.tool in active_tools:
                    continue
                if len(tasks) >= plan.parallelism:
                    break
                if source.first_wave > 1 and not any(job["record"]["status"] != "running" for job in run.jobs.values()):
                    continue
                tool = self.registry.get_tool(source.tool)
                if tool is None:
                    state.update(status="provider_unavailable", reason="tool_not_registered")
                    continue
                if not source.critical and loop.time() >= optional_end:
                    if not state["attempts"]:
                        state.update(status="skipped", reason="optional_time_budget")
                    continue
                ready = False
                for raw_view in self._views(source, frontier):
                    view = raw_view.model_copy(deep=True)
                    # One source owns these reservations; do not clone/reset its ledger.
                    if tool.name == "apify_social":
                        view.extra["apify_runtime"] = context.extra["apify_runtime"]
                    try:
                        key = self._key(tool, view)
                    except Exception:
                        state.update(status="failed", reason="input_fingerprint_error")
                        continue
                    if key in attempted:
                        continue
                    relevant = {pivot_id(kind, value) for kind, value in context_inputs(view)}
                    inputs = [c for c in frontier.candidates.values() if c.id in relevant and tool_accepts(tool, c)]
                    wave = max(source.first_wave, 1 + max((c.discovered_round for c in inputs), default=0))
                    if wave > plan.max_waves or (wave > 1 and loop.time() >= pivot_end):
                        if not state["attempts"]:
                            state.update(status="budget_exhausted", reason="wave_or_time_budget")
                        continue
                    try:
                        can_run = tool.can_run(view)
                    except Exception:
                        state.update(status="failed", reason="readiness_error")
                        continue
                    budget_reason = None
                    from app.core.config import settings
                    for name, field, maximum, values in (
                        ("username_finder", "username_finder_scanned", settings.username_scan_max_aliases, view.all_usernames()),
                        ("github_deep_scanner", "github_checked_usernames", settings.username_scan_max_aliases, view.all_usernames()),
                        ("phone_lookup", "phone_lookup_results", settings.phone_max_numbers, view.all_phones())):
                        checked = view.extra.get(field, [])
                        if tool.name == name and len(checked) >= maximum and any(value.casefold() not in checked for value in values):
                            can_run, budget_reason = False, "provider_input_budget"
                    if not can_run:
                        status, reason = ("budget_exhausted", budget_reason) if budget_reason else self._not_ready(tool, view)
                        if not state["attempts"] or status == "budget_exhausted":
                            state.update(status="partial" if state["findings_count"] and status == "budget_exhausted" else status, reason=reason)
                        continue
                    if len(state["attempts"]) >= source.max_invocations:
                        state.update(status="partial" if state["findings_count"] else "budget_exhausted",
                                     reason="source_invocation_budget")
                        continue
                    ready = True
                    attempted.add(key)
                    trace_id = str(uuid4())
                    record = {"id": trace_id, "wave": wave, "status": "running", "reason": None,
                        "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None,
                        "findings_count": 0, "input_key": reference(key)}
                    state["attempts"].append(record)
                    state.update(status="running", reason=None)
                    job = {"record": record, "wave": wave, "tool": tool, "source": source, "view": view,
                           "baseline": deepcopy(view.extra), "summary": safe_input_summary(tool, view), "cancelled": False}
                    run.jobs[trace_id] = job
                    task = asyncio.create_task(execute(tool, view, min(source.timeout_seconds, acquisition_end-loop.time())),
                                               name="fair:" + tool.name)
                    tasks[task] = job
                    active_tools.add(tool.name)
                    break  # Never overlap the same tool's mutable runtime/budgets.
                if not ready and state["attempts"] and state["status"] == "running" and source.tool not in active_tools:
                    state["status"] = aggregate(state)

        def ingest(task):
            job = tasks.pop(task)
            tool, view, record = job["tool"], job["view"], job["record"]
            active_tools.discard(tool.name)
            findings, status, reason = task.result() if not task.cancelled() else ([], "timeout", "cancelled_before_start")
            if job["cancelled"]:
                status, reason = ("partial" if findings else "timeout"), job.get("cancelled_reason", "scheduler_deadline")
            record.update(status=status, reason=reason, completed_at=datetime.now(timezone.utc).isoformat(), findings_count=len(findings))
            delta = view.model_copy(deep=False)
            delta.extra = {key: value for key, value in view.extra.items()
                           if key != "pivot_frontier" and value != job["baseline"].get(key)}
            current = PivotFrontier(context)
            current.merge_view(delta)
            current.mark_explored(view, [tool], {tool.name} if status in {"completed", "partial"} else set())
            for finding in findings:
                finding.metadata_info.update(source_tool=tool.name, engine_layer="fair_acquisition",
                    source_tool_execution_id=record["id"])
                run.observations.append(PendingObservation(finding, UUID(record["id"]), datetime.now(timezone.utc)))
            run.findings.extend(findings)
            context.extra["pivot_round"] = job["wave"]
            if job["source"].can_pivot:
                extract_and_apply_pivots(findings, context)
                # Fair always uses Frontier, even when normal mode has its flag disabled.
                from app.core.config import settings
                if not settings.pivot_frontier_enabled:
                    PivotFrontier(context).observe(findings, job["wave"])
            state = run.sources[tool.name]
            state["findings_count"] += len(findings)
            state.update(status=aggregate(state), reason=reason)

        await publish()
        try:
            while loop.time() < acquisition_end:
                schedule()
                run.phase = "wave_" + str(max((job["wave"] for job in run.jobs.values()), default=1))
                await publish()
                if loop.time() - last_checkpoint >= plan.checkpoint_seconds or not tasks:
                    await save()
                if not tasks:
                    break
                done, _ = await asyncio.wait(tasks, timeout=min(tick, max(0, acquisition_end-loop.time())),
                                             return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    ingest(task)
                if loop.time() >= optional_end:
                    for task, job in tasks.items():
                        if not job["source"].critical and not job["cancelled"]:
                            job["cancelled"] = True
                            job["cancelled_reason"] = "optional_time_budget"
                            task.cancel()
        finally:
            run.deadline_reached = loop.time() >= acquisition_end
            for task in list(tasks):
                if task.done():
                    ingest(task)
            if tasks:
                run.deadline_reached = loop.time() >= acquisition_end
                for task, job in tasks.items():
                    job["cancelled"] = True
                    task.cancel()
                done, pending = await asyncio.wait(tasks, timeout=min(plan.cancellation_seconds,
                    max(0, started + plan.deadline_seconds - loop.time())))
                for task in done:
                    ingest(task)
                run.cleanup_pending = bool(pending)
                for task in pending:
                    job = tasks[task]
                    job["record"].update(status="timeout", reason="cancellation_grace_exhausted",
                        completed_at=datetime.now(timezone.utc).isoformat())
                    state = run.sources[job["tool"].name]
                    state.update(status=aggregate(state), reason="cancellation_grace_exhausted")
                    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            for state in run.sources.values():
                if state["status"] == "pending":
                    state.update(status="skipped", reason="deadline_or_no_applicable_work")
            run.phase = "finalizing"
            await publish()
            await save()
            run.phase = "complete"
            await publish()
            await save()
            if checkpoint_task is not None and not checkpoint_task.done():
                run.cleanup_pending = True
                run.persistence = "partial"
            run.elapsed_seconds = round(loop.time() - started, 4)
            await event_bus.publish(investigation_id, {"type": "fair_snapshot", "snapshot": run.snapshot(self.registry)})
        return run

    async def execute_investigation(self, investigation_id, target, db):
        """All DB writes are serialized here; workers only acquire ordinary ToolFindings."""
        from sqlalchemy import select
        from app.models.entity import Entity
        from app.models.investigation import Investigation
        from app.models.tool_execution import ToolExecution
        target_copy = SimpleNamespace(**{name: deepcopy(getattr(target, name, None)) for name in (
            "id", "full_name", "email", "username", "phone", "dni", "university", "description", "extra_data")})
        entry_started = asyncio.get_running_loop().time()
        persisted_count = 0
        persisted_observations = 0
        entities = []
        initial_context = TargetContext.from_target(target_copy)
        try:
            loading_plan = self.plan or FairPlan.configured()
            async with asyncio.timeout(min(loading_plan.checkpoint_seconds, loading_plan.deadline_seconds
                    - loading_plan.finalization_seconds - loading_plan.cancellation_seconds)):
                investigation = await db.get(Investigation, UUID(investigation_id))
                initial_context.extra.update(deepcopy((investigation.metrics or {}).get("collection_runtime", {})))
                entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == UUID(investigation_id)))).all())
            if "username_finder_scanned" in initial_context.extra:
                initial_context.extra["username_finder_scanned"] = set(initial_context.extra["username_finder_scanned"])
            previous = [ToolFinding(entity_type=e.entity_type, platform=e.platform, value=e.value,
                display_name=e.display_name, metadata_info=dict(e.metadata_info or {})) for e in entities]
            extract_and_apply_pivots(previous, initial_context)
        except Exception:
            await db.rollback()
            previous = []
        persisted_count = len(previous)
        async def write_checkpoint(run, write_db):
            nonlocal persisted_count, persisted_observations, entities
            batch_count, observation_count = len(run.findings), len(run.observations)
            pending_findings = [finding.model_copy(deep=True) for finding in run.findings[persisted_count:batch_count]]
            pending_observations = run.observations[persisted_observations:observation_count]
            jobs = [{"record": deepcopy(job["record"]), "name": job["tool"].name,
                     "description": job["tool"].description, "summary": deepcopy(job["summary"])}
                    for job in list(run.jobs.values())]
            phase, progress, snapshot = run.phase, run.progress(), run.snapshot(self.registry)
            runtime = durable_runtime(run.context.extra)
            try:
                for job in jobs:
                    record = job["record"]
                    execution = await write_db.get(ToolExecution, UUID(record["id"]))
                    if execution is None:
                        execution = ToolExecution(id=UUID(record["id"]), investigation_id=UUID(investigation_id),
                            tool_name=job["name"], tool_description=job["description"][:255],
                            engine="fair", engine_layer="fair_acquisition", round_index=record["wave"],
                            started_at=datetime.fromisoformat(record["started_at"]), input_summary=job["summary"])
                        write_db.add(execution)
                    execution.status = record["status"]
                    execution.completed_at = datetime.fromisoformat(record["completed_at"]) if record["completed_at"] else None
                    execution.findings_count = record["findings_count"]
                    execution.error_summary = record["reason"]
                await write_db.flush()
                existing = list((await write_db.scalars(select(Entity).where(Entity.investigation_id == UUID(investigation_id)))).all())
                changed = await persist_findings(investigation_id, pending_findings, target_copy, write_db,
                                                default_source_tool="fair", existing_entities=existing)
                await trace_recorder.link_observations(write_db, investigation_id=investigation_id,
                    pending=pending_observations, entities=changed)
                entities = list((await write_db.scalars(select(Entity).where(Entity.investigation_id == UUID(investigation_id)))).all())
                run.entity_ids = {reference(entity_dedupe_key(entity)): str(entity.id) for entity in entities}
                inv = await write_db.get(Investigation, UUID(investigation_id))
                for group in ("findings", "social_content", "breaches", "academic", "documents"):
                    for item in snapshot[group]:
                        item["entity_id"] = run.entity_ids.get(item["key"])
                snapshot["execution"]["persistence"] = "persisted"
                snapshot["execution"]["partial"] = snapshot["execution"]["deadline_reached"] or any(
                    state["status"] in FAILURE_STATES for state in snapshot["sources"].values())
                inv.metrics = {**(inv.metrics or {}), "acquisition_mode": "fair", "engine_used": "fair", "ai_enhanced": False,
                    "collection_runtime": runtime, "fair_progress": progress,
                    "fair_snapshot": snapshot, "execution_time_seconds": progress["elapsed_seconds"],
                    "entities_discovered": len(entities)}
                if phase in {"finalizing", "complete"}:
                    inv.status = "completed"
                    inv.completed_at = datetime.now(timezone.utc)
                    inv.summary = f"Adquisición Fair: {len(entities)} observaciones; atribución pendiente de revisión."
                await write_db.commit()
                persisted_count = batch_count
                persisted_observations = observation_count
            except BaseException:
                await write_db.rollback()
                raise
        async def checkpoint(run):
            from sqlalchemy.ext.asyncio import AsyncSession
            async with AsyncSession(bind=db.bind, expire_on_commit=False) as write_db:
                await write_checkpoint(run, write_db)
        run = await self.collect_findings(investigation_id, target_copy, initial_context=initial_context,
            initial_findings=previous, checkpoint=checkpoint, started_at=entry_started)
        # Existing SSE is the temporary recovery path when storage remains unavailable.
        if persisted_count < len(run.findings):
            await event_bus.publish(investigation_id, {"type": "fair_unpersisted_findings",
                "findings": [finding.model_dump(mode="json") for finding in run.findings[persisted_count:]],
                "reason": "database_unavailable"})
        await event_bus.publish(investigation_id, {"type": "investigation_complete", "status": "completed",
            "partial": run.snapshot(self.registry)["execution"]["partial"], "entities_count": len(entities),
            "elapsed_seconds": run.elapsed_seconds, "mode": "fair"})
        return run


fair_engine = FairEngine()
