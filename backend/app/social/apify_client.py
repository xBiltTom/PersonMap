"""Bounded Apify REST client. Paid starts are NEVER retried after ambiguous failures."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import re

import httpx

from app.core.config import settings
from app.social.capabilities import actor_build
from app.tools import http_client

API = "https://api.apify.com/v2"
TERMINAL = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}


def identifier(value):
    token = settings.apify_token.get_secret_value() if settings.apify_token else None
    return value if isinstance(value, str) and value != token and re.fullmatch(r"[A-Za-z0-9]{1,100}", value) else None


class ApifyError(Exception):
    def __init__(self, code):
        super().__init__(code)  # Never include response bodies, URLs or headers.
        self.code = code


@dataclass
class ApifyRunResult:
    actor: str
    status: str = "not_started"
    actor_id: str | None = None
    run_id: str | None = None
    dataset_id: str | None = None
    build_id: str | None = None
    build_number: str | None = None
    retrieved_at: str | None = None
    error: str | None = None
    usage: dict = field(default_factory=dict)
    items: list = field(default_factory=list)

    def summary(self):
        return {key: getattr(self, key) for key in ("actor", "actor_id", "run_id", "dataset_id",
            "build_id", "build_number", "status", "retrieved_at", "error", "usage")} | {"items_read": len(self.items)}

    def update(self, raw):
        if not isinstance(raw, dict) or not identifier(raw.get("id")):
            raise ApifyError("run_schema_changed")
        if self.run_id and self.run_id != raw["id"]:
            raise ApifyError("run_id_mismatch")
        self.run_id = raw["id"]
        if raw.get("status") not in TERMINAL | {"READY", "RUNNING", "TIMING-OUT", "ABORTING"}:
            raise ApifyError("run_schema_changed")
        self.run_id, self.status = raw["id"], raw["status"]
        for field_name, key in (("actor_id", "actId"), ("dataset_id", "defaultDatasetId"), ("build_id", "buildId")):
            if value := identifier(raw.get(key)):
                setattr(self, field_name, value)
        number = raw.get("buildNumber")
        if isinstance(number, str) and re.fullmatch(r"[0-9.]{1,40}", number):
            self.build_number = number
        stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else {}
        for name, value in (("usageTotalUsd", raw.get("usageTotalUsd")), ("computeUnits", stats.get("computeUnits")),
                            ("runTimeSecs", stats.get("runTimeSecs"))):
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                self.usage[name] = value


class ApifyClient:
    async def _json(self, client, method, path, *, params=None, payload=None):
        attempts = 1 + (settings.apify_max_retries if method == "GET" else 0)
        for attempt in range(attempts):
            try:
                async with client.stream(method, API + path, params=params, json=payload) as response:
                    if response.status_code >= 500 and attempt + 1 < attempts:
                        continue
                    if not 200 <= response.status_code < 300:
                        raise ApifyError({401: "authentication_failed", 403: "access_denied", 402: "quota_exhausted",
                            429: "rate_limited"}.get(response.status_code,
                            "upstream_error" if response.status_code >= 500 else "unexpected_http_status"))
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > settings.apify_max_response_bytes:
                            raise ApifyError("response_too_large")
                try:
                    return json.loads(body)
                except (ValueError, UnicodeError):
                    raise ApifyError("invalid_json") from None
            except httpx.HTTPError:
                if attempt + 1 == attempts:
                    raise ApifyError("network_error") from None
        raise ApifyError("network_error")

    async def _abort(self, client, run_id):
        try:
            async with asyncio.timeout(5):
                await self._json(client, "POST", f"/actor-runs/{run_id}/abort")
            return True
        except (ApifyError, TimeoutError):
            return False

    async def run(self, spec, actor_input, item_limit, charge_limit, *, on_update=lambda result: None):
        result = ApifyRunResult(actor=spec.actor)
        token = settings.apify_token.get_secret_value() if settings.apify_token else ""
        if not token.strip():
            result.error = result.status = "token_missing"
            return result
        async with http_client.build_client(timeout=settings.apify_request_timeout, rotate_ua=False,
                max_retries=0, public_only=True, follow_redirects=False, trust_env=False,
                headers={"Authorization": "Bearer " + token, "User-Agent": "PersonMap/public-footprint-social/1"}) as client:
            try:
                async with asyncio.timeout(settings.apify_run_timeout):
                    raw = await self._json(client, "POST", f"/actors/{spec.actor.replace('/', '~')}/runs",
                        params={"timeout": settings.apify_run_timeout, "maxItems": item_limit,
                            "maxTotalChargeUsd": charge_limit, "restartOnError": "false", "build": actor_build(spec)},
                        payload=actor_input)
                    result.update(raw.get("data") if isinstance(raw, dict) else None)
                    on_update(result.summary())
                    while result.status not in TERMINAL:
                        raw = await self._json(client, "GET", f"/actor-runs/{result.run_id}", params={"waitForFinish": 5})
                        result.update(raw.get("data") if isinstance(raw, dict) else None)
                        on_update(result.summary())
                        if result.status not in TERMINAL:
                            await asyncio.sleep(0.1)  # Also bound unexpectedly immediate poll responses.
                    if result.status != "SUCCEEDED":
                        result.error = "actor_run_failed"
                    # A failed Actor can still have useful public partial rows.
                    if result.dataset_id:
                        offset = 0
                        while len(result.items) < item_limit:
                            limit = min(settings.apify_dataset_page_size, item_limit - len(result.items))
                            rows = await self._json(client, "GET", f"/datasets/{result.dataset_id}/items",
                                params={"clean": "true", "format": "json", "limit": limit, "offset": offset})
                            if not isinstance(rows, list):
                                raise ApifyError("dataset_schema_changed")
                            result.items.extend(rows[:limit])
                            if len(rows) < limit:
                                break
                            offset += limit
                    elif not result.error:
                        result.error = "dataset_missing"
            except (ApifyError, TimeoutError, ValueError) as error:
                result.error = error.code if isinstance(error, ApifyError) else "timeout" if isinstance(error, TimeoutError) else "invalid_actor_build"
                if result.run_id and result.status not in TERMINAL:
                    aborted = await self._abort(client, result.run_id)
                    result.status = "abort_requested" if aborted else "abort_failed"
                elif not result.run_id:
                    result.status = "start_uncertain"  # Do not resubmit a possibly billed POST.
            except asyncio.CancelledError:
                result.error = "cancelled"
                if result.run_id and result.status not in TERMINAL:
                    aborted = await asyncio.shield(self._abort(client, result.run_id))
                    result.status = "abort_requested" if aborted else "abort_failed"
                raise
            finally:
                result.retrieved_at = datetime.now(timezone.utc).isoformat()
                on_update(result.summary())
        return result
