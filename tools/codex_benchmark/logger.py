"""Logging helpers for the Codex benchmark."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import LoggingConfig


def setup_logging(config: LoggingConfig, logs_dir: str) -> logging.Logger:
    Path(logs_dir).mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("codex_benchmark")
    logger.setLevel(getattr(logging, config.level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        Path(logs_dir) / config.file_name,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if config.console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
