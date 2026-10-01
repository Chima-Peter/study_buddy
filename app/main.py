import asyncio

import sentry_sdk
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from app.authentication.router import authentication_router
from app.config import Settings
from app.container import Container
from app.core.correlation import CORRELATION_HEADER
from app.core.middleware import CorrelationIdMiddleware, SecurityHeadersMiddleware
from app.core.response import (
    ApiResponse,
    BasicResponse,
    basic_response_from_http_exception,
)
from app.system.router import system_router


def _init_sentry(settings: Settings) -> None:
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn or ".........." in dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.environment,
        data_collection={
            "user_info": True,
            "gen_ai": {"inputs": True, "outputs": True},
            "graphql": {"document": False, "variables": False},
            "database_query_data": True,
            "queues": True,
            "stack_frame_variables": False,
            "http_bodies": ["incoming_request", "outgoing_request"],
            "cookies": {
                "mode": "denylist",
                "terms": ["forwarded", "-ip", "remote-", "via", "-user"],
            },
            "http_headers": {
                "request": {
                    "mode": "denylist",
                    "terms": ["forwarded", "-ip", "remote-", "via", "-user"],
                },
            },
            "url_query_params": {
                "mode": "denylist",
                "terms": ["forwarded", "-ip", "remote-", "via", "-user"],
            },
        },
        traces_sample_rate=0.1,
        shutdown_timeout=10,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await app.container.init_resources()
    await asyncio.to_thread(app.container.embedding_manager().ensure_loaded)
    try:
        yield
    finally:
        await app.container.shutdown_resources()
        sentry_sdk.flush(timeout=10)


def create_app() -> FastAPI:
    container = Container()
    container.wire(packages=["app"])
    settings: Settings = container.settings()

    _init_sentry(settings)

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.container = container

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        _request: Request, exc: HTTPException
    ) -> BasicResponse:
        if exc.status_code >= 500:
            sentry_sdk.capture_exception(exc)
        return basic_response_from_http_exception(exc)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        _request: Request, exc: Exception
    ) -> BasicResponse:
        sentry_sdk.capture_exception(exc)
        return BasicResponse(
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-New-Token", CORRELATION_HEADER],
    )

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    api_router = APIRouter(prefix="/api")

    @api_router.get(
        "/health",
        response_model=ApiResponse,
        summary="Health check",
        tags=["health"],
    )
    async def health() -> BasicResponse:
        return BasicResponse(data={"status": "ok"})

    api_router.include_router(authentication_router)
    api_router.include_router(system_router)
    app.include_router(api_router)

    return app


app = create_app()
