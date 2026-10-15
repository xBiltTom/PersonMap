"""Cancellable GHunt JSONL worker; outbound HTTP uses PersonMap's shared budget."""
import asyncio
import base64
import json
import os
import re
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import settings
from app.tools import http_client
from app.tools.ghunt_runtime import ROOT, credentials_path, python_path

MAX_BODY = 4 * 1024 * 1024
_session_lock = None
_session_loop = None


def session_lock():
    # A single operator session is refreshed/written by only one child at a
    # time. Other tools retain all their normal concurrency.
    global _session_lock, _session_loop
    loop = asyncio.get_running_loop()
    if _session_loop is not loop:
        _session_lock, _session_loop = asyncio.Lock(), loop
    return _session_lock


def allowed_url(url):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        return (parsed.scheme == "https" and parsed.port in {None, 443}
                and not parsed.username and not parsed.password
                and any(host == domain or host.endswith("." + domain)
                        for domain in ("google.com", "googleapis.com", "googleusercontent.com", "ggpht.com")))
    except (TypeError, ValueError):
        return False


def cookie_validation_redirect(source, destination):
    """CheckCookie signals success via a regional SetSID Location.

The native checker only reads that header. It never follows it; outbound
requests to regional hosts still go through allowed_url and remain blocked.
"""
    try:
        source, destination = urlsplit(source), urlsplit(destination)
        return (source.scheme == "https" and source.hostname == "accounts.google.com"
                and source.path == "/CheckCookie" and destination.scheme == "https"
                and destination.port in {None, 443} and not destination.username and not destination.password
                and destination.path == "/accounts/SetSID"
                and bool(re.fullmatch(r"accounts\.google\.(?:(?:com|co)\.)?[a-z]{2,3}", destination.hostname or "")))
    except (ValueError, TypeError):
        return False


async def perform_request(client, message):
    url, method = message["url"], message["method"]
    if not allowed_url(url) or method not in {"GET", "POST", "HEAD"}:
        raise ValueError("GHunt destination rejected")
    headers = {key: value for key, value in message.get("headers", [])
               if key.lower() not in {"content-length", "connection", "transfer-encoding"}}
    if "host" in {key.lower() for key in headers}:
        supplied_host = next(value for key, value in headers.items() if key.lower() == "host")
        if not allowed_url("https://" + supplied_host):
            raise ValueError("GHunt Host rejected")
    body = base64.b64decode(message.get("body", ""), validate=True)
    if len(body) > MAX_BODY:
        raise ValueError("GHunt request limit")
    # Redirects remain in the child HTTPX client; each hop returns through this
    # policy. Prevent credential-bearing cross-host redirects at the source.
    client.cookies.clear()  # The child's domain-aware jar owns cookies, including anonymous calls.
    async with client.stream(method, url, headers=headers, content=body, follow_redirects=False,
                             timeout=settings.ghunt_request_timeout) as response:
        if response.is_redirect and response.headers.get("location"):
            destination = urljoin(url, response.headers["location"])
            if not allowed_url(destination) and not cookie_validation_redirect(url, destination):
                raise ValueError("GHunt redirect rejected")
        chunks, size = [], 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_BODY:
                raise ValueError("GHunt response limit")
            chunks.append(chunk)
        return {"status": response.status_code, "headers": [(key, value) for key, value in response.headers.multi_items()
                    if key.lower() not in {"content-encoding", "content-length", "transfer-encoding"}],
                "body": base64.b64encode(b"".join(chunks)).decode()}


async def run_ghunt(query, services):
    async with session_lock():
        async with asyncio.timeout(settings.ghunt_worker_timeout):
            return await _run(query, services)


async def _run(query, services):
    environment = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}}
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    process = await asyncio.create_subprocess_exec(str(python_path()), "-I", str(ROOT / "app/tools/ghunt_worker.py"),
        cwd=ROOT, env=environment, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, limit=8 * 1024 * 1024)

    async def discard_errors():
        while await process.stderr.read(8192):
            pass  # Native diagnostics may contain tokens; only enum statuses leave the child.

    errors = asyncio.create_task(discard_errors())
    try:
        job = {"query": query, "services": services, "credentials": str(credentials_path()),
               "timeout": settings.ghunt_request_timeout, "max_events": settings.ghunt_max_events}
        process.stdin.write((json.dumps(job) + "\n").encode())
        await process.stdin.drain()
        count, result = 0, None
        async with http_client.build_client(timeout=settings.ghunt_request_timeout, public_only=True,
                rotate_ua=False, max_retries=0, trust_env=False) as client:
            while line := await process.stdout.readline():
                message = json.loads(line)
                if message.get("event") == "request":
                    count += 1
                    try:
                        if count > settings.ghunt_max_requests:
                            raise ValueError("GHunt request limit")
                        payload = await perform_request(client, message)
                    except Exception:
                        payload = {"error": "request_failed"}
                    process.stdin.write((json.dumps({"id": message["id"], **payload}) + "\n").encode())
                    await process.stdin.drain()
                elif message.get("event") == "result":
                    result = message["result"]
            code = await process.wait()
            if code or result is None:
                raise RuntimeError("GHunt worker did not complete")
            result["requests"] = count
            return result
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
        await errors
