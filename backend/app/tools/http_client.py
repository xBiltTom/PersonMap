"""
Shared resilient HTTP layer for all OSINT tools.

Adapts battle-tested resilience patterns used by mature OSINT scanners
(Sherlock, Maigret, WhatsMyName-based tools) instead of reinventing them:
- Rotating User-Agent pool per attempt (avoids single-fingerprint bans).
- Small randomized jitter before every attempt (avoids perfectly-timed
  robotic request patterns that WAFs detect easily).
- Exponential backoff with retries on transient errors (timeouts, connection
  resets, 429/5xx) instead of failing a whole tool on one flaky response.
- Dos puertas de concurrencia con propósitos distintos: una **por host**, que
  es la cortesía real con cada sitio, y una **global**, que es el guardarraíl
  de recursos del proceso. Antes solo existía la global, lo que trataba igual
  500 peticiones a 500 hosts que 500 al mismo host y obligaba a mantenerla
  artificialmente baja.

Usage: every OSINT tool should build its client with `build_client(...)`
instead of `httpx.AsyncClient(...)`. All resilience (retry, backoff, jitter,
UA rotation, concurrency gating) is then applied transparently at the
transport level -- individual `client.get(...)` / `client.post(...)` call
sites do not need to change at all. The optional `get()`/`post()` helpers
below are a thin convenience layer for tools that prefer an
`Optional[httpx.Response]` (None on total failure) contract instead of a
raised exception.
"""

import asyncio
import random
from typing import Any, Optional

import httpx

from app.core.config import settings

# A small pool of realistic, currently-common User-Agents across browsers/OS.
# Rotating these (instead of one hardcoded string reused by every request)
# is the same technique used by Maigret/Naminter to reduce fingerprinting.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
]

# Status codes worth retrying (rate limiting / transient upstream issues).
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_global_semaphore: Optional[asyncio.Semaphore] = None
_host_semaphores: "dict[str, asyncio.Semaphore]" = {}


def _get_global_semaphore() -> asyncio.Semaphore:
    """Lazily creates the process-wide outbound concurrency gate."""
    global _global_semaphore
    if _global_semaphore is None:
        _global_semaphore = asyncio.Semaphore(settings.http_max_concurrency)
    return _global_semaphore


def _get_host_semaphore(host: str) -> asyncio.Semaphore:
    """
    Puerta de concurrencia **por host**, que es donde vive la cortesía real.

    El diseño anterior solo tenía el tope global, y eso confundía dos cosas
    distintas: 500 peticiones a 500 hosts distintos no molestan a nadie, pero
    500 al mismo host sí. Al separar los dos límites, el global puede subir
    (es un guardarraíl de recursos del proceso) sin volvernos descorteses, y
    un sitio concreto nunca recibe más de `http_max_per_host` a la vez por
    muchas herramientas que lo consulten en paralelo.

    Los semáforos se cachean por host durante la vida del proceso: son objetos
    diminutos y el conjunto de hosts está acotado por los catálogos.
    """
    sem = _host_semaphores.get(host)
    if sem is None:
        sem = asyncio.Semaphore(max(1, settings.http_max_per_host))
        _host_semaphores[host] = sem
    return sem


def reset_concurrency_gates() -> None:
    """Descarta los semáforos cacheados. Solo para los tests."""
    global _global_semaphore
    _global_semaphore = None
    _host_semaphores.clear()


def random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def build_headers(extra: Optional[dict] = None) -> dict:
    """Builds a realistic header set with a rotating User-Agent."""
    headers = {
        "User-Agent": random_user_agent(),
        "Accept": "*/*",
        "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if extra:
        headers.update(extra)
    return headers


class ResilientTransport(httpx.AsyncHTTPTransport):
    """
    Drop-in httpx transport that adds, transparently to every request made
    through it:
      1. A rotating User-Agent per attempt.
      2. Small randomized jitter before dispatching.
      3. Exponential backoff retries on timeouts/connection errors and on
         retryable HTTP status codes (429/5xx).
      4. A shared global semaphore so the whole process never exceeds
         `settings.http_max_concurrency` concurrent outbound requests,
         regardless of how many tools/rounds are running in parallel.
    """

    def __init__(
        self,
        *,
        max_retries: int = 2,
        base_delay: float = 0.35,
        jitter: float = 0.20,
        rotate_ua: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.jitter = jitter
        self.rotate_ua = rotate_ua

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        sem = _get_global_semaphore()
        host_sem = _get_host_semaphore(request.url.host or "")
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            if self.rotate_ua:
                request.headers["User-Agent"] = random_user_agent()

            await asyncio.sleep(random.uniform(0, self.jitter))
            try:
                # El global se toma primero y el de host después, siempre en el
                # mismo orden: invertirlo en algún camino abriría un interbloqueo
                # entre dos peticiones al mismo host.
                async with sem, host_sem:
                    response = await super().handle_async_request(request)
                if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                    await response.aclose()
                    await asyncio.sleep(self.base_delay * (2 ** attempt) + random.uniform(0, self.jitter))
                    continue
                return response
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.ReadError,
                httpx.RemoteProtocolError,
            ) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(self.base_delay * (2 ** attempt) + random.uniform(0, self.jitter))
                    continue
                raise

        if last_exc:
            raise last_exc
        raise httpx.TransportError("Max retries exceeded")


def build_client(
    *,
    timeout: float = 10.0,
    follow_redirects: bool = True,
    verify: bool = True,
    headers: Optional[dict] = None,
    max_retries: int = 2,
    rotate_ua: bool = True,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """
    Factory that every OSINT tool should use instead of `httpx.AsyncClient(...)`
    directly. Returns a client wired to `ResilientTransport`, so every request
    made through it automatically gets jittered retries with exponential
    backoff and a shared global concurrency gate.

    Set `rotate_ua=False` for APIs that require a stable, descriptive User-Agent
    identifying this application (e.g. Wikipedia/MediaWiki and OpenAlex both
    explicitly ask for this as part of their public API etiquette/"polite pool"
    policies) -- impersonating a rotating browser UA against those APIs would
    be counterproductive, not stealthier.

    `verify` defaults to True. It used to default to False, which silently
    disabled TLS certificate verification for every tool in the registry --
    an indefensible default in a platform whose subject matter is information
    security, and one that exposed every request to trivial interception.
    A tool that genuinely needs to reach a host with a broken chain must opt
    out explicitly at its own call site and document why.
    """
    transport = ResilientTransport(verify=verify, max_retries=max_retries, rotate_ua=rotate_ua)
    merged_headers = build_headers(headers)
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=follow_redirects,
        headers=merged_headers,
        **kwargs,
    )


async def get(client: httpx.AsyncClient, url: str, **kwargs: Any) -> Optional[httpx.Response]:
    """Convenience GET returning None (instead of raising) on total failure."""
    try:
        return await client.get(url, **kwargs)
    except Exception:
        return None


async def post(client: httpx.AsyncClient, url: str, **kwargs: Any) -> Optional[httpx.Response]:
    """Convenience POST returning None (instead of raising) on total failure."""
    try:
        return await client.post(url, **kwargs)
    except Exception:
        return None
