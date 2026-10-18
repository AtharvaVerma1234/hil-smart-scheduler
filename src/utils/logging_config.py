"""Application-wide structured logging configuration."""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_log_file_path() -> Path:
    """Return the absolute active log file path."""
    log_dir = Path(os.environ.get("HIL_LOG_DIR", PROJECT_ROOT / "logs"))
    return log_dir / "hil-smart-scheduler.log"


def configure_logging() -> None:
    """Configure console and rotating file logs once per Python process.

    The log format includes source location and process context. Application
    code must not log API keys, complete chat prompts, or raw environment
    contents.
    """
    root_logger = logging.getLogger()
    log_file_path = get_log_file_path().resolve()
    if any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename).resolve() == log_file_path
        for handler in root_logger.handlers
    ):
        return

    log_level_name = os.environ.get("HIL_LOG_LEVEL", "INFO").strip().upper()
    log_level = getattr(logging, log_level_name, None)
    if not isinstance(log_level, int):
        raise ValueError(
            f"Invalid HIL_LOG_LEVEL {log_level_name!r}; use DEBUG, INFO, WARNING, ERROR, or CRITICAL."
        )

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s.%(msecs)03d %(levelname)s "
            "[%(process)d:%(threadName)s] %(name)s:%(lineno)d - %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root_logger.setLevel(log_level)
    if not getattr(root_logger, "_hil_logging_configured", False):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        root_logger._hil_logging_configured = True  # type: ignore[attr-defined]
    try:
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
    except OSError:
        root_logger.exception(
            "File logging could not be initialized: path=%s; continuing with console logs.",
            log_file_path,
        )
        return
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    root_logger.info(
        "Application logging initialized: level=%s file=%s rotation=%s bytes x %s backups",
        log_level_name,
        file_handler.baseFilename,
        file_handler.maxBytes,
        file_handler.backupCount,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a module logger after ensuring the application handlers exist."""
    configure_logging()
    return logging.getLogger(name)
