"""Registered optional social source family using the ordinary PersonMap pipeline."""
import asyncio
from decimal import Decimal
import hashlib
import json
from weakref import WeakKeyDictionary

from app.core.config import settings
from app.social.apify_adapter import ApifyAdapter, actor_input
from app.social.apify_client import ApifyClient
from app.social.capabilities import ACTORS, actor_build, availability, config_id
from app.social.router import SocialSourceRouter
from app.tools.base import BaseTool, ToolCategory
from app.tools.social_profiles import parse_social_profile

_GATES = WeakKeyDictionary()


def _gate():
    loop = asyncio.get_running_loop()
    prior = _GATES.get(loop)
    if not prior or prior[0] != settings.apify_parallelism:
        _GATES[loop] = (settings.apify_parallelism, asyncio.Semaphore(settings.apify_parallelism))
    return _GATES[loop][1]


def profile_key(url):
    profile = parse_social_profile(url)
    if not profile:
        return url
    return ":".join((profile.platform, profile.resource_kind,
        profile.username if profile.resource_kind == "channel_id" else profile.username.casefold()))


def execution_summary(context):
    runs = context.extra.get("apify_runtime", {}).get("runs", {})
    return {"runs_reserved": len(runs), "actors_reserved": len({run["actor"] for run in runs.values()}),
        "items_read": sum(run.get("items_read", 0) for run in runs.values()),
        "reserved_charge_usd": float(sum(Decimal(str(run["reserved_charge_usd"])) for run in runs.values())),
        "unavailable": context.extra.get("apify_runtime", {}).get("unavailable"),
        "outcomes": [run.get("outcome", run["status"]) for run in runs.values()],
        "diagnostics": context.extra.get("apify_runtime", {}).get("diagnostics", [])[-20:]}


class ApifySocialTool(BaseTool):
    name = "apify_social"
    description = ("Enriquece cuentas declaradas con plataforma o perfiles públicos admitidos por fuentes nativas, mediante Actors Apify "
        "allowlisted y presupuestados. Requiere consentimiento del sujeto; no confirma pertenencia ni busca alias a ciegas.")
    category = ToolCategory.SOCIAL
    required_inputs = ["username", "candidate_urls"]
    # `force` must not erase paid reservations/coverage or unavailable states.
    cache_prefix = "apify_coverage_"

    def __init__(self, client_factory=ApifyClient):
        self.client_factory = client_factory
        self.router = SocialSourceRouter()
        self.adapter = ApifyAdapter()

    def pending(self, context):
        runs = context.extra.get("apify_runtime", {}).get("runs", {})
        seen = {(run["actor"], key) for run in runs.values() for key in run.get("profile_keys", [])}
        result = []
        for request in self.router.enrichment_requests(context):
            if (request.actor, profile_key(request.url)) not in seen:
                result.append(request)
                seen.add((request.actor, profile_key(request.url)))
        return result

    def _allocation(self, context, request):
        runs = context.extra.get("apify_runtime", {}).get("runs", {})
        if len(runs) >= settings.apify_max_runs:
            return 0, "run_budget_exhausted"
        actors = {run["actor"] for run in runs.values()}
        if request.actor not in actors and len(actors) >= settings.apify_max_actors:
            return 0, "actor_budget_exhausted"
        # Old records consumed one profile per run; retain them across upgrades.
        allocated = sum(run.get("profile_allowance", len(run.get("profile_keys", [])))
                        for run in runs.values() if run["actor"] == request.actor)
        remaining = settings.apify_max_profiles_per_actor - allocated
        if remaining <= 0:
            return 0, "profile_budget_exhausted"
        reserved = sum(Decimal(str(run["reserved_charge_usd"])) for run in runs.values())
        if reserved + Decimal(str(settings.apify_max_charge_per_run_usd)) > Decimal(str(settings.apify_max_charge_per_investigation_usd)):
            return 0, "charge_budget_exhausted"
        return remaining, None

    def can_run(self, context):
        return any(self._allocation(context, request)[1] is None for request in self.pending(context))

    def input_fingerprint(self, context):
        # Actual admitted inputs, not mutable pending/coverage: repeated workspace
        # requests can reuse their persisted ToolExecution without another run.
        return hashlib.sha256(json.dumps({"config": config_id(),
            "requests": [(request.platform, profile_key(request.url)) for request in self.router.enrichment_requests(context)]}, sort_keys=True).encode()).hexdigest()

    async def execute(self, context):
        state = context.extra.setdefault("apify_runtime", {"version": 1, "runs": {}, "diagnostics": []})
        runs = state.setdefault("runs", {})
        diagnostics = state.setdefault("diagnostics", [])
        requests = self.pending(context)
        if not requests:
            reason = "subject_consent_required" if context.extra.get("subject_consent") is not True else (
                state.get("unavailable") or availability())
            diagnostics.append({"status": "no_profiles_ready" if reason == "configured_not_live_validated" else reason})
            del diagnostics[:-50]
            return []
        findings, jobs = [], []
        groups = {}
        for request in requests:
            groups.setdefault((request.platform, request.actor), []).append(request)
        for group in groups.values():
            request = group[0]
            allowance, reason = self._allocation(context, request)
            if reason:
                diagnostics.append({"platform": request.platform, "status": reason})
                continue
            spec = ACTORS[request.platform]
            try:
                build = actor_build(spec)
            except ValueError:
                diagnostics.append({"platform": request.platform, "status": "invalid_actor_build"})
                continue
            batch = group[:allowance]
            if len(group) > len(batch):
                diagnostics.append({"platform": request.platform, "status": "profile_budget_exhausted"})
            profile_keys = [profile_key(item.url) for item in batch]
            content_limit = settings.apify_max_content_items_per_profile
            # Profile rows contain nested posts; flat rows are bounded separately.
            row_limit = len(batch) if spec.profile_row else len(batch) * content_limit
            key = hashlib.sha256(json.dumps([spec.actor, build, profile_keys]).encode()).hexdigest()
            # Synchronous reservation before the first await: concurrent jobs in
            # this context cannot independently spend the same remaining budget.
            record = {"actor": spec.actor, "platform": spec.platform, "status": "reserved", "items_read": 0,
                "item_allowance": row_limit, "profile_allowance": len(batch),
                "content_allowance_per_profile": content_limit, "requested_build": build, "reserved_charge_usd": settings.apify_max_charge_per_run_usd,
                "profile_keys": profile_keys}
            runs[key] = record
            jobs.append((spec, batch, record, actor_input(spec, batch, content_limit)))

        async def execute_one(spec, batch, record, submitted_input):
            try:
                async with _gate():
                    if state.get("unavailable"):
                        record["outcome"] = "provider_unavailable"
                        return
                    result = await self.client_factory().run(spec, submitted_input, record["item_allowance"],
                        record["reserved_charge_usd"], on_update=record.update)
                    record.update(result.summary())
                    if result.error in {"authentication_failed", "access_denied", "quota_exhausted", "rate_limited"}:
                        state["unavailable"] = result.error
                    normalized = []
                    record["profiles"] = []
                    for request in batch:
                        try:
                            observed = self.adapter.normalize(spec, request, result, submitted_input)
                            normalized.extend(observed)
                            record["profiles"].append({"input": request.url,
                                "outcome": "observed" if observed else "no_usable_public_rows"})
                        except Exception:
                            record["profiles"].append({"input": request.url, "outcome": "adapter_error"})
                    findings.extend(normalized)
                    if normalized:
                        record["outcome"] = "partial" if result.error or len(normalized) < len(batch) else "observed"
                    else:
                        record["outcome"] = result.error or ("no_usable_public_rows" if result.items else "empty_dataset")
                    for finding in normalized:
                        observed = finding.metadata_info.get("observed_profile_url")
                        if observed and profile_key(observed) not in record["profile_keys"]:
                            record["profile_keys"].append(profile_key(observed))
            except asyncio.CancelledError:
                record["outcome"] = "batch_timeout_or_cancelled"
                raise
            except Exception:
                # Actor/parser drift is a partial source failure, never an engine failure.
                record["outcome"] = "adapter_error"

        try:
            async with asyncio.timeout(settings.apify_batch_timeout):
                await asyncio.gather(*(execute_one(*job) for job in jobs))
        except TimeoutError:
            diagnostics.append({"status": "batch_timeout"})
        except asyncio.CancelledError:
            if context.extra.get("preserve_partial_on_cancel") is not True:
                raise
            diagnostics.append({"status": "batch_timeout_or_cancelled"})
        del diagnostics[:-50]
        return findings
