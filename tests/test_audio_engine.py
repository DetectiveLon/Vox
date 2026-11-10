"""The engine's threading and routing, with PortAudio replaced by fakes."""

import time

import numpy as np
import pytest

from voxapp import engine
from voxapp.devices import AudioDevice


class FakeInputStream:
    def __init__(self, **kwargs):
        self.callback = kwargs.get("callback")
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        pass


class FakeOutputStream:
    instances: list["FakeOutputStream"] = []

    def __init__(self, **kwargs):
        self.written: list[np.ndarray] = []
        FakeOutputStream.instances.append(self)

    def start(self):
        pass

    def write(self, data):
        self.written.append(np.asarray(data, dtype=np.float32).reshape(-1).copy())

    def stop(self):
        pass

    def close(self):
        pass

    def audio(self) -> np.ndarray:
        blocks = [block for block in self.written if block.size]
        return np.concatenate(blocks) if blocks else np.zeros(0, np.float32)


def device(index: int, name: str, inputs: int, outputs: int) -> AudioDevice:
    return AudioDevice(
        index=index,
        name=name,
        hostapi="Windows WASAPI",
        max_input=inputs,
        max_output=outputs,
        default_samplerate=48_000,
    )


@pytest.fixture
def fake_audio(monkeypatch):
    FakeOutputStream.instances.clear()
    monkeypatch.setattr(engine.sd, "InputStream", FakeInputStream)
    monkeypatch.setattr(engine.sd, "OutputStream", FakeOutputStream)
    monkeypatch.setattr(engine.sd, "check_input_settings", lambda **kwargs: None)
    monkeypatch.setattr(engine.sd, "check_output_settings", lambda **kwargs: None)
    return FakeOutputStream


@pytest.fixture
def sample_voice():
    rate = 16_000
    t = np.arange(int(3.2 * rate)) / rate
    return (0.2 * np.sin(2 * np.pi * 130 * t)).astype(np.float32)


def feed(engine_instance, seconds: float, amplitude: float = 0.3) -> None:
    block = 480
    t = np.arange(block) / 48_000
    cycle = (
        amplitude * np.sin(2 * np.pi * 440 * t)
    ).astype(np.float32).reshape(-1, 1)
    for _ in range(int(seconds * 48_000 / block)):
        engine_instance._on_input(cycle, block, None, None)


def wait_for(predicate, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_bypass_passes_the_raw_microphone(fake_audio, sample_voice):
    model = engine.IsolationModel(mode="cpu", chunk_ms=80)
    loop = engine.AudioEngine(
        model, sample_voice, device(1, "Mic", 1, 0), device(2, "Speakers", 0, 1)
    )
    try:
        loop.start()
        loop.set_bypass(True)
        feed(loop, 1.0)
        sink = fake_audio.instances[0]
        assert wait_for(lambda: sink.audio().size > 4_800)
        stats = loop.snapshot()
        assert stats.bypassed
        assert not stats.error
        audio = sink.audio()
        assert np.isfinite(audio).all()
        assert float(np.max(np.abs(audio))) > 0.1
    finally:
        loop.stop()


def test_isolated_audio_reaches_the_output(fake_audio, sample_voice):
    model = engine.IsolationModel(mode="cpu", chunk_ms=80)
    loop = engine.AudioEngine(
        model, sample_voice, device(1, "Mic", 1, 0), device(2, "Speakers", 0, 1)
    )
    try:
        loop.start()
        feed(loop, 0.8)
        sink = fake_audio.instances[0]
        assert wait_for(lambda: sink.audio().size > 4_800)
        stats = loop.snapshot()
        assert not stats.error, stats.error
        assert stats.running
        audio = sink.audio()
        assert np.isfinite(audio).all()
    finally:
        loop.stop()
