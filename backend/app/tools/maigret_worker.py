"""Private JSONL worker for the complete Maigret library.

Only networking is adapted. Site checks, activations, engine inheritance,
extraction, mutations and retries execute upstream code. Every HTTP request,
including activations, is delegated to the API's shared transport. The library
module overrides are confined to this child process.
"""
import asyncio
import base64
import copy
import json
import logging
import sys
import threading
from http.cookies import Morsel


class Bridge:
    def __init__(self, reader, output):
        self.reader, self.output = reader, output
        self.pending, self.observed = {}, {}
        self.sequence = 0
        self.loop = asyncio.get_running_loop()
        self.output_lock = threading.Lock()

    def emit(self, message):
        with self.output_lock:
            self.output.write(json.dumps(message, ensure_ascii=True, default=str) + "\n")
            self.output.flush()

    async def dispatch(self, method, url, **kwargs):
        future = asyncio.run_coroutine_threadsafe(self.request(method, url, **kwargs), self.loop)
        return await asyncio.wrap_future(future)

    async def receive(self):
        while line := await self.reader.readline():
            message = json.loads(line)
            future = self.pending.get(message.get("id"))
            if future is not None and not future.done():
                future.set_result(message)
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConnectionError("Parent transport closed"))

    async def request(self, method, url, **kwargs):
        self.sequence += 1
        key = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        self.emit({"event": "request", "id": key, "method": method.upper(), "url": str(url), **kwargs})
        try:
            response = await future
        finally:
            self.pending.pop(key, None)
        if response.get("error"):
            raise ConnectionError(response["error"])
        self.observed[str(url)] = response
        return Response(response)


class Response:
    def __init__(self, payload):
        from requests.structures import CaseInsensitiveDict
        self.payload = payload
        self.status = self.status_code = payload["status"]
        self.headers = CaseInsensitiveDict(payload.get("headers", {}))
        self.url = payload["url"]
        self.charset = self.encoding = payload.get("encoding") or "utf-8"
        self.cookies = {}
        for name, value in payload.get("cookies", {}).items():
            morsel = Morsel()
            morsel.set(name, value, value)
            self.cookies[name] = morsel
        self.content = self

    async def read(self):
        return base64.b64decode(self.payload["body"])


class AioResponse(Response):
    async def text(self):
        return (await self.read()).decode(self.encoding, errors="replace")

    async def json(self, **kwargs):
        return json.loads(await self.text())


class CurlResponse(Response):
    @property
    def text(self):
        return base64.b64decode(self.payload["body"]).decode(self.encoding, errors="replace")


def install_transport(bridge):
    import maigret.checking as checking
    import maigret.activation as activation
    import requests

    def synchronous_request(session, method, url, **kwargs):
        # socid_extractor has synchronous postprocessors (e.g. a Gravatar
        # redirect). Search runs on its own thread; the RPC loop stays free.
        allowed = {key: kwargs[key] for key in ("headers", "json", "data", "params", "allow_redirects") if key in kwargs}
        timeout = kwargs.get("timeout")
        if timeout:
            allowed["timeout"] = max(timeout) if isinstance(timeout, tuple) else timeout
        wire = asyncio.run_coroutine_threadsafe(bridge.request(method, url, **allowed), bridge.loop).result()
        response = requests.Response()
        response.status_code, response.url = wire.status, wire.url
        response.headers = requests.structures.CaseInsensitiveDict(wire.headers)
        response._content = base64.b64decode(wire.payload["body"])
        response.encoding = wire.encoding
        response.cookies = requests.cookies.cookiejar_from_dict(wire.payload.get("cookies", {}))
        return response

    requests.sessions.Session.request = synchronous_request

    class Request:
        def __init__(self, method, url, **kwargs):
            self.method, self.url, self.kwargs = method, url, kwargs

        async def __aenter__(self):
            response = await bridge.dispatch(self.method, self.url, **self.kwargs)
            return AioResponse(response.payload)

        async def __aexit__(self, *args):
            pass

    class Session:
        def __init__(self, *args, **kwargs):
            self.connector = kwargs.get("connector")
            self.cookie_jar = kwargs.get("cookie_jar")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            if self.connector is not None:
                await self.connector.close()

        def request(self, method, url, **kwargs):
            # aiohttp timeout/proxy objects never cross the JSON boundary.
            timeout = kwargs.get("timeout")
            if timeout is not None and not isinstance(timeout, (int, float)):
                kwargs["timeout"] = timeout.total
            kwargs.pop("ssl", None)  # Parent always verifies certificates.
            if self.cookie_jar:
                headers = dict(kwargs.get("headers") or {})
                cookies = self.cookie_jar.filter_cookies(str(url))
                if cookies:
                    headers["Cookie"] = cookies.output(header="", sep=";").strip()
                kwargs["headers"] = headers
            return Request(method, url, **kwargs)

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

        def head(self, url, **kwargs):
            return self.request("HEAD", url, **kwargs)

    class CurlSession(Session):
        async def request(self, method, url, **kwargs):
            kwargs["browser"] = kwargs.pop("impersonate", "chrome")
            response = await bridge.dispatch(method, url, **kwargs)
            return CurlResponse(response.payload)

    class Connector:
        # Networking is owned by the parent. Do not start an unused c-ares
        # resolver/thread in the isolated search loop.
        def __init__(self, **kwargs):
            pass

        async def close(self):
            pass

    checking.ClientSession = activation.ClientSession = Session
    checking.CurlCffiAsyncSession = CurlSession
    checking.TCPConnector = Connector


def serialize(result, bridge):
    status = result.get("status")
    url = result.get("url_probe") or result.get("url_user", "")
    response = bridge.observed.get(url)
    return {
        "site": result["site"].name,
        "status": status.status.value if status else "Unknown",
        "error": str(status.error) if status and status.error else None,
        "url_user": result.get("url_user", ""), "url_probe": url,
        "http_status": result.get("http_status"),
        "ids_data": status.ids_data or {} if status else {},
        "ids_usernames": result.get("ids_usernames", {}),
        "ids_links": result.get("ids_links", []),
        "is_similar": result.get("is_similar", False),
        "keyword_match": str(status.keyword_match_status) if status else None,
        "response": response,
    }


async def search_job(job, bridge):
    from unittest.mock import Mock
    from maigret import search
    from maigret.sites import MaigretDatabase
    from maigret.result import MaigretCheckStatus
    install_transport(bridge)
    logger = logging.getLogger("maigret.worker")
    logger.setLevel(logging.ERROR)
    db = MaigretDatabase().load_from_path(job["database"])
    sites = {name: copy.deepcopy(db.sites_dict[name]) for name in job["sites"]}
    for name, site in sites.items():
        if name == "Disqus":
            # Correct the public URL while retaining the native API probe.
            site.url = "https://disqus.com/by/{username}/"
        if name == "Telegram":
            site.check_type = "status_code"
            site.absence_strs = site.presense_strs = []
    notifier = Mock()
    completed = set()
    def update(status, *args):
        completed.add(status.site_name)
        bridge.emit({"event": "progress", "checked": len(completed), "total": len(sites)})
    notifier.update = update
    options = dict(logger=logger, timeout=job["timeout"], no_progressbar=True,
                   retries=1, max_connections=job["concurrency"], query_notify=notifier,
                   is_parsing_enabled=True, is_enrich_enabled=job["enrich"],
                   keywords=job.get("keywords"))
    results = await search(job["username"], sites, **options)
    semaphore = asyncio.Semaphore(job["concurrency"])
    async def finish(name, result):
        wire = serialize(result, bridge)
        control_user = job["controls"].get(name)
        if result.get("status") and result["status"].status == MaigretCheckStatus.CLAIMED and control_user:
            async with semaphore:
                control_options = {**options, "is_parsing_enabled": False,
                                   "is_enrich_enabled": False, "max_connections": 1, "retries": 0,
                                   "query_notify": Mock()}
                controlled = await search(control_user, {name: copy.deepcopy(sites[name])}, **control_options)
                wire["control"] = serialize(controlled[name], bridge)
                wire["control"]["username"] = control_user
        bridge.emit({"event": "result", "result": wire})
    await asyncio.gather(*(finish(name, result) for name, result in results.items()))


async def main():
    output = sys.stdout
    sys.stdout = sys.stderr  # Upstream's terminal output cannot corrupt JSONL.
    reader = asyncio.StreamReader(limit=16 * 1024 * 1024)
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)
    job = json.loads(await reader.readline())
    bridge = Bridge(reader, output)
    receiver = asyncio.create_task(bridge.receive())
    try:
        await asyncio.to_thread(asyncio.run, search_job(job, bridge))
        bridge.emit({"event": "done"})
    except Exception as exc:
        bridge.emit({"event": "failure", "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
