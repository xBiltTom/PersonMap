"""Run Maigret workers with shared HTTP budgets and cancellable JSONL RPC."""
import asyncio
import base64
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import settings
from app.tools import http_client
from app.tools.maigret_catalog import database_path
from app.tools.public_network import UnsafePublicURL, public_address
from app.tools.social_profiles import normalize_web_url

MAX_BODY = 4 * 1024 * 1024


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
    method = message["method"]
    headers = dict(message.get("headers") or {})
    payload = message.get("json")
    timeout = float(message.get("timeout") or settings.maigret_request_timeout)
    for _ in range(7):
        if normalize_web_url(url, keep_query=True) is None:
            raise UnsafePublicURL("Invalid browser destination")
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(info[4][0] for info in addresses))
        if not ips or not all(public_address(ip) for ip in ips):
            raise UnsafePublicURL("Browser destination is not public")
        resolved = ",".join(f"[{ip}]" if ":" in ip else ip for ip in ips)
        request_headers = dict(client.build_request(method, url, headers=headers).headers)
        # curl supplies the UA matching its TLS impersonation.
        request_headers.pop("user-agent", None)
        async with http_client.outgoing_budget(host):
            async with AsyncSession(curl_options={CurlOpt.RESOLVE: [f"{host}:{port}:{resolved}"]}, trust_env=False) as session:
                response = await session.request(method, url, headers=request_headers, json=payload,
                    impersonate=message.get("browser", "chrome"), verify=True,
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
                method, payload = "GET", None
            url = next_url
            continue
        return result
    raise httpx.TooManyRedirects("Browser redirect limit exceeded")


async def perform_request(client, message):
    if message["method"] not in {"GET", "POST", "HEAD"}:
        raise ValueError("Unsupported worker method")
    if normalize_web_url(message["url"], keep_query=True) is None:
        raise UnsafePublicURL("Invalid worker URL")
    timeout = float(message.get("timeout") or settings.maigret_request_timeout)
    async with asyncio.timeout(timeout):
        if message.get("browser"):
            response = await browser_request(client, message)
        else:
            options = {key: message[key] for key in ("headers", "json", "data", "params") if key in message}
            response = await client.request(message["method"], message["url"], timeout=timeout,
                follow_redirects=message.get("allow_redirects", True), **options)
    if len(response.content) > MAX_BODY:
        raise ValueError("Worker response exceeds body limit")
    return {"status": response.status_code, "url": str(response.url),
            "headers": dict(decoded_headers(response.headers.multi_items())), "encoding": response.encoding,
            "cookies": dict(response.cookies),
            "body": base64.b64encode(response.content).decode("ascii")}


async def run_maigret(username, sites, controls, on_result, on_progress=None, *, request_semaphore=None):
    """Native job failures remain visible; no silent switch of search engine."""
    root = Path(__file__).resolve().parents[2]
    environment = {**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.tools.maigret_worker", cwd=root, env=environment,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, limit=16 * 1024 * 1024,
    )
    requests = set()

    async def drain_errors():
        # Upstream sometimes logs extracted page content. Do not persist it or
        # expose potentially sensitive headers; failures use the JSON channel.
        while await process.stderr.read(8192):
            pass

    errors = asyncio.create_task(drain_errors())
    job = {"username": username, "sites": [site.native_name for site in sites],
           "controls": controls, "database": str(database_path()),
           "timeout": settings.maigret_request_timeout,
           "concurrency": settings.tool_concurrency_budget(settings.username_scan_concurrency),
           "enrich": settings.maigret_enrich, "keywords": settings.maigret_keywords}
    try:
        async with http_client.build_client(timeout=settings.maigret_request_timeout,
                                            public_only=True, rotate_ua=False) as client:
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
