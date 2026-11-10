"""Application entry point."""

from __future__ import annotations

import ctypes
import logging
import sys

from . import APP_NAME, __version__
from .logging_setup import setup_logging

log = logging.getLogger(__name__)


def _attach_console() -> None:
    """Give a windowed build a stdout so --selftest can print its JSON."""
    if not getattr(sys, "frozen", False) or sys.stdout is not None:
        return
    try:
        ctypes.windll.kernel32.AttachConsole(-1)
        stream = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    setup_logging()

    if "--selftest" in args:
        _attach_console()
        from .selftest import run_selftest

        return run_selftest(args)

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "DetectiveLon.Vox"
        )
    except Exception:
        pass

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("DetectiveLon")
    app.setApplicationVersion(__version__)

    from .theme import apply_theme, app_icon

    apply_theme(app)
    app.setWindowIcon(app_icon())

    from .ui import MainWindow

    window = MainWindow()
    window.show()
    code = app.exec()
    log.info("%s %s exited with %d", APP_NAME, __version__, code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
