import pytest

from voxapp.engine import CHUNK_FRAMES, IsolationModel


@pytest.mark.parametrize("chunk_ms,frames", sorted(CHUNK_FRAMES.items()))
def test_block_and_fixed_shape(chunk_ms, frames):
    model = IsolationModel(mode="cpu", chunk_ms=chunk_ms)
    assert model.frames == frames
    assert model.block_samples == frames * 128
    # 512-sample window plus one 128-sample hop for every frame after the first.
    assert model.fixed_samples == 512 + (frames - 1) * 128


def test_80ms_is_the_default_shape():
    model = IsolationModel()
    assert model.chunk_ms == 80
    assert model.block_samples == 1280
    assert model.fixed_samples == 1664


def test_unknown_chunk_is_rejected():
    with pytest.raises(ValueError):
        IsolationModel(chunk_ms=20)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        IsolationModel(mode="tensor")


def test_key_identifies_a_loaded_model():
    before = IsolationModel(mode="cpu", chunk_ms=40, threads=2).key
    assert before == ("cpu", 40, 2)
    assert before != IsolationModel(mode="gpu", chunk_ms=40, threads=2).key
