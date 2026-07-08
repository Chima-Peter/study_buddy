import logging
from collections.abc import Iterator


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def init_logging(log_level: str) -> Iterator[logging.Logger]:
    """Configure application logging and yield the root app logger."""
    configure_logging(log_level)
    logger = logging.getLogger("app")
    try:
        yield logger
    finally:
        logging.shutdown()


def get_named_logger(name: str, app_logger: logging.Logger) -> logging.Logger:
    """Return a module logger after the logging resource has been initialized."""
    _ = app_logger
    return logging.getLogger(name)
