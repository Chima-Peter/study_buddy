import uvicorn

from app.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        ws_ping_interval=20,
        ws_ping_timeout=20,
        ws_max_size=65536,
    )


if __name__ == "__main__":
    main()
