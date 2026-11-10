"""WASAPI device discovery and stable device keys.

PortAudio device numbers change when hardware comes and goes, so settings store
"host API::name" instead and resolve it again on every launch.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import sounddevice as sd

log = logging.getLogger(__name__)

WASAPI = "Windows WASAPI"

# "CABLE Input", and also "CABLE-A Input" from the A+B pack.
_CABLE_ROLE = re.compile(r"cable(?:[- ][a-d])?\s+(input|output)", re.IGNORECASE)


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    hostapi: str
    max_input: int
    max_output: int
    default_samplerate: int

    @property
    def key(self) -> str:
        return f"{self.hostapi}::{self.name}"

    @property
    def cable_role(self) -> str | None:
        """'input' for a cable's playback side, 'output' for its capture side."""
        match = _CABLE_ROLE.search(self.name)
        return match.group(1).lower() if match else None

    @property
    def is_cable_input(self) -> bool:
        return self.cable_role == "input"

    @property
    def is_cable_output(self) -> bool:
        return self.cable_role == "output"

    @property
    def label(self) -> str:
        if self.is_cable_input:
            return f"{self.name}  (virtual mic)"
        if self.is_cable_output:
            return f"{self.name}  (from the cable)"
        return self.name

    @property
    def cable_family(self) -> str | None:
        """The cable a device belongs to, for either end of it. None for real devices."""
        if not (self.is_cable_input or self.is_cable_output):
            return None
        start, end = self.name.rfind("("), self.name.rfind(")")
        if 0 <= start < end:
            return self.name[start + 1:end].strip().lower()
        return self.name.strip().lower()


def cable_loop(source: AudioDevice | None, sink: AudioDevice | None) -> bool:
    """True when Vox would capture the very cable it plays into.

    Windows makes anything played to CABLE Input appear on CABLE Output, so that
    pairing feeds the processed voice straight back into the microphone, where it
    is processed again, and again. It sounds like electrical noise."""
    if source is None or sink is None:
        return False
    if not (source.is_cable_output and sink.is_cable_input):
        return False
    return source.cable_family == sink.cable_family


@dataclass
class DeviceSet:
    inputs: list[AudioDevice]
    outputs: list[AudioDevice]
    default_input: AudioDevice | None
    default_output: AudioDevice | None
    wasapi_available: bool

    def find_input(self, key: str) -> AudioDevice | None:
        return next((device for device in self.inputs if device.key == key), None)

    def find_output(self, key: str) -> AudioDevice | None:
        return next((device for device in self.outputs if device.key == key), None)

    @property
    def cable_input(self) -> AudioDevice | None:
        return next((device for device in self.outputs if device.is_cable_input), None)

    @property
    def cable_output(self) -> AudioDevice | None:
        return next((device for device in self.inputs if device.is_cable_output), None)


def _wasapi_hostapi_index() -> int | None:
    for index, hostapi in enumerate(sd.query_hostapis()):
        if hostapi["name"] == WASAPI:
            return index
    return None


def scan() -> DeviceSet:
    """All WASAPI endpoints, split into inputs and outputs."""
    wasapi = _wasapi_hostapi_index()
    inputs: list[AudioDevice] = []
    outputs: list[AudioDevice] = []
    default_input = default_output = None
    if wasapi is None:
        return DeviceSet([], [], None, None, False)

    hostapi = sd.query_hostapis(wasapi)
    for index, info in enumerate(sd.query_devices()):
        if info["hostapi"] != wasapi:
            continue
        device = AudioDevice(
            index=index,
            name=str(info["name"]).strip(),
            hostapi=WASAPI,
            max_input=int(info["max_input_channels"]),
            max_output=int(info["max_output_channels"]),
            default_samplerate=int(round(float(info["default_samplerate"]))),
        )
        if device.max_input > 0:
            inputs.append(device)
        if device.max_output > 0:
            outputs.append(device)

    def pick(items: list[AudioDevice], index: object) -> AudioDevice | None:
        try:
            wanted = int(index)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return items[0] if items else None
        return next((item for item in items if item.index == wanted), items[0] if items else None)

    default_input = pick(inputs, hostapi.get("default_input_device", -1))
    default_output = pick(outputs, hostapi.get("default_output_device", -1))
    return DeviceSet(inputs, outputs, default_input, default_output, True)


def pick_output(devices: DeviceSet, stored: str) -> AudioDevice | None:
    """Stored output if it still exists, else the cable, else the system default."""
    return (
        devices.find_output(stored)
        or devices.cable_input
        or devices.default_output
        or (devices.outputs[0] if devices.outputs else None)
    )


def pick_input(devices: DeviceSet, stored: str) -> AudioDevice | None:
    """Stored input if it still exists, else the default, skipping the cable.

    The cable's capture side is a valid input when another application is
    routed through Vox, so an explicit stored choice is always respected. Only
    the automatic choice avoids it, because on a PC with VB-CABLE installed it
    is often the system default and captures nothing useful.
    """
    chosen = devices.find_input(stored)
    if chosen is not None:
        return chosen
    if devices.default_input is not None and not devices.default_input.is_cable_output:
        return devices.default_input
    return next(
        (device for device in devices.inputs if not device.is_cable_output),
        devices.default_input or (devices.inputs[0] if devices.inputs else None),
    )


def pick_monitor(devices: DeviceSet, stored: str, output: AudioDevice | None) -> AudioDevice | None:
    """A speaker/headphone endpoint, never the virtual cable itself."""
    candidate = devices.find_output(stored)
    if candidate and not candidate.is_cable_input and (output is None or candidate.index != output.index):
        return candidate
    if devices.default_output and not devices.default_output.is_cable_input:
        if output is None or devices.default_output.index != output.index:
            return devices.default_output
    return next(
        (
            device
            for device in devices.outputs
            if not device.is_cable_input and (output is None or device.index != output.index)
        ),
        None,
    )


def choose_rate(device: AudioDevice, kind: str, preferred: int = 48000) -> int:
    """Prefer 48 kHz, fall back to the endpoint default if the device refuses it.

    WASAPI shared mode normally mixes at 48 kHz, so the preferred rate is almost
    always accepted; the fallback covers older or unusual drivers.
    """
    candidates = [preferred]
    if device.default_samplerate != preferred:
        candidates.append(device.default_samplerate)
    for rate in candidates:
        try:
            sd.check_input_settings(
                device=device.index, channels=1, dtype="float32", samplerate=rate
            ) if kind == "input" else sd.check_output_settings(
                device=device.index, channels=1, dtype="float32", samplerate=rate
            )
            return rate
        except Exception as exc:  # PortAudio raises its own exception type
            log.debug("Device %s refuses %s Hz (%s): %s", device.name, rate, kind, exc)
    return device.default_samplerate
