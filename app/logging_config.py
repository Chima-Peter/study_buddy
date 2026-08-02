import logging
from collections.abc import Iterator

# Third-party loggers that drown out app signal at INFO.
_QUIET_LOGGERS = (
    "elastic_transport",
    "elasticsearch",
    "httpx",
    "httpcore",
    "huggingface_hub",
    "sentence_transformers",
    "transformers",
    "google_genai",
    "google_genai.models",
    "urllib3",
    "aio_pika",
    "aiormq",
)


def init_logging(log_level: str) -> Iterator[logging.Logger]:
    """Configure application logging and yield the app logger."""
    level = log_level.upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logger = logging.getLogger("app")
    try:
        yield logger
    finally:
        logging.shutdown()
