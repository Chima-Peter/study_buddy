import logging
import sys
from collections.abc import Iterator

from app.core.correlation import get_correlation_id

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

_RESET = "\033[0m"
_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[32m",  # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[35m",  # magenta
}


class CorrelationIdFilter(logging.Filter):
    """Inject the current correlation id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class ColorLevelFormatter(logging.Formatter):
    """Color only the level name when writing to a TTY."""

    def __init__(self, *args, use_color: bool = True, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        original = record.levelname
        padded = f"{original:<8}"
        if self.use_color:
            color = _LEVEL_COLORS.get(record.levelno)
            record.levelname = f"{color}{padded}{_RESET}" if color else padded
        else:
            record.levelname = padded
        try:
            return super().format(record)
        finally:
            record.levelname = original


def init_logging(log_level: str) -> Iterator[logging.Logger]:
    """Configure application logging and yield the app logger."""
    level = getattr(logging, log_level.upper(), None)
    if not isinstance(level, int):
        level = logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(
        ColorLevelFormatter(
            fmt=(
                "%(asctime)s | %(levelname)s | %(name)s | "
                "%(correlation_id)s | %(message)s"
            ),
            datefmt="%Y-%m-%d %H:%M:%S",
            use_color=sys.stderr.isatty(),
        )
    )
    handler.addFilter(CorrelationIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)

    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logger = logging.getLogger("app")
    logger.setLevel(level)
    try:
        yield logger
    finally:
        logging.shutdown()
