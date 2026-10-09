"""Bearer gate for the local MCP bridge; does not expose the key in responses."""
import secrets
from starlette.responses import JSONResponse
from app.core.config import settings


class MCPTokenGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope.get("path") != "/mcp":
            return await JSONResponse({"detail": "Not found"}, status_code=404)(scope, receive, send)
        if not settings.mcp_enabled:
            return await JSONResponse({"detail": "MCP deshabilitado"}, status_code=404)(scope, receive, send)
        key = settings.mcp_api_key.get_secret_value() if settings.mcp_api_key else ""
        if not key:
            return await JSONResponse({"detail": "Configura MCP_API_KEY para habilitar el puente MCP"}, status_code=503)(scope, receive, send)
        headers = dict(scope["headers"])
        value = headers.get(b"authorization", b"").decode("latin-1")
        scheme, _, token = value.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(token.encode(), key.encode()):
            return await JSONResponse({"detail": "Token MCP inválido"}, status_code=401,
                                      headers={"WWW-Authenticate": "Bearer"})(scope, receive, send)
        return await self.app(scope, receive, send)
