from voxapp.devices import AudioDevice, DeviceSet, choose_rate, pick_input, pick_monitor, pick_output

WASAPI = "Windows WASAPI"


def device(index: int, name: str, inputs: int = 1, outputs: int = 1, rate: int = 48_000) -> AudioDevice:
    return AudioDevice(
        index=index,
        name=name,
        hostapi=WASAPI,
        max_input=inputs,
        max_output=outputs,
        default_samplerate=rate,
    )


def test_keys_are_stable_and_ignore_index():
    assert device(3, "Mic").key == device(9, "Mic").key == "Windows WASAPI::Mic"
    assert device(3, "Mic").key != device(3, "Other").key


def test_cable_flags_ignore_case():
    assert device(1, "CABLE Input (VB-Audio Virtual Cable)").is_cable_input
    assert device(2, "CABLE Output (VB-Audio Virtual Cable)").is_cable_output
    assert not device(3, "Speakers").is_cable_input


def test_labels_name_the_role():
    assert "virtual mic" in device(1, "CABLE Input").label
    assert "from the cable" in device(2, "CABLE Output").label
    assert device(3, "Speakers").label == "Speakers"


def sample_set() -> DeviceSet:
    mic = device(1, "Microphone", outputs=0)
    cable_out = device(2, "CABLE Output", outputs=0)
    speakers = device(3, "Speakers", inputs=0)
    cable_in = device(4, "CABLE Input", inputs=0)
    return DeviceSet([mic, cable_out], [speakers, cable_in], mic, speakers, True)


def test_pick_output_prefers_the_stored_device():
    devices = sample_set()
    assert pick_output(devices, "Windows WASAPI::Speakers").name == "Speakers"
    assert pick_output(devices, "Windows WASAPI::Gone").name == "CABLE Input"
    assert pick_output(devices, "").name == "CABLE Input"


def test_pick_input_falls_back_to_default():
    devices = sample_set()
    assert pick_input(devices, "Windows WASAPI::CABLE Output").name == "CABLE Output"
    assert pick_input(devices, "Windows WASAPI::Gone").name == "Microphone"


def test_automatic_input_skips_the_cable():
    devices = sample_set()
    cable_out = devices.find_input("Windows WASAPI::CABLE Output")
    devices.default_input = cable_out
    assert pick_input(devices, "").name == "Microphone"
    # An explicit choice still wins.
    assert pick_input(devices, "Windows WASAPI::CABLE Output").name == "CABLE Output"


def test_monitor_is_never_the_cable_or_the_output():
    devices = sample_set()
    cable_in = devices.find_output("Windows WASAPI::CABLE Input")
    assert pick_monitor(devices, "", cable_in).name == "Speakers"
    # The only speaker is already the output, so there is no monitor candidate.
    assert pick_monitor(devices, "", devices.find_output("Windows WASAPI::Speakers")) is None


def test_choose_rate_falls_back_to_device_default(monkeypatch):
    import sounddevice as sd

    calls = []

    def refuse_48k(*args, **kwargs):
        calls.append(kwargs.get("samplerate"))
        if kwargs.get("samplerate") == 48_000:
            raise sd.PortAudioError("unsupported")

    monkeypatch.setattr(sd, "check_input_settings", refuse_48k)
    rate = choose_rate(device(1, "Old mic", rate=44_100), "input")
    assert rate == 44_100
    assert calls == [48_000, 44_100]
