from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)

        path = request.url.path
        csp = _DOCS_CSP if path in _DOCS_PATHS else _API_CSP
        response.headers["Content-Security-Policy"] = csp
        return response
