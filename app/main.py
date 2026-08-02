from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.authentication.router import authentication_router
from app.config import Settings
from app.container import Container
from app.core.middleware import SecurityHeadersMiddleware
from app.core.response import (
    ApiResponse,
    BasicResponse,
    basic_response_from_http_exception,
)
from app.system.router import system_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await app.container.init_resources()
    app.container.embedding_manager()
    try:
        yield
    finally:
        await app.container.shutdown_resources()


def create_app() -> FastAPI:
    container = Container()
    container.wire(packages=["app"])
    settings: Settings = container.settings()

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
        return basic_response_from_http_exception(exc)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
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
