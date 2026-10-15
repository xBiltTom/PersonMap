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
        if response.get("target_response"):
            target = response["target_response"]
            self.observed[target["request_url"]] = target
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


def install_transport(bridge, gateways=None):
    import maigret.checking as checking
    import maigret.activation as activation
    import requests
    import aiohttp_socks

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
            self.proxy = kwargs.get("proxy") or getattr(self.connector, "proxy", None)

        def gateway(self):
            for kind in ("tor", "i2p"):
                configured = (gateways or {}).get(kind)
                if configured and self.proxy == configured:
                    return kind
            return "proxy" if self.proxy else None

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
            if self.gateway():
                kwargs["gateway"] = self.gateway()
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
            if self.gateway():
                kwargs["gateway"] = self.gateway()
            response = await bridge.dispatch(method, url, **kwargs)
            return CurlResponse(response.payload)

    class Connector:
        # Networking is owned by the parent. Do not start an unused c-ares
        # resolver/thread in the isolated search loop.
        def __init__(self, **kwargs):
            self.proxy = kwargs.get("proxy")

        async def close(self):
            pass

    checking.ClientSession = activation.ClientSession = Session
    checking.CurlCffiAsyncSession = CurlSession
    checking.TCPConnector = Connector
    # Gateways remain in the parent, never sockets owned by the child.
    checking.ProxyConnector = type("ProxyConnector", (Connector,), {
        "from_url": classmethod(lambda cls, url, **kwargs: cls(proxy=url))})
    aiohttp_socks.ProxyConnector = checking.ProxyConnector

    class DomainChecker:
        def __init__(self, **kwargs):
            self.url = None

        def prepare(self, url, **kwargs):
            self.url = url

        async def check(self):
            try:
                response = await bridge.dispatch("DNS", self.url)
                return (await response.read()).decode(), response.status, None
            except Exception:
                from maigret.errors import CheckError
                return None, 0, CheckError("DNS resolve error")

        async def close(self):
            pass

    checking.AiodnsDomainResolver = DomainChecker


def serialize(result, bridge):
    status = result.get("status")
    url = result.get("url_probe") or result.get("url_user", "")
    response = bridge.observed.get(url)
    return {
        "site": result["site"].name,
        "status": status.status.value if status else "Unknown",
        "error": status.error.type if status and status.error else None,
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
    install_transport(bridge, {kind: job.get(kind + "_proxy") for kind in ("tor", "i2p")})
    logger = logging.getLogger("maigret.worker")
    logger.setLevel(logging.ERROR)
    import maigret.checking as checking
    native_executor = checking.AsyncioQueueGeneratorExecutor
    class BudgetedExecutor(native_executor):
        def __init__(self, *args, **kwargs):
            # Per-request deadlines remain native. Shared-budget queueing and
            # serial enrichment need headroom at the whole-check deadline.
            kwargs["timeout"] = kwargs.get("timeout", job["timeout"]) + job.get("queue_grace", 0)
            super().__init__(*args, **kwargs)
    checking.AsyncioQueueGeneratorExecutor = BudgetedExecutor
    import hashlib
    from pathlib import Path
    if hashlib.sha256(Path(job["database"]).read_bytes()).hexdigest() != job["database_sha256"]:
        raise ValueError("Catalogue changed while starting the worker")
    db = MaigretDatabase().load_from_path(job["database"])
    if job.get("operation") == "report":
        from app.tools.maigret_reports import render_native_report
        bridge.emit({"event": "result", "result": render_native_report(job, db)})
        return
    if job.get("operation") == "extract":
        from socid_extractor import parse, extract, mutate_url
        from maigret.utils import extract_usernames
        from app.tools.maigret_ids import identifier_values, identifiers_from_url
        for url in job.get("urls", []):
            data, ids, links = {}, identifiers_from_url(url), []
            error = None
            try:
                if not job.get("parse", True):
                    bridge.emit({"event": "result", "result": {"url_user": url, "ids_data": {},
                        "ids_usernames": {item["value"]: item["id_type"] for item in ids}, "ids_links": [],
                        "identifiers": ids,
                        "response": None, "error": None}})
                    continue
                requests = [(url, {})]
                if job.get("enrich"):
                    requests.extend(list(mutate_url(url))[:3])
                for source, headers in requests:
                    page, _ = parse(source, cookies_str="", headers=headers, timeout=job["timeout"])
                    info = extract(page) or {}
                    data.update(info)
                    ids.extend(identifier_values([{"value": value, "id_type": key} for key, value in info.items()
                                                  if isinstance(value, (str, int)) and not isinstance(value, bool)]))
                    ids.extend(identifier_values({value: "username" for value in extract_usernames(info, logger)}))
                    raw_links = info.get("links", [])
                    if isinstance(raw_links, str):
                        import ast
                        try:
                            raw_links = ast.literal_eval(raw_links)
                        except (ValueError, SyntaxError):
                            raw_links = [raw_links]
                    if isinstance(raw_links, list):
                        links.extend(value for value in raw_links if isinstance(value, str))
                    for key in ("website", "blog", "url"):
                        if isinstance(info.get(key), str):
                            links.append(info[key])
            except Exception as exc:
                error = type(exc).__name__
            for link in links:
                ids.extend(identifiers_from_url(link))
            bridge.emit({"event": "result", "result": {"url_user": url, "ids_data": data,
                         "ids_usernames": {item["value"]: item["id_type"] for item in ids},
                         "identifiers": identifier_values(ids),
                         "ids_links": list(dict.fromkeys(links)), "response": bridge.observed.get(url), "error": error}})
        return
    if job.get("operation") == "permute":
        from maigret.permutator import Permute
        candidates = Permute({part: "username" for part in job["parts"]}).gather()
        bridge.emit({"event": "result", "result": {"usernames": list(candidates)[:job["limit"]]}})
        return
    sites = {name: copy.deepcopy(db.sites_dict[name]) for name in job["sites"]}
    for name, site in sites.items():
        if name == "Disqus":
            # Correct the public URL while retaining the native API probe.
            site.url = "https://disqus.com/by/{username}/"
        if name == "Telegram":
            site.check_type = "status_code"
            site.absence_strs = site.presense_strs = []
    if job.get("operation") == "self_check":
        from maigret.checking import self_check
        checked = await self_check(db, sites, logger, silent=True, max_connections=job["concurrency"],
                                  auto_disable=False, no_progressbar=True, proxy=job.get("proxy"),
                                  tor_proxy=job.get("tor_proxy"), i2p_proxy=job.get("i2p_proxy"),
                                  cloudflare_bypass=job.get("cloudflare_bypass"))
        # The catalogue file is never saved or automatically disabled here.
        for result in checked["results"]:
            for key in ("issues", "recommendations"):
                values = []
                for value in result.get(key, []):
                    text = str(value)
                    for secret in (job.get("proxy"), job.get("tor_proxy"), job.get("i2p_proxy"), job.get("cookies")):
                        if secret:
                            text = text.replace(secret, "[configured value]")
                    values.append(text)
                result[key] = values
        bridge.emit({"event": "result", "result": checked})
        return
    notifier = Mock()
    completed = set()
    def update(status, *args):
        completed.add(status.site_name)
        bridge.emit({"event": "progress", "checked": len(completed), "total": len(sites)})
    notifier.update = update
    options = dict(logger=logger, timeout=job["timeout"], no_progressbar=True,
                   retries=job.get("retries", 1), max_connections=job["concurrency"], query_notify=notifier,
                   is_parsing_enabled=job.get("parse", True), is_enrich_enabled=job["enrich"],
                   keywords=job.get("keywords"), id_type=job.get("id_type", "username"),
                   cookies=job.get("cookies"), proxy=job.get("proxy"),
                   tor_proxy=job.get("tor_proxy"), i2p_proxy=job.get("i2p_proxy"),
                   check_domains=job.get("check_domains", False), cloudflare_bypass=job.get("cloudflare_bypass"))
    solver_sites = {name: site for name, site in sites.items() if job.get("cloudflare_bypass")
                    and set(site.protection).intersection(job["cloudflare_bypass"]["trigger_protection"])}
    solver_options = {**options, "timeout": job.get("solver_timeout", 65),
                      "max_connections": min(job["concurrency"], job.get("solver_concurrency", 4))}
    regular_sites = {name: site for name, site in sites.items() if name not in solver_sites}
    batches = []
    if regular_sites:
        batches.append(search(job["username"], regular_sites, **options))
    if solver_sites:
        batches.append(search(job["username"], solver_sites, **solver_options))
    results = {}
    for batch in await asyncio.gather(*batches):
        results.update(batch)
    semaphore = asyncio.Semaphore(job["concurrency"])
    async def finish(name, result):
        wire = serialize(result, bridge)
        if result.get("status") and result["status"].status == MaigretCheckStatus.CLAIMED:
            from app.tools.maigret_ids import identifiers_from_url, identifier_values
            ids = dict(wire["ids_usernames"])
            identifiers = identifier_values(ids)
            identifiers.extend(identifier_values([{"value": value, "id_type": key}
                               for key, value in wire["ids_data"].items() if isinstance(value, (str, int)) and not isinstance(value, bool)]))
            for link in wire["ids_links"]:
                for item in identifiers_from_url(link):
                    ids[item["value"]] = item["id_type"]
                    identifiers.append(item)
            wire["ids_usernames"] = ids
            wire["identifiers"] = identifier_values(identifiers)
        control_user = job["controls"].get(name)
        if result.get("status") and result["status"].status == MaigretCheckStatus.CLAIMED and control_user:
            async with semaphore:
                control_options = {**(solver_options if name in solver_sites else options), "is_parsing_enabled": False,
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
        bridge.emit({"event": "failure", "error": type(exc).__name__})
        raise
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
