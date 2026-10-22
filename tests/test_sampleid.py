import numpy as np
import pytest
from lastrada.audio.synthetic import demo_pair
from lastrada.recognition.sampleid_adapter import (
    Embeddings,
    chunks,
    group_candidates,
    SampleIDAdapter,
    SampleIDUnavailable,
)


def test_model_optional_without_checkpoint(tmp_path):
    with pytest.raises(SampleIDUnavailable, match="not installed"):
        SampleIDAdapter(tmp_path / "missing.ckpt")


def test_chunks_cpu_mono_16khz_and_short_padding():
    original, new, _ = demo_pair()
    pieces, starts, ends = chunks(original)
    assert len(pieces) == 1
    assert pieces[0].shape == (80000,)
    assert starts[0] == 0 and ends[0] == 4
    pieces, starts, ends = chunks(new)
    assert len(pieces) == 8
    assert ends[-1] == 12


def test_grouped_candidates_temporal_consistency():
    values = np.eye(3)
    original = Embeddings(values, np.array([0, 1, 2]), np.array([5, 6, 7]))
    new = Embeddings(values, np.array([10, 11, 12]), np.array([15, 16, 17]))
    result = group_candidates(original, new, 0.9)
    assert len(result) == 1
    assert result[0].new_start == 10 and result[0].new_end == 17
    assert result[0].original_start == 0 and result[0].original_end == 7
    assert result[0].status == "candidate"


def test_unrelated_embeddings_no_candidate():
    original = Embeddings(np.array([[1.0, 0.0]]), np.array([0]), np.array([5]))
    new = Embeddings(np.array([[0.0, 1.0]]), np.array([0]), np.array([5]))
    assert group_candidates(original, new, 0.9) == []
