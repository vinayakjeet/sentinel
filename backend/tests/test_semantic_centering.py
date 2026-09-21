"""Mean-centering of case embeddings (app/semantic/embedder.py). Pure numpy: no model, no DB."""

import json

import numpy as np
import pytest

from app.semantic import embedder
from app.semantic.embedder import EMBEDDING_DIM, center_and_normalise, load_mean


def _unit(rows: np.ndarray) -> np.ndarray:
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def test_centering_removes_shared_component_and_stays_unit_norm():
    rng = np.random.default_rng(1)
    shared = np.ones(EMBEDDING_DIM)
    raw = _unit(shared * 3 + rng.normal(size=(200, EMBEDDING_DIM)))
    mean = raw.mean(axis=0)

    before = raw @ raw.T
    out = center_and_normalise(raw, mean)
    after = out @ out.T
    off_diag = ~np.eye(len(raw), dtype=bool)

    assert before[off_diag].mean() > 0.8  # anisotropic: everything looks alike
    assert abs(after[off_diag].mean()) < 0.05  # unrelated pairs now sit near zero
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)


def test_no_mean_is_identity():
    raw = _unit(np.random.default_rng(2).normal(size=(5, EMBEDDING_DIM)))
    assert np.array_equal(center_and_normalise(raw, None), raw)


def test_vector_equal_to_mean_does_not_divide_by_zero():
    mean = _unit(np.ones((1, EMBEDDING_DIM)))[0]
    out = center_and_normalise(mean[None, :], mean)
    assert np.isfinite(out).all()


def test_load_mean_roundtrip_and_shape_check(tmp_path):
    good = tmp_path / "m.json"
    good.write_text(json.dumps({"mean": [0.5] * EMBEDDING_DIM}))
    assert load_mean(good).shape == (EMBEDDING_DIM,)

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"mean": [0.5] * 10}))
    with pytest.raises(RuntimeError):
        load_mean(bad)

    assert load_mean(tmp_path / "missing.json") is None


def test_mean_path_prefers_artifacts_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    assert embedder.mean_path() == tmp_path / embedder.MEAN_FILENAME
