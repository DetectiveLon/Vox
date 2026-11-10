"""Voice profiles: record, import, validate, save and load.

VoxLock needs at least three seconds of clean speech from the person who should
stay. Ten to fifteen seconds gives it a better voice sample; thirty is the most
it looks at, so longer files are trimmed on import.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
import soxr

from .devices import AudioDevice, choose_rate
from .paths import profiles_dir

log = logging.getLogger(__name__)

MODEL_RATE = 16000
MIN_SECONDS = 3.0
MAX_SECONDS = 30.0
DEFAULT_SECONDS = 10.0


class RecordingCancelled(Exception):
    """The user stopped the recording before it finished."""


class ProfileError(Exception):
    """A profile cannot be used, with a message meant for the user."""


@dataclass(frozen=True)
class ProfileInfo:
    path: Path
    name: str
    duration: float

    @property
    def label(self) -> str:
        return f"{self.name}  ({self.duration:.1f}s)"


def sanitize_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:60] or "My voice"


def unique_path(name: str) -> Path:
    folder = profiles_dir()
    folder.mkdir(parents=True, exist_ok=True)
    base = sanitize_name(name)
    candidate = folder / f"{base}.wav"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{base} {counter}.wav"
        counter += 1
    return candidate


def list_profiles() -> list[ProfileInfo]:
    folder = profiles_dir()
    if not folder.exists():
        return []
    found: list[ProfileInfo] = []
    for path in sorted(folder.glob("*.wav")):
        try:
            info = sf.info(str(path))
            duration = info.frames / info.samplerate if info.samplerate else 0.0
        except Exception as exc:
            log.warning("Skipping unreadable profile %s: %s", path, exc)
            continue
        found.append(ProfileInfo(path=path, name=path.stem, duration=duration))
    return found


def load_profile(path: Path) -> np.ndarray:
    """Read any soundfile-supported file as 16 kHz mono float32."""
    return _read_as_model_audio(Path(path))


def _read_as_model_audio(path: Path) -> np.ndarray:
    try:
        data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception as exc:
        raise ProfileError(f"Could not read {path.name}: {exc}") from exc
    if data.size == 0:
        raise ProfileError(f"{path.name} contains no audio.")
    mono = data.mean(axis=1, dtype=np.float32)
    if rate != MODEL_RATE:
        mono = soxr.resample(mono, rate, MODEL_RATE).astype(np.float32)
    max_samples = int(MAX_SECONDS * MODEL_RATE)
    if len(mono) > max_samples:
        mono = mono[:max_samples]
    if len(mono) < int(MIN_SECONDS * MODEL_RATE):
        raise ProfileError(
            f"The voice sample is {len(mono) / MODEL_RATE:.1f}s long. "
            f"Vox needs at least {MIN_SECONDS:.0f} seconds."
        )
    return np.ascontiguousarray(mono, dtype=np.float32)


def save_profile(name: str, samples16: np.ndarray) -> Path:
    audio = np.asarray(samples16, dtype=np.float32).reshape(-1)
    if len(audio) < int(MIN_SECONDS * MODEL_RATE):
        raise ProfileError(
            f"Record at least {MIN_SECONDS:.0f} seconds of speech "
            f"(got {len(audio) / MODEL_RATE:.1f}s)."
        )
    max_samples = int(MAX_SECONDS * MODEL_RATE)
    if len(audio) > max_samples:
        audio = audio[:max_samples]
    audio = np.clip(audio, -1.0, 1.0)
    path = unique_path(name)
    sf.write(str(path), audio, MODEL_RATE, subtype="PCM_16")  # str: soundfile is happiest with a plain path
    log.info("Saved voice profile %s (%.1fs)", path.name, len(audio) / MODEL_RATE)
    return path


def import_audio(source: Path, name: str | None = None) -> Path:
    audio = _read_as_model_audio(Path(source))
    return save_profile(name or Path(source).stem, audio)


def record(
    device: AudioDevice,
    duration: float = DEFAULT_SECONDS,
    stop_event: threading.Event | None = None,
    progress=None,
) -> np.ndarray:
    """Record from a WASAPI input and return 16 kHz mono float32.

    `progress(fraction, level)` is called about ten times a second so the UI can
    show a level meter without doing any audio work on the GUI thread.
    """
    if duration < 1.0 or duration > 60.0:
        raise ValueError("Recording duration must be between 1 and 60 seconds.")
    stop_event = stop_event or threading.Event()
    rate = choose_rate(device, "input")
    block = max(160, int(rate * 0.01))
    total = int(rate * duration)
    captured: list[np.ndarray] = []
    got = 0
    stream = None
    try:
        stream = sd.InputStream(
            device=device.index,
            samplerate=rate,
            channels=1,
            dtype="float32",
            blocksize=block,
            latency="low",
        )
        stream.start()
        while got < total:
            if stop_event.is_set():
                raise RecordingCancelled()
            data, overflowed = stream.read(block)
            if overflowed:
                log.debug("Input overflow while recording the voice profile")
            chunk = np.asarray(data[:, 0], dtype=np.float32).copy()
            captured.append(chunk)
            got += len(chunk)
            if progress is not None:
                progress(min(1.0, got / total), float(np.sqrt(np.mean(chunk**2))))
    finally:
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
    audio = np.concatenate(captured) if captured else np.zeros(0, np.float32)
    if rate != MODEL_RATE:
        audio = soxr.resample(audio, rate, MODEL_RATE).astype(np.float32)
    return np.ascontiguousarray(audio[: int(duration * MODEL_RATE)], dtype=np.float32)


def waveform_peaks(samples: np.ndarray | None, buckets: int = 220) -> list[float]:
    """Downsample a waveform to peak values in 0..1 for drawing."""
    if samples is None or len(samples) == 0:
        return []
    data = np.asarray(samples, dtype=np.float32).reshape(-1)
    buckets = max(8, int(buckets))
    if len(data) < buckets:
        padded = np.zeros(buckets, np.float32)
        padded[: len(data)] = np.abs(data)
        peaks = padded
    else:
        edges = np.linspace(0, len(data), buckets + 1, dtype=np.int64)
        peaks = np.array(
            [np.max(np.abs(data[edges[i] : edges[i + 1]])) if edges[i + 1] > edges[i] else 0.0 for i in range(buckets)],
            dtype=np.float32,
        )
    ceiling = float(peaks.max())
    if ceiling > 1e-6:
        peaks = peaks / ceiling
    return [float(value) for value in peaks]
