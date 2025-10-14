"""Logging configuration built around structlog JSON logging."""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Iterable

import structlog

_LOGGING_INITIALISED = False


def _default_log_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "logs"


def configure_logging(verbose: bool = False) -> structlog.BoundLogger:
    """Configure structlog + stdlib handlers and return application logger."""

    global _LOGGING_INITIALISED
    log_dir = _default_log_dir()
    error_log = log_dir / "error.log"
    crawler_log = log_dir / "crawler.log"
    sources_dir = log_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    error_log.touch(exist_ok=True)
    crawler_log.touch(exist_ok=True)

    if not _LOGGING_INITIALISED:
        level = "DEBUG" if verbose else "INFO"
        # Configure stdlib logging (console + files)
        logging.config.dictConfig(
            {
                "version": 1,
                "disable_existing_loggers": False,
                "formatters": {
                    # Keep a simple JSON formatter for all handlers
                    "plain": {
                        "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                        "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
                    }
                },
                "handlers": {
                    "console": {
                        "class": "logging.StreamHandler",
                        "level": level,
                        "formatter": "plain",
                    },
                    "crawler_file": {
                        "class": "logging.FileHandler",
                        "level": "INFO",
                        "filename": str(crawler_log),
                        "formatter": "plain",
                    },
                    "error_file": {
                        "class": "logging.FileHandler",
                        "level": "ERROR",
                        "filename": str(error_log),
                        "formatter": "plain",
                    },
                },
                "loggers": {
                    # Core app logger (global messages)
                    "intelli_crawler": {
                        "handlers": ["console", "crawler_file", "error_file"],
                        "level": level,
                        "propagate": False,
                    },
                },
            }
        )

        # Configure structlog to forward events to stdlib logging
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.stdlib.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                # Wrap for stdlib formatter; keep JSON formatting at handler level
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        _LOGGING_INITIALISED = True
    return structlog.get_logger("intelli_crawler")


def source_logger(source_name: str, verbose: bool = False) -> structlog.BoundLogger:
    """Return a logger bound to a specific source and ensure file handler exists."""

    logger = configure_logging(verbose)
    source_log_path = _default_log_dir() / "sources" / f"{source_name}.log"
    source_log_path.parent.mkdir(parents=True, exist_ok=True)

    logger_name = f"intelli_crawler.source.{source_name}"
    py_logger = logging.getLogger(logger_name)
    if not any(
        isinstance(handler, logging.FileHandler) and handler.baseFilename == str(source_log_path)
        for handler in py_logger.handlers
    ):
        file_handler = logging.FileHandler(source_log_path, encoding="utf-8")
        # Reuse the same JSON formatter as global logger
        global_logger = logging.getLogger("intelli_crawler")
        if global_logger.handlers:
            file_handler.setFormatter(global_logger.handlers[0].formatter)
        file_handler.setLevel(logging.INFO)
        py_logger.addHandler(file_handler)

    return structlog.get_logger(logger_name).bind(source=source_name)


def tail_log(path: Path, line_count: int = 100) -> list[str]:
    """Return the last N lines from a log file."""

    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="ignore") as stream:
        lines = stream.readlines()
    return lines[-line_count:]


def available_source_logs() -> Iterable[Path]:
    """Yield available source log file paths."""

    sources_dir = _default_log_dir() / "sources"
    if not sources_dir.exists():
        return []
    return sorted(p for p in sources_dir.glob("*.log"))


__all__ = ["configure_logging", "source_logger", "tail_log", "available_source_logs"]
