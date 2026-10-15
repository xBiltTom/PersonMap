"""Deterministic admission of investigation inputs, never identity attribution.

The canonical TargetContext remains the archive. Execution views only expose
admitted inputs; no evidence is removed when a budget defers a candidate.
"""
import hashlib
import json
from types import SimpleNamespace
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from app.core.config import settings
from app.identity.evidence import signals, resource_key, is_profile, STRONG_EMAIL_ROLES, STRONG_PHONE_ROLES
from app.schemas.identifiers import CASE_SENSITIVE_TYPES
from app.tools.base import TargetContext
from app.tools.dni_public import public_source_url
from app.tools.phone_numbers import phone_identity

VERSION = 1
SEMANTICS = "investigation_priority_not_identity_probability"
PRIMARY = {"email": "email", "username": "username", "phone": "phone", "name": "full_name", "dni": "dni"}
DISCOVERED = {"email": "discovered_emails", "username": "discovered_usernames",
              "phone": "discovered_phones", "name": "discovered_names"}
URL_FIELDS = ("candidate_urls", "personal_domain_urls", "dni_source_urls")
INPUT_LISTS = (*URL_FIELDS, "avatar_urls", "maigret_identifiers")
BASE = {"P0": 1000, "P1": 800, "P2": 600, "P3": 400, "P4": 200}
GAIN = {"email": 12, "orcid": 12, "url": 8, "username": 10, "phone": 8, "name": 6, "avatar": 2, "dni": 8}
# Relative exploration units, not promised HTTP counts or monetary prices.
TOOL_COST = {"username_finder": 20, "maigret_enricher": 12, "ghunt": 10,
             "email_enumerator": 10, "search_dorker": 6, "academic_finder": 6,
             "reverse_image_search": 6, "domain_finder": 4, "github_deep_scanner": 3}


class PivotSupport(BaseModel):
    observation_key: str
    source_tool: str
    source_url: str | None = None
    source_observation_id: str | None = None
    source_execution_id: str | None = None
    evidence_role: str
    evidence_class: Literal["strong", "contextual", "weak", "seed"]
    independent_key: str | None = None


class PivotCandidate(BaseModel):
    id: str
    type: str
    value: str
    discovered_round: int
    confidence_class: Literal["P0", "P1", "P2", "P3", "P4"] = "P4"
    pivot_priority: int = 0
    expected_information_gain: Literal["high", "medium", "low"] = "low"
    exploration_cost: int = 1
    status: Literal["pending", "active", "explored", "deferred"] = "pending"
    support_count: int = 0
    independent_source_count: int = 0
    supports: list[PivotSupport] = Field(default_factory=list)
    possible_tools: list[str] = Field(default_factory=list)
    input_fields: list[str] = Field(default_factory=list)
    explored_by: list[str] = Field(default_factory=list)
    selected_rounds: list[int] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    score_components: dict[str, int] = Field(default_factory=dict)
    deferred_reason: str | None = None


class PivotFrontierRead(BaseModel):
    version: int
    semantics: Literal["investigation_priority_not_identity_probability"]
    pending: list[PivotCandidate]
    active: list[PivotCandidate]
    explored: list[PivotCandidate]
    deferred: list[PivotCandidate]
    summary: dict[str, int]
    decisions: list[dict]
    duplicate_executions_avoided: int


class PivotFrontierResponse(BaseModel):
    pivot_frontier: PivotFrontierRead


def pivot_id(kind, value):
    if kind == "email":
        value = value.strip().casefold()
    elif kind == "phone":
        value = phone_identity(value) or value.strip()
    elif kind == "username":
        value = value.strip().lstrip("@").casefold()
    elif kind in {"url", "avatar"}:
        value = resource_key(value) or value.strip()
    elif kind not in CASE_SENSITIVE_TYPES:
        value = value.strip().casefold()
    return kind + ":" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]


def context_inputs(context):
    for kind, values in (("email", context.all_emails()), ("username", context.all_usernames()),
                         ("phone", context.all_phones()),
                         ("name", [context.full_name, *context.discovered_names]), ("dni", [context.dni])):
        for value in values:
            if value:
                yield kind, value
    for field in URL_FIELDS:
        for value in context.extra.get(field, []):
            yield "url", value
    for value in context.extra.get("avatar_urls", []):
        yield "avatar", value
    for item in context.extra.get("maigret_identifiers", []):
        yield item["id_type"], item["value"]


def tool_accepts(tool, candidate):
    required = set(getattr(tool, "required_inputs", []))
    kind = candidate.type
    if kind in PRIMARY:
        field = PRIMARY[kind]
        return field in required or DISCOVERED.get(kind) in required
    if kind == "url":
        return "candidate_urls" in required or (tool.name == "dni_lookup" and "dni_source_urls" in candidate.input_fields)
    if kind == "avatar":
        return "avatar_urls" in required
    return "identifiers" in required or (tool.name == "ghunt" and kind == "gaia_id")


def _source_key(finding):
    meta = finding.metadata_info
    # An original observation takes precedence over its adapters or mirrors.
    source = next((public_source_url(meta.get(key)) for key in
                   ("original_source_url", "parent_source_url", "source_url")
                   if isinstance(meta.get(key), str) and public_source_url(meta[key])), None)
    source = source or public_source_url(finding.value)
    if not source:
        source = next((public_source_url(url) for url in finding.evidence_urls if public_source_url(url)), None)
    root = source
    if source:
        host = urlsplit(source).hostname or ""
        while host.split(".")[0] in {"www", "api", "m", "mobile"}:
            host = host.split(".", 1)[-1]
        # Different paths/adapters on one provider do not establish independence.
        root = host
    if meta.get("doi"):
        root = "doi:" + str(meta["doi"]).lower().removeprefix("https://doi.org/")
    return source, root


class PivotFrontier:
    def __init__(self, context: TargetContext):
        self.context = context
        state = context.extra.get("pivot_frontier", {})
        self.candidates = {key: PivotCandidate.model_validate(value)
                           for key, value in state.get("candidates", {}).items()}
        self.decisions = list(state.get("decisions", []))
        self.duplicate_executions_avoided = state.get("duplicate_executions_avoided", 0)

    def save(self):
        self.context.extra["pivot_frontier"] = {
            "version": VERSION, "semantics": SEMANTICS,
            "candidates": {key: value.model_dump(mode="json") for key, value in self.candidates.items()},
            "decisions": self.decisions,
            "duplicate_executions_avoided": self.duplicate_executions_avoided,
        }

    def seed(self, target=None):
        for kind, field in PRIMARY.items():
            value = getattr(target or self.context, field, None)
            if value:
                self.add(kind, value, 0, PivotSupport(observation_key="seed:" + pivot_id(kind, value),
                    source_tool="target_input", evidence_role="user_input", evidence_class="seed"))
        extra = (target.extra_data or {}) if target is not None else {}
        from app.tools.maigret_ids import identifier_values
        for item in identifier_values(extra.get("identifiers", [])):
            self.add(item["id_type"], item["value"], 0, PivotSupport(
                observation_key="seed:" + pivot_id(item["id_type"], item["value"]),
                source_tool="target_input", evidence_role="user_input", evidence_class="seed"))
        for url in [extra.get("url"), *extra.get("candidate_urls", [])]:
            if isinstance(url, str) and public_source_url(url):
                urls = self.context.extra.setdefault("candidate_urls", [])
                if url not in urls:
                    urls.append(url)
                self.add("url", url, 0, PivotSupport(observation_key="seed:" + pivot_id("url", url),
                    source_tool="target_input", source_url=url, evidence_role="user_input", evidence_class="seed"))
        self.sync(self.context.extra.get("pivot_round", 0))

    def add(self, kind, value, round_index, support=None):
        key = pivot_id(kind, value)
        candidate = self.candidates.setdefault(key, PivotCandidate(
            id=key, type=kind, value=value, discovered_round=round_index))
        if support and not any(item.observation_key == support.observation_key for item in candidate.supports):
            candidate.supports.append(support)
        return candidate

    def sync(self, round_index):
        for kind, value in context_inputs(self.context):
            self.add(kind, value, round_index)
        for field in URL_FIELDS:
            for value in self.context.extra.get(field, []):
                candidate = self.candidates[pivot_id("url", value)]
                if field not in candidate.input_fields:
                    candidate.input_fields.append(field)
        self.rank()
        self.save()

    def observe(self, findings, round_index):
        self.sync(round_index)
        known = set(self.candidates)
        for finding in findings:
            meta = finding.metadata_info or {}
            tool = str(meta.get("source_tool", "unknown")).rsplit(":", 1)[-1]
            source, independent = _source_key(finding)
            entity = SimpleNamespace(entity_type=finding.entity_type, platform=finding.platform,
                                     value=finding.value, metadata_info=meta, source_tool=tool)
            roles = {}
            for signal in signals(entity):
                kind, value, role = signal["kind"], signal["value"], signal["role"]
                strong = role in (STRONG_EMAIL_ROLES | STRONG_PHONE_ROLES | {"profile_identifier"})
                # Exact-query echoes are useful provenance, not independent confirmation.
                level = "weak" if role in {"lookup_email", "identifier"} else "strong" if strong else "contextual"
                roles[pivot_id(kind, value)] = (role, level)
            proposed = []
            for kind, fields in (("email", ("emails", "extracted_emails")),
                                 ("username", ("usernames", "extracted_usernames")),
                                 ("phone", ("phones", "extracted_phones"))):
                for field in fields:
                    proposed.extend((kind, value) for value in meta.get(field, []) if isinstance(value, str))
            proposed.extend(("url", value) for value in [finding.value, meta.get("url"), meta.get("website"),
                meta.get("blog"), *meta.get("linked_profiles", [])] if isinstance(value, str))
            proposed.extend(("avatar", meta[field]) for field in ("avatar_url", "photo_url", "thumbnail_url")
                            if isinstance(meta.get(field), str))
            proposed.extend((c.type, c.value) for c in self.candidates.values() if c.id in roles)
            # Typed identifiers already carry extraction provenance; do not parse
            # arbitrary text or infer identities to manufacture additional pivots.
            from app.tools.maigret_ids import identifier_values
            identifiers = identifier_values(meta.get("extracted_identifiers", [])) + identifier_values(meta.get("discovered_identifiers", {}))
            sources = self.context.extra.get("maigret_identifier_sources", {})
            identifiers += [item for item in self.context.extra.get("maigret_identifiers", [])
                if any(entry.get("url") == finding.value for entry in sources.get(item["id_type"] + ":" + item["value"], []))]
            proposed.extend((item["id_type"], item["value"]) for item in identifiers)
            if isinstance(meta.get("full_name"), str):
                proposed.append(("name", meta["full_name"]))
            observed_profile = is_profile(entity) and (
                meta.get("verification_status") == "verified" or tool in {"github_deep_scanner", "gravatar_deep", "keybase_resolver"})
            for kind, value in proposed:
                key = pivot_id(kind, value)
                if key not in known:
                    continue  # Admission does not expand the extractor's scope.
                role, level = roles.get(key, ("unverified_candidate", "weak"))
                if finding.entity_type == "search_mention" or meta.get("evidence_level") == "snippet":
                    role, level = "search_snippet", "weak"
                elif key not in roles and (meta.get("source_kind") == "public_document" or finding.entity_type in {"paper", "academic"}):
                    role, level = "document_mention", "contextual"
                elif kind == "url" and value in meta.get("linked_profiles", []) and observed_profile:
                    role, level = "explicit_profile_link", "strong"
                elif kind == "url" and value == finding.value and observed_profile:
                    role, level = "observed_profile_url", "strong"
                elif kind == "url" and value in [meta.get("website"), meta.get("blog")] and observed_profile:
                    role, level = "profile_declared_website", "strong"
                elif kind not in PRIMARY and kind not in {"url", "avatar"} and observed_profile:
                    role, level = "profile_identifier", "strong"
                fingerprint = json.dumps([tool, resource_key(source) if source else finding.value, key, role], sort_keys=True)
                support = PivotSupport(observation_key=hashlib.sha256(fingerprint.encode()).hexdigest()[:24],
                    source_tool=tool, source_url=source, source_observation_id=meta.get("source_observation_id"),
                    source_execution_id=meta.get("source_tool_execution_id"),
                    evidence_role=role, evidence_class=level,
                    independent_key=None if role in {"lookup_email", "identifier"} else independent)
                self.add(kind, value, round_index, support)
        self.rank()
        self.save()

    def rank(self):
        from app.tools.registry import tool_registry
        tools = tool_registry.get_all()
        for candidate in self.candidates.values():
            candidate.possible_tools = sorted(t.name for t in tools if tool_accepts(t, candidate))
            candidate.exploration_cost = max([TOOL_COST.get(t, 1) for t in candidate.possible_tools] or [1])
            gain = GAIN.get(candidate.type, 6)
            candidate.expected_information_gain = "high" if gain >= 10 else "medium" if gain >= 6 else "low"
            candidate.support_count = len(candidate.supports)
            candidate.independent_source_count = len({s.independent_key for s in candidate.supports if s.independent_key})
            classes = {s.evidence_class for s in candidate.supports}
            tier = "P0" if "seed" in classes else "P1" if "strong" in classes else "P3" if "contextual" in classes else "P4"
            if tier == "P3" and candidate.independent_source_count >= 2:
                tier = "P2"
            candidate.confidence_class = tier
            bonus = min(3, max(0, candidate.independent_source_count - 1)) * settings.pivot_corroboration_bonus
            components = {"evidence_strength": BASE[tier], "corroboration_bonus": bonus,
                "source_quality": 5 if "strong" in classes else 0,
                "expected_information_gain": gain, "exploration_cost": -candidate.exploration_cost,
                "repetition_penalty": -min(10, len(candidate.explored_by)),
                "weak_context_penalty": -10 if tier == "P4" else 0}
            candidate.score_components = components
            candidate.pivot_priority = 1000 if tier == "P0" else sum(components.values())
            candidate.reasons = sorted({s.evidence_role for s in candidate.supports}) or ["context input without observed association"]
            if bonus:
                candidate.reasons.append(f"{candidate.independent_source_count} independent source families")
        return sorted(self.candidates.values(), key=lambda c: (-c.pivot_priority, c.discovered_round, c.id))

    def next(self, round_index, mode="standard"):
        from app.tools.registry import tool_registry
        readiness = self.context.model_copy(deep=False)
        for kind, field in DISCOVERED.items():
            primary = PRIMARY[kind]
            if not getattr(readiness, primary) and getattr(readiness, field):
                setattr(readiness, primary, getattr(readiness, field)[0])
        ready = {tool.name for tool in tool_registry.get_all() if tool.can_run(readiness)}
        ranked = self.rank()
        admitted = sum(bool(c.selected_rounds) for c in ranked if c.confidence_class != "P0")
        previous = {c.id for c in ranked if round_index in c.selected_rounds and c.confidence_class != "P0"}
        round_count = len(previous)
        selected = []
        weak = sum(c.confidence_class == "P4" for c in ranked if c.id in previous)
        cost = sum(c.exploration_cost for c in ranked if c.id in previous)
        for candidate in ranked:
            if candidate.status == "explored":
                continue
            if candidate.confidence_class == "P0":
                candidate.status = "active"
                selected.append(candidate)
                continue  # User inputs never lose admission to an exploration cap.
            reason = None
            if candidate.id in previous:
                pass  # Repeated selection in one LLM turn cannot reset budgets.
            elif not ready.intersection(candidate.possible_tools):
                reason = "no compatible tool currently runnable"
            elif admitted >= settings.pivot_max_total and not candidate.selected_rounds:
                reason = "total exploration budget"
            elif round_count >= settings.pivot_max_per_round:
                reason = "round pivot budget"
            elif cost + candidate.exploration_cost > settings.pivot_round_cost_budget:
                reason = "round exploration cost budget"
            elif mode != "deep" and candidate.pivot_priority < settings.pivot_min_priority:
                reason = "standard priority threshold"
            elif mode != "deep" and candidate.confidence_class == "P4" and weak >= settings.pivot_max_weak_per_round:
                reason = "standard weak pivot budget"
            if reason:
                candidate.status, candidate.deferred_reason = "deferred", reason
                continue
            candidate.status, candidate.deferred_reason = "active", None
            selected.append(candidate)
            if candidate.id not in previous:
                weak += candidate.confidence_class == "P4"
                cost += candidate.exploration_cost
                round_count += 1
            admitted += not bool(candidate.selected_rounds)
        for candidate in selected:
            if round_index not in candidate.selected_rounds:
                candidate.selected_rounds.append(round_index)
        self.decisions.append({"round": round_index, "mode": mode, "selected": [c.id for c in selected],
                               "estimated_cost": cost, "deferred": sum(c.status == "deferred" for c in ranked)})
        self.save()
        return selected

    def suggest(self, args, round_index):
        """LLM inputs may propose weak leads; they cannot supply evidence roles."""
        from app.engine.pivot_rules import EMAIL_REGEX, USERNAME_REGEX, IGNORE_EMAIL_PREFIXES, IGNORE_USERNAMES
        from app.tools.maigret_ids import add_identifiers, identifier_values
        requested = set()
        def add(kind, value):
            key = pivot_id(kind, value)
            requested.add(key)
            if key not in self.candidates:
                self.add(kind, value, round_index, PivotSupport(observation_key="suggestion:" + key,
                    source_tool="hybrid_suggestion", evidence_role="suggested_input", evidence_class="weak"))
            if kind in DISCOVERED:
                original = getattr(self.context, DISCOVERED[kind])
                existing = [*original, getattr(self.context, PRIMARY[kind])]
                if not any(v and pivot_id(kind, v) == key for v in existing):
                    original.append(value)
            elif kind == "url":
                urls = self.context.extra.setdefault("candidate_urls", [])
                if value not in urls:
                    urls.append(value)
        for kind, field in PRIMARY.items():
            value = args.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            value = value.strip()
            if kind == "email":
                value = value.lower()
                if not EMAIL_REGEX.fullmatch(value) or value.split("@")[0] in IGNORE_EMAIL_PREFIXES:
                    raise ValueError("invalid email suggestion")
            if kind == "username":
                value = value.lstrip("@")
                if not USERNAME_REGEX.fullmatch(value) or value.lower() in IGNORE_USERNAMES:
                    raise ValueError("invalid username suggestion")
            if kind == "phone":
                value = phone_identity(value)
                if not value:
                    raise ValueError("invalid phone suggestion")
            if kind == "dni":
                from app.tools.dni_public import normalize_dni
                value = normalize_dni(value)
                if not value or value != self.context.dni:
                    raise ValueError("DNI expansion is not an existing pivot capability")
            args[field] = value
            add(kind, value)
        urls = args.get("candidate_urls", [])
        if urls is not None and not isinstance(urls, (str, list)):
            raise ValueError("public URL suggestions must be an array")
        urls = [urls] if isinstance(urls, str) else urls
        for raw in [args.get("url"), *(urls or [])]:
            if raw is None:
                continue
            value = public_source_url(raw)
            if not value:
                raise ValueError("invalid public URL suggestion")
            add("url", value)
        identifiers = identifier_values(args.get("identifiers", []))
        add_identifiers(self.context, identifiers, source_tool="hybrid_suggestion")
        for item in identifiers:
            add(item["id_type"], item["value"])
        self.sync(round_index)
        return requested

    def execution_view(self):
        view = self.context.model_copy(deep=False)
        view.extra = dict(self.context.extra)
        allowed = {c.id for c in self.candidates.values() if c.status in {"active", "explored"}}
        order = {c.id: n for n, c in enumerate(self.rank())}
        def values(kind, items):
            return sorted((v for v in items if v and pivot_id(kind, v) in allowed), key=lambda v: order[pivot_id(kind, v)])
        for kind, field in PRIMARY.items():
            setattr(view, field, getattr(self.context, field) if pivot_id(kind, getattr(self.context, field) or "") in allowed else None)
        for kind, field in DISCOVERED.items():
            setattr(view, field, values(kind, getattr(self.context, field)))
            # Several legacy tools use BaseTool.can_run(), which checks the
            # primary field. Give them the first admitted discovered input when
            # the user supplied no seed of this type, without changing the seed.
            if not getattr(view, PRIMARY[kind]) and getattr(view, field):
                setattr(view, PRIMARY[kind], getattr(view, field)[0])
        for field in URL_FIELDS:
            view.extra[field] = values("url", self.context.extra.get(field, []))
        view.extra["avatar_urls"] = values("avatar", self.context.extra.get("avatar_urls", []))
        view.extra["maigret_identifiers"] = sorted((dict(item) for item in self.context.extra.get("maigret_identifiers", [])
            if pivot_id(item["id_type"], item["value"]) in allowed), key=lambda item: order[pivot_id(item["id_type"], item["value"])])
        return view

    def merge_view(self, view):
        for field in DISCOVERED.values():
            original = getattr(self.context, field)
            original.extend(v for v in getattr(view, field) if v not in original)
        for field, value in view.extra.items():
            if field == "pivot_frontier":
                continue
            if field in INPUT_LISTS:
                original = self.context.extra.setdefault(field, [])
                original.extend(v for v in value if v not in original)
            else:
                self.context.extra[field] = value

    def mark_explored(self, view, tools, successful):
        visible = {pivot_id(kind, value) for kind, value in context_inputs(view)}
        for candidate in self.candidates.values():
            if candidate.id not in visible:
                continue
            for tool in tools:
                if tool.name in successful and tool_accepts(tool, candidate) and tool.name not in candidate.explored_by:
                    candidate.explored_by.append(tool.name)
            candidate.status = "explored" if candidate.explored_by else "pending"
        self.rank()
        self.save()

    def release_active(self):
        for candidate in self.candidates.values():
            if candidate.status == "active":
                candidate.status = "pending"
        self.save()

    def snapshot(self, limit=None):
        ranked = sorted(self.candidates.values(), key=lambda c: (-c.pivot_priority, c.discovered_round, c.id))
        groups = {status: [c.model_dump(mode="json") for c in ranked if c.status == status]
                  for status in ("pending", "active", "explored", "deferred")}
        return {"version": VERSION, "semantics": SEMANTICS, **{k: v[:limit] if limit else v for k, v in groups.items()},
                "summary": {"total": len(ranked), **{k: len(v) for k, v in groups.items()},
                    "high": sum(c.confidence_class in {"P0", "P1", "P2"} for c in ranked),
                    "medium": sum(c.confidence_class == "P3" for c in ranked),
                    "low": sum(c.confidence_class == "P4" for c in ranked)},
                "decisions": self.decisions, "duplicate_executions_avoided": self.duplicate_executions_avoided}

    def digest(self):
        ranked = self.rank()
        def compact(c):
            return {"type": c.type, "value": c.value, "class": c.confidence_class,
                    "pivot_priority": c.pivot_priority, "status": c.status,
                    "reasons": c.reasons[:4], "possible_tools": c.possible_tools,
                    "deferred_reason": c.deferred_reason}
        unresolved = [c for c in ranked if c.status != "explored"]
        return {"semantics": SEMANTICS, "high_priority_unresolved": [compact(c) for c in unresolved
                    if c.confidence_class in {"P0", "P1", "P2"}][:5],
                "medium_unresolved": [compact(c) for c in unresolved if c.confidence_class == "P3"][:5],
                "weak_available": [compact(c) for c in unresolved if c.confidence_class == "P4"][:5],
                "summary": self.snapshot()["summary"]}


def frontier_from_metrics(metrics):
    state = metrics.get("external_runtime", {}).get("pivot_frontier") or metrics.get("collection_runtime", {}).get("pivot_frontier", {})
    return PivotFrontier(TargetContext(extra={"pivot_frontier": state})).snapshot()
