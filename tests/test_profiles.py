import numpy as np
import pytest

from voxapp import profiles


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path


def tone(seconds: float, rate: int = 16_000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.2 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)


def test_sanitize_name_strips_path_characters():
    assert profiles.sanitize_name('a<b>:"c/d\\e|f?g*') == "abcdefg"
    assert profiles.sanitize_name("   ") == "My voice"
    assert profiles.sanitize_name("x" * 100) == "x" * 60


def test_save_then_load_roundtrip(appdata):
    audio = tone(5.0)
    path = profiles.save_profile("Test voice", audio)
    assert path.parent == appdata / "Vox" / "profiles"
    assert path.suffix == ".wav"

    loaded = profiles.load_profile(path)
    assert loaded.dtype == np.float32
    assert abs(len(loaded) - len(audio)) <= 1
    assert float(np.max(np.abs(loaded))) > 0.1


def test_saved_profile_appears_in_list(appdata):
    profiles.save_profile("First", tone(4.0))
    found = profiles.list_profiles()
    assert [item.name for item in found] == ["First"]
    assert 3.9 < found[0].duration < 4.1


def test_short_recording_is_rejected(appdata):
    with pytest.raises(profiles.ProfileError, match="at least"):
        profiles.save_profile("Too short", tone(2.0))


def test_long_recording_is_trimmed(appdata):
    path = profiles.save_profile("Long", tone(40.0))
    assert abs(profiles.list_profiles()[0].duration - 30.0) < 0.1
    assert path.exists()


def test_unique_names_do_not_overwrite(appdata):
    first = profiles.save_profile("Same", tone(3.5))
    second = profiles.save_profile("Same", tone(3.5))
    assert first != second
    assert len(profiles.list_profiles()) == 2


def test_import_reads_any_rate(tmp_path, appdata):
    import soundfile as sf

    source = tmp_path / "call.wav"
    sf.write(str(source), tone(6.0, 44_100), 44_100, subtype="PCM_16")
    imported = profiles.import_audio(source, "From call")
    loaded = profiles.load_profile(imported)
    assert abs(len(loaded) - 6 * 16_000) < 32
