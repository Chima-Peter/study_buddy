from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.correlation import CORRELATION_HEADER, correlation_id_scope


class CorrelationIdMiddleware:
    """Pure ASGI middleware so contextvars reach the endpoint and spawn_task."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        with correlation_id_scope() as cid:
            scope.setdefault("state", {})
            scope["state"]["correlation_id"] = cid

            async def send_with_header(message: Message) -> None:
                if message["type"] == "http.response.start":
                    headers = MutableHeaders(scope=message)
                    headers[CORRELATION_HEADER] = cid
                await send(message)

            await self.app(scope, receive, send_with_header)
