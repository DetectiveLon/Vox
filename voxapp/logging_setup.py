"""File logging that survives a frozen, windowed build with no console."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from .paths import logs_dir


def setup_logging(level: int = logging.INFO) -> None:
    logs_dir().mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    if root.handlers:
        return

    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir() / "vox.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        root.addHandler(console)

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        root.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = hook
