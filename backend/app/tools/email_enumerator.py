"""Bounded email registration checks with reviewed Holehe query techniques."""
import asyncio
from collections import Counter
import json
import re
import secrets
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup
import httpx

from app.core.config import settings
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.email_catalog import HOLEHE_COMMIT, capabilities, config_id, parse_registration, selected_probes


def valid_email(value):
    return isinstance(value, str) and len(value) <= 254 and bool(re.fullmatch(r"[^\s@/?#\\]+@[^\s@/?#\\]+\.[^\s@/?#\\]+", value))


def fill(payload, email):
    if isinstance(payload, dict):
        return {key: fill(value, email) for key, value in payload.items()}
    return email if payload == "{email}" else payload


def response_status(response, accepted=(200, 422)):
    code = response.status_code
    if code == 429:
        return "rate_limited"
    if code in {401, 403}:
        return "blocked"
    if code in {404, 410}:
        return "unavailable"
    if code >= 500:
        return "upstream_error"
    if 300 <= code < 400:
        return "redirected"
    if any(marker in response.text[:200_000].lower() for marker in (
            "cf-chl-", "challenge-platform", "captcha-required", "verify you are human")):
        return "blocked"
    if code not in accepted:
        return "unexpected_response"
    return None


class EmailEnumeratorTool(BaseTool):
    name = "email_enumerator"
    description = (
        "Busca señales de registro por correo con comprobaciones de consulta/validación "
        "adaptadas de Holehe. Distingue registro, sin registro, bloqueos y errores; "
        "no identifica automáticamente el perfil. Google se consulta con GHunt."
    )
    category = ToolCategory.EMAIL
    required_inputs = ["email"]
    cache_prefix = "email_enum_"

    @staticmethod
    def capabilities():
        return capabilities()

    def pending(self, context):
        checked = context.extra.get("email_enum_checked", []) if context.extra.get("email_enum_config_id") == config_id() else []
        emails = [email for email in context.all_emails() if valid_email(email)]
        admitted = list(dict.fromkeys([*checked, *emails]))[:settings.email_enum_max_emails]
        return [email for email in emails if email in admitted and email not in checked] if selected_probes() else []

    def can_run(self, context):
        return bool(self.pending(context))

    @staticmethod
    def _invented_email(email):
        """Random control in the same domain; absence must still be observed."""
        return "pm" + secrets.token_hex(12) + "@" + email.rsplit("@", 1)[1]

    async def probe(self, client, email, spec, diagnostics):
        payload, headers = fill(spec.payload, email), {"Accept": "application/json", **spec.headers}

        async def request(method, url, *, accepted=(200,), **kwargs):
            diagnostics["requests"] += 1
            response = await client.request(method, url, **kwargs)
            diagnostics["http_status"] = response.status_code
            status = response_status(response, accepted)
            if status:
                raise ProbeUnavailable(status)
            return response

        if spec.warmup:
            warmup = await request("GET", spec.warmup)
            soup = BeautifulSoup(warmup.text, "html.parser")
            headers["Referer"] = spec.warmup
            if spec.csrf == "github":
                token = None
                for check in soup.select("auto-check[src]"):
                    if urlsplit(check.get("src", "")).path == urlsplit(spec.url).path:
                        node = check.select_one('input[name="authenticity_token"][value], input[data-csrf="true"][value]')
                        token = node.get("value") if node else check.get("csrf")
                        break
                if not token:
                    raise ProbeUnavailable("csrf_unavailable")
                payload["authenticity_token"] = token
            elif spec.csrf == "meta":
                token = soup.select_one('meta[name="csrf-token"][content]')
                if not token or not token.get("content"):
                    raise ProbeUnavailable("csrf_unavailable")
                headers["X-CSRF-Token"] = token["content"]
                headers["X-Requested-With"] = "XMLHttpRequest"
            else:
                token = warmup.cookies.get("csrftoken")
                if not token:
                    raise ProbeUnavailable("csrf_unavailable")
                if spec.csrf == "lastfm":
                    payload["csrfmiddlewaretoken"] = token
                else:
                    headers["X-CSRFToken"] = token
        if spec.key == "pinterest":
            payload["data"] = json.dumps(payload["data"])
        response = await request(spec.method, spec.url.replace("{email}", quote(email, safe="")),
                                 accepted=spec.response_codes, headers=headers, **{spec.send: payload})
        if spec.parser == "steam":
            try:
                if response.json().get("success") == 84:
                    raise ProbeUnavailable("rate_limited")
            except (ValueError, AttributeError):
                pass
        if spec.parser == "miro":
            try:
                data = response.json()
                if isinstance(data, dict) and isinstance(data.get("recommendedAuthenticationType"), str):
                    # The operator's known account and a random same-domain
                    # control both return CREDENTIALS. This is not absence.
                    return {"status": "auth_hint_only", "registered": None}
            except ValueError:
                pass
        registered = parse_registration(spec.parser, response)
        return {"status": "registered" if registered is True else "not_registered" if registered is False else "unexpected_response",
                "registered": registered}

    async def _run_probe(self, email, spec, gate, diagnostics):
        diagnostics.update(status="pending", requests=0)
        async with gate:
            try:
                async with asyncio.timeout(settings.email_enum_probe_timeout):
                    # A CSRF warmup and its validation share a private cookie jar.
                    async with http_client.build_client(timeout=settings.email_enum_request_timeout,
                            follow_redirects=False, max_retries=0, rotate_ua=False,
                            public_only=True, trust_env=False) as client:
                        result = await self.probe(client, email, spec, diagnostics)
                        diagnostics["status"] = result["status"]
                        if result.get("registered") is not True:
                            return None
                        control_diagnostics = {"requests": 0}
                        try:
                            control = await self.probe(client, self._invented_email(email), spec, control_diagnostics)
                            control_status = control["status"]
                        except ProbeUnavailable as exc:
                            control_status = exc.status
                        except (httpx.TimeoutException, TimeoutError):
                            control_status = "timeout"
                        except Exception:
                            control_status = "transport_error"
                        finally:
                            diagnostics["requests"] += control_diagnostics["requests"]
                        diagnostics["control_status"] = control_status
                        if control_status == "registered":
                            diagnostics["status"] = "non_discriminating"
                            return None
                        negative_control = "passed" if control_status == "not_registered" else "untested"
                        return ToolFinding(entity_type="email_registration", platform=spec.platform,
                            value=f"{spec.platform} ({email})", display_name=f"{spec.platform}: Señal de registro por correo",
                            confidence=0.65 if negative_control == "passed" else 0.4,
                            metadata_info={"email": email, "platform": spec.platform, "registered": True,
                                "category": spec.category, "service_url": spec.home,
                                "verification_status": "registration_signal", "profile_status": "unresolved",
                                "source_tool": self.name, "negative_control": negative_control,
                                "probe_id": spec.key, "technique": "email_validation_query",
                                "probe_origin": "holehe_adapted" if spec.upstream else "person_map",
                                **({"adaptation_reference": spec.reference} if spec.reference else {}),
                                **({"holehe_commit": HOLEHE_COMMIT, "holehe_module": spec.upstream} if spec.upstream else {})},
                            evidence_urls=[spec.url.replace("{email}", quote(email, safe=""))])
            except ProbeUnavailable as exc:
                diagnostics["status"] = exc.status
            except (TimeoutError, httpx.TimeoutException):
                diagnostics["status"] = "timeout"
            except httpx.HTTPError:
                diagnostics["status"] = "transport_error"
            except asyncio.CancelledError:
                diagnostics["status"] = "interrupted"
                raise
            except Exception:
                diagnostics["status"] = "unexpected_response"
            return None

    async def execute(self, context: TargetContext):
        signature = config_id()
        if context.extra.get("email_enum_config_id") != signature:
            context.extra.update(email_enum_config_id=signature, email_enum_checked=[], email_enum_diagnostics={})
        emails = self.pending(context)
        if not emails:
            return []
        diagnostics = context.extra["email_enum_diagnostics"]
        gate = asyncio.Semaphore(settings.tool_concurrency_budget(settings.email_enum_concurrency))
        tasks = []
        for email in emails:
            context.extra["email_enum_checked"].append(email)
            per_email = diagnostics.setdefault(email, {})
            for spec in selected_probes():
                state = per_email.setdefault(spec.key, {"status": "pending", "requests": 0})
                tasks.append(asyncio.create_task(self._run_probe(email, spec, gate, state)))
        try:
            done, pending = await asyncio.wait(tasks, timeout=settings.email_enum_batch_timeout)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for per_email in diagnostics.values():
                for state in per_email.values():
                    if state["status"] in {"pending", "interrupted"}:
                        state["status"] = "budget_exhausted"
            return [task.result() for task in tasks if task in done and not task.cancelled() and task.result() is not None]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


class ProbeUnavailable(Exception):
    def __init__(self, status):
        self.status = status


def execution_summary(context):
    diagnostics = context.extra.get("email_enum_diagnostics", {})
    counts = Counter(state.get("status", "unknown") for sites in diagnostics.values() for state in sites.values())
    return {"catalog_id": context.extra.get("email_enum_config_id"),
            "holehe_commit": HOLEHE_COMMIT, "emails_checked": len(context.extra.get("email_enum_checked", [])),
            "counts": dict(sorted(counts.items())),
            "requests": sum(state.get("requests", 0) for sites in diagnostics.values() for state in sites.values())}
