from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.authentication.router import router as auth_router
from app.config import Settings
from app.container import Container
from app.core.response import BasicResponse, basic_response_from_http_exception
from app.core.middleware import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    await app.container.init_resources()
    settings: Settings = app.container.settings()
    logger = app.container.logging()
    logger.info("%s started", settings.app_name)
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
        lifespan=lifespan
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

    @api_router.get("/health")
    async def health() -> BasicResponse:
        return BasicResponse(data={"status": "ok"})

    api_router.include_router(auth_router)
    app.include_router(api_router)

    return app


app = create_app()
