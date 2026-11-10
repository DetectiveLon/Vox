"""Small JSON settings file, written atomically so a crash cannot corrupt it."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .paths import settings_path

log = logging.getLogger(__name__)

VALID_MODES = ("cpu", "gpu")
VALID_CHUNKS = (40, 80)


@dataclass
class Settings:
    input_device: str = ""
    output_device: str = ""
    monitor_device: str = ""
    monitor_enabled: bool = False
    profile: str = ""
    mode: str = "cpu"
    chunk_ms: int = 80
    threads: int = 2
    gain_db: float = 0.0
    window_w: int = 760
    window_h: int = 700

    @classmethod
    def from_dict(cls, raw: object) -> "Settings":
        data = raw if isinstance(raw, dict) else {}
        settings = cls()
        for field_name in settings.__dataclass_fields__:
            if field_name in data:
                setattr(settings, field_name, data[field_name])
        settings.sanitize()
        return settings

    def sanitize(self) -> None:
        if self.mode not in VALID_MODES:
            self.mode = "cpu"
        try:
            self.chunk_ms = int(self.chunk_ms)
        except (TypeError, ValueError):
            self.chunk_ms = 80
        if self.chunk_ms not in VALID_CHUNKS:
            self.chunk_ms = 80
        try:
            self.threads = int(self.threads)
        except (TypeError, ValueError):
            self.threads = 2
        if self.threads not in (1, 2, 4):
            self.threads = 2
        try:
            self.gain_db = max(-12.0, min(12.0, float(self.gain_db)))
        except (TypeError, ValueError):
            self.gain_db = 0.0
        try:
            self.window_w = max(680, min(1200, int(self.window_w)))
            self.window_h = max(620, min(1100, int(self.window_h)))
        except (TypeError, ValueError):
            self.window_w, self.window_h = 760, 700
        for name in ("input_device", "output_device", "monitor_device", "profile"):
            value = getattr(self, name)
            if not isinstance(value, str):
                setattr(self, name, "")
        self.monitor_enabled = bool(self.monitor_enabled)


def load_settings(path: Path | None = None) -> Settings:
    target = path or settings_path()
    try:
        with target.open("r", encoding="utf-8") as handle:
            return Settings.from_dict(json.load(handle))
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError) as exc:
        log.warning("Could not read settings from %s: %s", target, exc)
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    target = path or settings_path()
    settings.sanitize()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(asdict(settings), handle, indent=2)
        handle.write("\n")
    temporary.replace(target)
