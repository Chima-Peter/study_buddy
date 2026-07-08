import logging
from collections.abc import Iterator


def init_logging(log_level: str) -> Iterator[logging.Logger]:
    """Configure application logging and yield the app logger."""
    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    logger = logging.getLogger("app")
    try:
        yield logger
    finally:
        logging.shutdown()
