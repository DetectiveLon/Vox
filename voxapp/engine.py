"""Real-time audio engine.

Three stages, each on its own thread:

  capture (PortAudio callback) -> bounded queue -> inference worker -> output queues
                                                                  -> one writer per output device

The microphone callback never waits for the model. If inference falls behind,
the oldest capture block is dropped and the UI is told, instead of the delay
growing without bound.

VoxLock runs on 16 kHz mono audio. The engine keeps a 48 kHz timeline for the
raw/bypass path and resamples around the model.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import sounddevice as sd
import soxr

from .devices import AudioDevice, choose_rate
from .paths import models_dir

log = logging.getLogger(__name__)

CANON_RATE = 48_000
MODEL_RATE = 16_000
HOP = 128
CHUNK_FRAMES = {40: 5, 80: 10}
EMIT = 480  # 10 ms of the 48 kHz timeline
IN_QUEUE_BLOCKS = 100
OUT_QUEUE_BLOCKS = 100


class EngineError(Exception):
    """Something the user can act on: missing model, busy device, no GPU."""


@dataclass
class EngineStats:
    running: bool = False
    bypassed: bool = False
    input_rms: float = 0.0
    output_rms: float = 0.0
    infer_ms: float = 0.0
    rtf: float = 0.0
    underruns: int = 0
    overruns: int = 0
    queue_ms: int = 0
    mode: str = "cpu"
    chunk_ms: int = 80
    error: str = ""


def _rms(block: np.ndarray) -> float:
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))


def gpu_available() -> bool:
    """True when the installed ONNX Runtime has the DirectML provider."""
    try:
        import onnxruntime as ort

        return "DmlExecutionProvider" in ort.get_available_providers()
    except Exception as exc:
        log.debug("Could not query ONNX Runtime providers: %s", exc)
        return False


class IsolationModel:
    """VoxLock with a fixed inference shape, so DirectML compiles it once."""

    def __init__(
        self,
        mode: str = "cpu",
        chunk_ms: int = 80,
        threads: int = 2,
        folder: Path | None = None,
    ) -> None:
        if mode not in ("cpu", "gpu"):
            raise ValueError(f"Unknown mode: {mode}")
        if chunk_ms not in CHUNK_FRAMES:
            raise ValueError(f"Unsupported chunk size: {chunk_ms}")
        self.mode = mode
        self.chunk_ms = chunk_ms
        self.threads = threads
        self.folder = Path(folder) if folder else models_dir()
        self.frames = CHUNK_FRAMES[chunk_ms]
        self.block_samples = self.frames * HOP
        self.fixed_samples = 512 + (self.frames - 1) * HOP
        self._vl = None
        self._stream = None
        self._load_lock = threading.Lock()

    @property
    def key(self) -> tuple[str, int, int]:
        return (self.mode, self.chunk_ms, self.threads)

    def _check_files(self) -> None:
        needed = ["enroll.onnx", "enroll_fp16.onnx", "chunk_int8.onnx", "chunk_fp16.onnx"]
        missing = [name for name in needed if not (self.folder / name).is_file()]
        if missing:
            raise EngineError(
                "The voice model is missing from the installation: "
                + ", ".join(missing)
                + ". Reinstall Vox."
            )

    def load(self) -> None:
        """Create the ONNX sessions. Safe to call once; cheap to call again."""
        with self._load_lock:
            if self._vl is not None:
                return
            self._check_files()
            import onnxruntime as ort
            from voxlock.core import VoxLock

            precision = "int8" if self.mode == "cpu" else "fp16"
            if self.mode == "gpu":
                providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
            else:
                providers = ["CPUExecutionProvider"]
            if self.mode == "gpu" and "DmlExecutionProvider" not in ort.get_available_providers():
                raise EngineError(
                    "GPU mode needs the DirectML build of ONNX Runtime, which is not installed. "
                    "Use CPU mode or reinstall Vox."
                )

            original = ort.InferenceSession

            def session_factory(path, sess_options=None, **kwargs):
                options = sess_options or ort.SessionOptions()
                if "chunk" in Path(str(path)).name:
                    # Without this, DirectML recompiles the graph for every
                    # slightly different chunk length and runs 8x slower.
                    options.add_free_dimension_override_by_name("S", self.fixed_samples)
                kwargs.pop("providers", None)
                return original(path, options, providers=providers)

            started = time.perf_counter()
            try:
                ort.InferenceSession = session_factory  # type: ignore[assignment]
                self._vl = VoxLock(
                    model_dir=str(self.folder),
                    precision=precision,
                    threads=self.threads if self.mode == "cpu" else 1,
                )
            except EngineError:
                raise
            except Exception as exc:
                raise EngineError(f"Could not load the voice model: {exc}") from exc
            finally:
                ort.InferenceSession = original  # type: ignore[assignment]

            active = self._vl.chunk.get_providers()
            if self.mode == "gpu" and "DmlExecutionProvider" not in active:
                self._vl = None
                raise EngineError(
                    "DirectML was requested but ONNX Runtime did not activate it. "
                    "Use CPU mode or update your graphics driver."
                )
            log.info(
                "Loaded %s model (%s, %d ms, %d frames) in %.2fs on %s",
                precision,
                self.mode,
                self.chunk_ms,
                self.frames,
                time.perf_counter() - started,
                ", ".join(active),
            )

    def lock(self, sample16: np.ndarray) -> None:
        """Start a fresh stream locked to this voice sample."""
        if self._vl is None:
            self.load()
        assert self._vl is not None
        self._stream = self._vl.stream(np.asarray(sample16, dtype=np.float32))
        # VoxLock's first push builds its reflect padding. 128 samples is too
        # short to produce output, and leaves the next block exactly aligned.
        self._stream.push(np.zeros(HOP, np.float32), frames_per_run=self.frames)

    def process(self, block16: np.ndarray) -> np.ndarray:
        if self._stream is None:
            raise EngineError("The model has no voice profile loaded.")
        if len(block16) != self.block_samples:
            raise EngineError(
                f"Internal audio block is {len(block16)} samples, expected {self.block_samples}."
            )
        return np.asarray(
            self._stream.push(block16, frames_per_run=self.frames), dtype=np.float32
        )

    def unload(self) -> None:
        self._stream = None
        self._vl = None


class OutputSink:
    """One output device, its own resampler and writer thread."""

    def __init__(self, device: AudioDevice, name: str) -> None:
        self.device = device
        self.name = name
        self.rate = choose_rate(device, "output")
        self.queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=OUT_QUEUE_BLOCKS)
        self._stop = threading.Event()
        self._stream: sd.OutputStream | None = None
        self._thread: threading.Thread | None = None
        self._resampler = (
            soxr.ResampleStream(CANON_RATE, self.rate, 1, dtype="float32", quality="LQ")
            if self.rate != CANON_RATE
            else None
        )
        self.error: str = ""
        self.dropped = 0
        self.underruns = 0
        self._armed = False

    def start(self) -> None:
        self._stream = sd.OutputStream(
            device=self.device.index,
            samplerate=self.rate,
            channels=1,
            dtype="float32",
            blocksize=0,
            latency="low",
        )
        self._stream.start()
        self._thread = threading.Thread(
            target=self._run, name=f"vox-out-{self.name}", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        assert self._stream is not None
        silence = np.zeros(max(160, int(self.rate * 0.01)), np.float32)
        try:
            while not self._stop.is_set():
                try:
                    block = self.queue.get(timeout=0.05)
                except queue.Empty:
                    if self._armed:
                        self.underruns += 1
                    block = silence
                output = (
                    self._resampler.resample_chunk(block) if self._resampler else block
                )
                if len(output) == 0:
                    continue
                self._stream.write(np.asarray(output, np.float32).reshape(-1, 1))
        except Exception as exc:
            self.error = f"{self.name}: {exc}"
            log.exception("Output stream %s failed", self.name)

    def push(self, block: np.ndarray) -> None:
        self._armed = True
        try:
            self.queue.put_nowait(block)
        except queue.Full:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            self.dropped += 1
            try:
                self.queue.put_nowait(block)
            except queue.Full:
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        if self._stream is not None:
            try:
                self._stream.stop()
            finally:
                self._stream.close()
            self._stream = None


class AudioEngine:
    """Capture, isolate, and send the result to one or two outputs."""

    def __init__(
        self,
        model: IsolationModel,
        sample16: np.ndarray,
        input_device: AudioDevice,
        output_device: AudioDevice,
        monitor_device: AudioDevice | None = None,
        gain_db: float = 0.0,
    ) -> None:
        self.model = model
        self.sample16 = np.asarray(sample16, dtype=np.float32)
        self.input_device = input_device
        self.output_device = output_device
        self.monitor_device = monitor_device
        self._stats = EngineStats(mode=model.mode, chunk_ms=model.chunk_ms)
        self._stop = threading.Event()
        self._bypass = threading.Event()
        self._reset_requested = threading.Event()
        self._input_stream: sd.InputStream | None = None
        self._input_rate = 48_000
        self._input_block = 480
        self._in_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=IN_QUEUE_BLOCKS)
        self._sinks: list[OutputSink] = []
        self._worker: threading.Thread | None = None
        self._gain = float(10.0 ** (gain_db / 20.0))
        self._fatal = ""
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        if self.monitor_device is not None and self.monitor_device.index == self.output_device.index:
            raise EngineError("The monitor and the virtual microphone are the same device.")
        self._stop.clear()
        self._bypass.clear()
        self._reset_requested.clear()
        self._fatal = ""
        self._stats = EngineStats(mode=self.model.mode, chunk_ms=self.model.chunk_ms)
        self._in_queue = queue.Queue(maxsize=IN_QUEUE_BLOCKS)

        self._input_rate = choose_rate(self.input_device, "input")
        self._input_block = max(160, int(self._input_rate * 0.01))
        try:
            self._input_stream = sd.InputStream(
                device=self.input_device.index,
                samplerate=self._input_rate,
                channels=1,
                dtype="float32",
                blocksize=self._input_block,
                latency="low",
                callback=self._on_input,
            )
            self._input_stream.start()
        except Exception as exc:
            self._input_stream = None
            raise EngineError(f"Could not open the microphone: {exc}") from exc

        try:
            self._sinks = [OutputSink(self.output_device, "main")]
            if self.monitor_device is not None:
                self._sinks.append(OutputSink(self.monitor_device, "monitor"))
            for sink in self._sinks:
                sink.start()
        except Exception as exc:
            self._close_input()
            for sink in self._sinks:
                try:
                    sink.stop()
                except Exception:
                    pass
            self._sinks = []
            raise EngineError(f"Could not open the output device: {exc}") from exc

        self._stats.running = True
        self._running = True
        self._worker = threading.Thread(target=self._work, name="vox-inference", daemon=True)
        self._worker.start()
        log.info(
            "Started: in=%s @%d, out=%s @%d, mode=%s, chunk=%d ms",
            self.input_device.name,
            self._input_rate,
            self.output_device.name,
            self._sinks[0].rate,
            self.model.mode,
            self.model.chunk_ms,
        )

    def _close_input(self) -> None:
        stream, self._input_stream = self._input_stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

    def _on_input(self, indata, frames, time_info, status) -> None:
        if status:
            self._stats.overruns += 1
        block = np.asarray(indata[:, 0], dtype=np.float32).copy()
        self._stats.input_rms = _rms(block)
        try:
            self._in_queue.put_nowait(block)
        except queue.Full:
            try:
                self._in_queue.get_nowait()
            except queue.Empty:
                pass
            self._stats.overruns += 1
            try:
                self._in_queue.put_nowait(block)
            except queue.Full:
                pass

    def _emit(self, block48: np.ndarray) -> None:
        output = block48 * self._gain
        np.clip(output, -1.0, 1.0, out=output)
        self._stats.output_rms = _rms(output)
        for sink in self._sinks:
            sink.push(output)

    def _work(self) -> None:
        try:
            self._work_inner()
        except Exception as exc:
            self._fatal = str(exc)
            self._stats.error = self._fatal
            log.exception("Inference worker stopped")
            self._stop.set()

    def _work_inner(self) -> None:
        block16 = self.model.block_samples
        input_resampler = (
            soxr.ResampleStream(
                self._input_rate, CANON_RATE, 1, dtype="float32", quality="LQ"
            )
            if self._input_rate != CANON_RATE
            else None
        )
        to_model = soxr.ResampleStream(
            CANON_RATE, MODEL_RATE, 1, dtype="float32", quality="LQ"
        )
        to_canon = soxr.ResampleStream(
            MODEL_RATE, CANON_RATE, 1, dtype="float32", quality="LQ"
        )
        pending16 = np.zeros(0, np.float32)
        pending48 = np.zeros(0, np.float32)
        first_block = True
        self.model.lock(self.sample16)

        while not self._stop.is_set():
            try:
                raw = self._in_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            self._stats.queue_ms = int(
                self._in_queue.qsize() * (len(raw) / self._input_rate * 1000)
            )
            x48 = (
                input_resampler.resample_chunk(raw).astype(np.float32)
                if input_resampler
                else raw
            )

            if self._bypass.is_set():
                self._emit(x48)
                continue

            if self._reset_requested.is_set():
                self._reset_requested.clear()
                self.model.lock(self.sample16)
                pending16 = np.zeros(0, np.float32)
                pending48 = np.zeros(0, np.float32)
                first_block = True

            pending16 = np.concatenate(
                [pending16, to_model.resample_chunk(x48).astype(np.float32)]
            )
            while len(pending16) >= block16:
                chunk16 = pending16[:block16]
                pending16 = pending16[block16:]
                started = time.perf_counter()
                output16 = self.model.process(chunk16)
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                self._stats.infer_ms = (
                    0.8 * self._stats.infer_ms + 0.2 * elapsed_ms
                    if self._stats.infer_ms
                    else elapsed_ms
                )
                block_ms = block16 / MODEL_RATE * 1000.0
                self._stats.rtf = self._stats.infer_ms / block_ms
                if first_block:
                    missing = block16 - len(output16)
                    if missing > 0:
                        output16 = np.concatenate(
                            [np.zeros(missing, np.float32), output16]
                        )
                    first_block = False
                if len(output16) == 0:
                    continue
                pending48 = np.concatenate(
                    [pending48, to_canon.resample_chunk(output16).astype(np.float32)]
                )
                while len(pending48) >= EMIT:
                    self._emit(pending48[:EMIT])
                    pending48 = pending48[EMIT:]

    def set_bypass(self, enabled: bool) -> None:
        if enabled:
            self._bypass.set()
        else:
            self._reset_requested.set()
            self._bypass.clear()
        self._stats.bypassed = enabled

    def set_gain(self, gain_db: float) -> None:
        self._gain = float(10.0 ** (max(-24.0, min(24.0, gain_db)) / 20.0))

    def snapshot(self) -> EngineStats:
        stats = replace(self._stats)
        if self._fatal:
            stats.error = self._fatal
        for sink in self._sinks:
            if sink.error:
                stats.error = stats.error or sink.error
            stats.underruns = max(stats.underruns, sink.underruns)
            stats.overruns = max(stats.overruns, sink.dropped)
        return stats

    def stop(self) -> None:
        if not self._running and self._input_stream is None:
            return
        self._stop.set()
        self._close_input()
        worker = self._worker
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=2.0)
        self._worker = None
        for sink in self._sinks:
            try:
                sink.stop()
            except Exception:
                log.exception("Could not close output device %s", sink.name)
        self._sinks = []
        self._running = False
        self._stats.running = False
        log.info("Stopped")
