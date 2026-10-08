"""Validate DNS and connect to that IP; retain the original HTTP Host/TLS name."""

import asyncio
import ipaddress
import socket

import httpcore
import httpx


class UnsafePublicURL(httpx.TransportError):
    pass


def public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class PublicNetworkBackend:
    def __init__(self, backend):
        self.backend = backend

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if port not in {80, 443}:
            raise UnsafePublicURL("Only public HTTP(S) ports are allowed")
        try:
            async with asyncio.timeout(timeout):
                addresses = await asyncio.get_running_loop().getaddrinfo(
                    host, port, type=socket.SOCK_STREAM,
                )
                ips = list(dict.fromkeys(info[4][0] for info in addresses))
                if not ips or not all(public_address(ip) for ip in ips):
                    raise UnsafePublicURL("Destination resolves to a non-public address")
                last_error = None
                for ip in ips:
                    try:
                        return await self.backend.connect_tcp(
                            ip, port, timeout=timeout, local_address=local_address,
                            socket_options=socket_options,
                        )
                    except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                        last_error = exc
                raise last_error
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout("Public connection timed out") from exc
        except OSError as exc:
            raise httpcore.ConnectError("Public DNS lookup failed") from exc

    async def connect_unix_socket(self, *args, **kwargs):
        raise UnsafePublicURL("Unix sockets are not public destinations")

    async def sleep(self, seconds):
        await self.backend.sleep(seconds)
