"""Where Vox keeps its files, in development and inside a frozen build."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def _base(env: str, fallback: Path) -> Path:
    value = os.environ.get(env)
    return Path(value) if value else fallback


def app_data_dir() -> Path:
    """Writable per-user data: settings and voice profiles."""
    return _base("APPDATA", Path.home() / "AppData" / "Roaming") / APP_NAME


def local_data_dir() -> Path:
    """Per-machine data that can be recreated: logs."""
    return _base("LOCALAPPDATA", Path.home() / "AppData" / "Local") / APP_NAME


def install_dir() -> Path:
    """Folder holding the executable, or the repository root in development."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """Folder holding bundled read-only data (models, assets)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def models_dir() -> Path:
    return bundle_dir() / "models"


def assets_dir() -> Path:
    return bundle_dir() / "assets"


def profiles_dir() -> Path:
    return app_data_dir() / "profiles"


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def logs_dir() -> Path:
    return local_data_dir() / "logs"


def ensure_dirs() -> None:
    for folder in (app_data_dir(), profiles_dir(), logs_dir()):
        folder.mkdir(parents=True, exist_ok=True)
