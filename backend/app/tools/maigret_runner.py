"""Run Maigret workers with shared HTTP budgets and cancellable JSONL RPC."""
import asyncio
import base64
import json
import os
import socket
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import settings
from app.tools import http_client
from app.tools.maigret_catalog import database_path, native_recipes
from app.tools.public_network import UnsafePublicURL, public_address
from app.tools.social_profiles import normalize_web_url

MAX_BODY = 4 * 1024 * 1024


async def public_ips(url):
    if normalize_web_url(url, keep_query=True) is None:
        raise UnsafePublicURL("Invalid public destination")
    parsed = urlsplit(url)
    addresses = await asyncio.get_running_loop().getaddrinfo(
        parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    ips = list(dict.fromkeys(info[4][0] for info in addresses))
    if not ips or not all(public_address(ip) for ip in ips):
        raise UnsafePublicURL("Destination is not public")
    return ips


def hidden_proxy(url):
    host = (urlsplit(url).hostname or "").lower()
    protocol = "tor" if host.endswith(".onion") else "i2p" if host.endswith(".i2p") else None
    if not protocol:
        return None
    configured = settings.maigret_tor_proxy if protocol == "tor" else settings.maigret_i2p_proxy
    if not configured:
        raise UnsafePublicURL("Hidden service gateway is not configured")
    for site in native_recipes(id_type=None, protocols=(protocol,)).values():
        template = urlsplit(site.url).hostname or ""
        pattern = re.escape(template).replace(re.escape("{username}"), "[a-z0-9_-]+")
        if re.fullmatch(pattern, host, re.IGNORECASE):
            proxy = configured.get_secret_value()
            return "socks5h://" + proxy.removeprefix("socks5://") if proxy.startswith("socks5://") else proxy
    raise UnsafePublicURL("Hidden service is outside the native catalogue")


def wire_response(response):
    if len(response.content) > MAX_BODY:
        raise ValueError("Worker response exceeds body limit")
    return {"status": response.status_code, "url": str(response.url),
            "headers": dict(decoded_headers(response.headers.multi_items())), "encoding": response.encoding,
            "cookies": dict(response.cookies), "body": base64.b64encode(response.content).decode("ascii")}


async def solver_request(message):
    """Only an administrator-configured JSON solver endpoint is trusted locally."""
    payload = message.get("json") or {}
    target = payload.get("url", "")
    if message["method"] != "POST" or payload.get("cmd") not in {"request.get", "request.post"}:
        raise UnsafePublicURL("Invalid solver operation")
    await public_ips(target)
    timeout = min(float(message.get("timeout") or 65), 120)
    async with http_client.outgoing_budget(urlsplit(target).hostname):
        async with httpx.AsyncClient(trust_env=False, timeout=timeout) as service:
            response = await service.post(settings.maigret_solver_url, json=payload, follow_redirects=False)
    response.raise_for_status()
    data = response.json()
    result = wire_response(response)
    if data.get("status") == "ok":
        solution = data.get("solution") or {}
        final = solution.get("url") or target
        await public_ips(final)
        upstream = httpx.Response(int(solution.get("status") or 502),
            headers=decoded_headers((solution.get("headers") or {}).items()),
            content=(solution.get("response") or "").encode(), request=httpx.Request("GET", final))
        result["target_response"] = {**wire_response(upstream), "request_url": target}
    return result


def decoded_headers(items):
    """The RPC and curl bodies are decoded bytes, not compressed wire bodies.

Reusing Content-Encoding makes httpx decode them a second time. Wire lengths
and transfer framing likewise no longer describe these in-memory bodies.
"""
    return [(key, value) for key, value in items
            if key.lower() not in {"content-encoding", "content-length", "transfer-encoding"}]


async def browser_request(client, message):
    """Native curl impersonation, with verified TLS and pinned public DNS.

Redirects are followed here so every destination gets its own DNS validation
and host budget. The child cannot create an unrestricted browser session.
"""
    from curl_cffi import CurlOpt
    from curl_cffi.requests import AsyncSession
    url = message["url"]
    if message.get("params"):
        url = str(httpx.URL(url).copy_merge_params(message["params"]))
    method = message["method"]
    headers = dict(message.get("headers") or {})
    payload = message.get("json")
    form = message.get("data")
    timeout = float(message.get("timeout") or settings.maigret_request_timeout)
    for _ in range(7):
        if normalize_web_url(url, keep_query=True) is None:
            raise UnsafePublicURL("Invalid browser destination")
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        gateway = hidden_proxy(url)
        kind = message.get("gateway")
        configured = getattr(settings, "maigret_" + kind + "_proxy", None) if kind in {"tor", "i2p"} else settings.maigret_proxy
        if kind in {"tor", "i2p"} and not configured:
            raise UnsafePublicURL("Requested gateway is not configured")
        proxy = gateway or (configured.get_secret_value() if configured else None)
        options = {}
        if not gateway:
            ips = await public_ips(url)
            resolved = ",".join(f"[{ip}]" if ":" in ip else ip for ip in ips)
            options[CurlOpt.RESOLVE] = [f"{host}:{port}:{resolved}"]
            if proxy:
                # CONNECT_TO forces proxy tunnels to the validated IP too;
                # the original hostname is retained for HTTP Host and TLS.
                address = f"[{ips[0]}]" if ":" in ips[0] else ips[0]
                options[CurlOpt.CONNECT_TO] = [f"{host}:{port}:{address}:{port}"]
        request_headers = dict(client.build_request(method, url, headers=headers).headers)
        # curl supplies the UA matching its TLS impersonation.
        request_headers.pop("user-agent", None)
        async with http_client.outgoing_budget(host):
            async with AsyncSession(curl_options=options, trust_env=False) as session:
                response = await session.request(method, url, headers=request_headers, json=payload,
                    data=form, proxy=proxy,
                    impersonate=message.get("browser") or "chrome", verify=True,
                    timeout=timeout, allow_redirects=False)
        result = httpx.Response(response.status_code, headers=decoded_headers(response.headers.multi_items()),
                                content=response.content, request=httpx.Request(method, url))
        client.cookies.extract_cookies(result)
        if message.get("allow_redirects", True) and result.status_code in {301, 302, 303, 307, 308}:
            location = result.headers.get("location")
            if not location:
                return result
            next_url = urljoin(url, location)
            if urlsplit(next_url).netloc != parsed.netloc:
                headers = {k: v for k, v in headers.items() if k.lower() not in {"authorization", "cookie"}}
            if result.status_code == 303 or (result.status_code in {301, 302} and method == "POST"):
                method, payload, form = "GET", None, None
            url = next_url
            continue
        return result
    raise httpx.TooManyRedirects("Browser redirect limit exceeded")


async def perform_request(client, message):
    if message["method"] == "DNS":
        if not settings.maigret_check_domains or not re.fullmatch(r"[A-Za-z0-9.-]+", message["url"]):
            raise UnsafePublicURL("Invalid DNS query")
        url = "https://" + message["url"]
        async with http_client.outgoing_budget(message["url"]), asyncio.timeout(settings.maigret_request_timeout):
            try:
                ips = await public_ips(url)
                response = httpx.Response(200, text="\n".join(ips), request=httpx.Request("GET", url))
            except socket.gaierror:
                response = httpx.Response(404, request=httpx.Request("GET", url))
        return wire_response(response)
    if message["method"] not in {"GET", "POST", "HEAD"}:
        raise ValueError("Unsupported worker method")
    if settings.maigret_solver_url and message["url"] == settings.maigret_solver_url:
        return await solver_request(message)
    if normalize_web_url(message["url"], keep_query=True) is None:
        raise UnsafePublicURL("Invalid worker URL")
    timeout = float(message.get("timeout") or settings.maigret_request_timeout)
    async with asyncio.timeout(timeout):
        if message.get("browser") or hidden_proxy(message["url"]) or settings.maigret_proxy or message.get("gateway"):
            response = await browser_request(client, message)
        else:
            options = {key: message[key] for key in ("headers", "json", "data", "params") if key in message}
            response = await client.request(message["method"], message["url"], timeout=timeout,
                follow_redirects=message.get("allow_redirects", True), **options)
    return wire_response(response)


async def run_maigret(username, sites, controls, on_result, on_progress=None, *, request_semaphore=None,
                      id_type="username", operation="search", urls=None, parts=None, limit=None, options=None,
                      records=None, report_format=None):
    """Native job failures remain visible; no silent switch of search engine."""
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    requests = set()

    async def drain_errors():
        # Upstream sometimes logs extracted page content. Do not persist it or
        # expose potentially sensitive headers; failures use the JSON channel.
        while await process.stderr.read(8192):
            pass

    job = {"username": username, "sites": [site.native_name for site in sites],
           "controls": controls, "database": str(database_path()),
           "timeout": settings.maigret_request_timeout,
           "concurrency": settings.tool_concurrency_budget(settings.username_scan_concurrency),
           "enrich": settings.maigret_enrich, "keywords": settings.maigret_keywords,
           "parse": settings.maigret_parse, "retries": settings.maigret_retries,
           "id_type": id_type, "operation": operation, "urls": urls or [], "parts": parts or [], "limit": limit,
           "records": records or [], "report_format": report_format,
           "cookies": str(Path(settings.maigret_cookie_file).resolve()) if settings.maigret_cookie_file else None,
           "check_domains": settings.maigret_check_domains,
           "queue_grace": settings.maigret_queue_grace,
           "solver_timeout": settings.maigret_solver_timeout, "solver_concurrency": settings.maigret_solver_concurrency,
           **{name: getattr(settings, "maigret_" + name).get_secret_value() if getattr(settings, "maigret_" + name) else None
              for name in ("proxy", "tor_proxy", "i2p_proxy")}}
    job.update({key: value for key, value in (options or {}).items() if key in {"enrich", "parse", "keywords", "retries"}})
    if settings.maigret_solver_url:
        job["cloudflare_bypass"] = {"trigger_protection": ["cf_js_challenge", "cf_firewall", "js_challenge"],
            "modules": [{"method": "json_api", "url": settings.maigret_solver_url,
                         "max_timeout_ms": max(1000, int(settings.maigret_solver_timeout * 1000) - 5000)}]}
    import hashlib
    job["database_sha256"] = hashlib.sha256(Path(job["database"]).read_bytes()).hexdigest()
    from app.tools import maigret_catalog
    if Path(job["database"]).resolve() == Path(maigret_catalog.database_path()).resolve():
        if job["database_sha256"] != maigret_catalog.database_info()["maigret_catalog_sha256"]:
            raise RuntimeError("Catalogue changed; restart the service to load its recipes and fingerprint")
    if operation == "permute" and (len(job["parts"]) > 3 or not 0 <= (limit or 0) <= 100):
        raise ValueError("Permutation budget exceeded")
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.tools.maigret_worker", cwd=root, env=environment,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, limit=16 * 1024 * 1024,
    )
    errors = asyncio.create_task(drain_errors())
    try:
        async with http_client.build_client(timeout=settings.maigret_request_timeout,
                                            public_only=True, rotate_ua=False) as client:
            if settings.maigret_cookie_file and operation in {"search", "extract", "self_check"}:
                from http.cookiejar import MozillaCookieJar
                jar = MozillaCookieJar(settings.maigret_cookie_file)
                try:
                    jar.load(ignore_discard=True, ignore_expires=False)
                except (OSError, ValueError):
                    raise RuntimeError("The configured Maigret cookie file could not be loaded") from None
                for cookie in jar:
                    client.cookies.jar.set_cookie(cookie)
            async def respond(message):
                try:
                    if request_semaphore is None:
                        payload = await perform_request(client, message)
                    else:
                        # Native and complementary checks belong to one tool;
                        # their concurrent requests must share its quota too.
                        async with request_semaphore:
                            payload = await perform_request(client, message)
                except Exception as exc:
                    # Error type suffices for diagnostics; URLs/headers may carry tokens.
                    payload = {"error": type(exc).__name__}
                if process.returncode is None:
                    process.stdin.write((json.dumps({"id": message["id"], **payload}) + "\n").encode())
                    await process.stdin.drain()

            async with asyncio.timeout(settings.maigret_worker_timeout):
                process.stdin.write((json.dumps(job) + "\n").encode())
                await process.stdin.drain()
                done = False
                while line := await process.stdout.readline():
                    message = json.loads(line)
                    if message["event"] == "request":
                        task = asyncio.create_task(respond(message))
                        requests.add(task)
                        def finished(task):
                            requests.discard(task)
                            if not task.cancelled():
                                task.exception()
                        task.add_done_callback(finished)
                    elif message["event"] == "result":
                        await on_result(message["result"])
                    elif message["event"] == "progress" and on_progress:
                        await on_progress(message)
                    elif message["event"] == "failure":
                        raise RuntimeError("Maigret worker failed: " + message["error"])
                    elif message["event"] == "done":
                        done = True
                code = await process.wait()
                if code or not done:
                    raise RuntimeError(f"Maigret worker stopped before completion ({code})")
    finally:
        for task in list(requests):
            task.cancel()
        await asyncio.gather(*requests, return_exceptions=True)
        if process.returncode is None:
            process.kill()
        await process.wait()
        await errors
