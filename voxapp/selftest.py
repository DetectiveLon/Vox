"""A headless check that the model and the packaged runtime actually work.

Used by the installer test and by anyone who wants to verify a build without
opening the window. It can also process a real recording:

  Vox.exe --selftest --input call.wav --profile my_voice.wav --result out.json
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np

from . import __version__
from .engine import EngineError, IsolationModel, gpu_available
from .profiles import load_profile

log = logging.getLogger(__name__)


def _synthetic() -> tuple[np.ndarray, np.ndarray]:
    """Two different pitched voices with speech-like gaps, plus light noise."""
    rate = 16000
    seconds = 8.0
    t = np.arange(int(rate * seconds)) / rate
    rng = np.random.default_rng(7)

    def voice(f0: float, seed: int) -> np.ndarray:
        local = np.random.default_rng(seed)
        signal = np.zeros_like(t)
        for harmonic in range(1, 7):
            signal += (
                np.sin(2 * np.pi * f0 * harmonic * t + local.uniform(0, 2 * np.pi))
                / harmonic
            )
        envelope = 0.55 + 0.45 * np.sin(2 * np.pi * 2.7 * t + local.uniform(0, 6.28))
        gate = (np.sin(2 * np.pi * 0.55 * t + local.uniform(0, 6.28)) > -0.35).astype(float)
        gate[: int(0.8 * rate)] = 1.0
        return (0.07 * signal * envelope * gate).astype(np.float32)

    target = voice(118.0, 3)
    other = voice(219.0, 11)
    mixture = target + other + 0.0015 * rng.standard_normal(len(t)).astype(np.float32)
    return mixture.astype(np.float32), target


def _process(
    model: IsolationModel, sample16: np.ndarray, audio16: np.ndarray
) -> tuple[np.ndarray, float]:
    model.load()
    model.lock(sample16)
    block = model.block_samples
    usable = (len(audio16) // block) * block
    first = True
    chunks: list[np.ndarray] = []
    started = time.perf_counter()
    for offset in range(0, usable, block):
        output = model.process(audio16[offset : offset + block])
        if first:
            missing = block - len(output)
            if missing > 0:
                output = np.concatenate([np.zeros(missing, np.float32), output])
            first = False
        chunks.append(output)
    elapsed = time.perf_counter() - started
    if not chunks:
        return np.zeros(0, np.float32), elapsed
    return np.concatenate(chunks), elapsed


def run_selftest(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="Vox --selftest")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--mode", choices=["cpu", "gpu"], default="cpu")
    parser.add_argument("--chunk", type=int, choices=[40, 80], default=80)
    parser.add_argument("--threads", type=int, choices=[1, 2, 4], default=2)
    parser.add_argument("--input", type=str, default="")
    parser.add_argument("--profile", type=str, default="")
    parser.add_argument("--result", type=str, default="")
    args = parser.parse_args(argv)

    result: dict[str, object] = {
        "ok": False,
        "version": __version__,
        "mode": args.mode,
        "chunk_ms": args.chunk,
        "threads": args.threads,
    }
    try:
        if args.mode == "gpu" and not gpu_available():
            raise EngineError("GPU mode was requested but DirectML is not available.")
        if args.input:
            mixture = load_profile(Path(args.input))
            sample = load_profile(Path(args.profile)) if args.profile else mixture[: 3 * 16000]
        else:
            mixture, sample = _synthetic()
        model = IsolationModel(
            mode=args.mode, chunk_ms=args.chunk, threads=args.threads
        )
        output, elapsed = _process(model, sample, mixture)
        block_seconds = model.block_samples / 16000
        audio_seconds = len(output) / 16000
        rtf = elapsed / audio_seconds if audio_seconds else 0.0
        rms = float(np.sqrt(np.mean(np.square(output, dtype=np.float64)))) if len(output) else 0.0
        finite = bool(np.isfinite(output).all()) if len(output) else False
        ok = bool(len(output) > 0 and finite)
        result.update(
            {
                "ok": ok,
                "seconds_processed": round(audio_seconds, 2),
                "seconds_taken": round(elapsed, 2),
                "rtf": round(rtf, 3),
                "block_ms": round(block_seconds * 1000),
                "output_rms": round(rms, 6),
                "model_root": str(model.folder),
            }
        )
        if not ok:
            result["error"] = "The model produced no usable audio."
    except Exception as exc:
        log.exception("Self-test failed")
        result["error"] = str(exc)

    payload = json.dumps(result, indent=2)
    if args.result:
        Path(args.result).parent.mkdir(parents=True, exist_ok=True)
        Path(args.result).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if result.get("ok") else 1
