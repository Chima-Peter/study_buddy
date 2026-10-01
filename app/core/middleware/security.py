from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Strict CSP for API responses.
_API_CSP = "default-src 'self'"

# Swagger UI / ReDoc load assets from jsdelivr and FastAPI CDN.
_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' https://fastapi.tiangolo.com data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "worker-src 'self' blob:"
)

_DOCS_PATHS = {
    "/api/docs",
    "/api/redoc",
    "/openapi.json",
    "/api/openapi.json",
}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class SecurityHeadersMiddleware:
    """Pure ASGI middleware — BaseHTTPMiddleware breaks exception propagation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        csp = _DOCS_CSP if path in _DOCS_PATHS else _API_CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for header, value in SECURITY_HEADERS.items():
                    headers.setdefault(header, value)
                headers["Content-Security-Policy"] = csp
            await send(message)

        await self.app(scope, receive, send_with_headers)
