import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.authentication.router import router as auth_router
from app.config import Settings
from app.container import Container
from app.logging_config import configure_logging
from app.middleware import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    await app.container.init_resources()
    try:
        yield
    finally:
        await app.container.shutdown_resources()


def create_app() -> FastAPI:
    container = Container()
    container.wire(packages=["app"])
    settings: Settings = container.settings()

    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan
    )
    app.container = container

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
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    api_router.include_router(auth_router)
    app.include_router(api_router)

    logger.info("%s started", settings.app_name)
    return app


app = create_app()
