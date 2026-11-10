import json

from voxapp.settings import Settings, load_settings, save_settings


def test_defaults_are_valid():
    settings = Settings()
    settings.sanitize()
    assert settings.mode == "cpu"
    assert settings.chunk_ms == 80
    assert settings.threads == 2
    assert settings.gain_db == 0.0


def test_sanitize_repairs_broken_values():
    settings = Settings(
        mode="tensor",
        chunk_ms=20,
        threads=8,
        gain_db=100.0,
        window_w=10,
        window_h=10_000,
        input_device=42,  # type: ignore[arg-type]
    )
    settings.sanitize()
    assert settings.mode == "cpu"
    assert settings.chunk_ms == 80
    assert settings.threads == 2
    assert settings.gain_db == 12.0
    assert (settings.window_w, settings.window_h) == (680, 1100)
    assert settings.input_device == ""


def test_from_dict_ignores_unknown_keys():
    settings = Settings.from_dict({"mode": "gpu", "chunk_ms": 40, "nonsense": True})
    assert settings.mode == "gpu"
    assert settings.chunk_ms == 40
    assert not hasattr(settings, "nonsense")


def test_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(
        input_device="Windows WASAPI::Headset Microphone",
        output_device="Windows WASAPI::CABLE Input",
        monitor_enabled=True,
        profile="me.wav",
        mode="gpu",
        chunk_ms=40,
        threads=4,
        gain_db=-3.5,
    )
    save_settings(original, path)
    assert load_settings(path) == original
    assert json.loads(path.read_text(encoding="utf-8"))["mode"] == "gpu"


def test_missing_file_uses_defaults(tmp_path):
    assert load_settings(tmp_path / "absent.json") == Settings()


def test_corrupt_file_uses_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_settings(path) == Settings()
