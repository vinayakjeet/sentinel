"""CaseEmbedder — sentence-transformers MiniLM, loaded exactly once (DESIGN §8).

The model is ~90 MB and takes several seconds to construct, so it is a process-level singleton
behind a lock. Lane A's lifespan hook can warm it at startup with `get_embedder()`; if it does
not, the first request pays the cost once and every later request is fast.

Mean-centering. MiniLM vectors of same-template text share a large common component, so raw
cosine between two unrelated case narratives is ~0.80 and between neighbours ~0.99 (measured on
the 41,858-row corpus: random-pair mean 0.799, std 0.084). We subtract the corpus mean vector
and re-normalise, which puts unrelated pairs at ~0.0 (std 0.361). The mean is fitted once by
`ml/scripts/backfill_embeddings.py --recompute` and stored in `embedding_mean_v1.json` next to
the model artifacts; every stored vector and every query goes through the same transform, so
the corpus and the queries stay comparable. Changing that file requires re-embedding the corpus.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Sequence
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

MEAN_FILENAME = "embedding_mean_v1.json"

_lock = threading.Lock()
_embedder: CaseEmbedder | None = None


def mean_path() -> Path:
    """Where the fitted corpus mean lives: ARTIFACTS_DIR (the container mount), else ml/artifacts."""
    base = os.environ.get("ARTIFACTS_DIR")
    if base and Path(base).is_dir():
        return Path(base) / MEAN_FILENAME
    return Path(__file__).resolve().parents[3] / "ml" / "artifacts" / MEAN_FILENAME


def load_mean(path: Path | None = None) -> np.ndarray | None:
    path = path or mean_path()
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    mean = np.asarray(payload["mean"], dtype=np.float64)
    if mean.shape != (EMBEDDING_DIM,):
        raise RuntimeError(f"{path} holds a {mean.shape} mean; expected ({EMBEDDING_DIM},)")
    return mean


def center_and_normalise(vectors: np.ndarray, mean: np.ndarray | None) -> np.ndarray:
    """(v - mean), then L2-normalise. With no mean this is the identity on unit vectors."""
    vectors = np.asarray(vectors, dtype=np.float64)
    if mean is None:
        return vectors
    centered = vectors - mean
    norms = np.linalg.norm(centered, axis=1, keepdims=True)
    return centered / np.maximum(norms, 1e-12)


class CaseEmbedder:
    """Encodes case narratives into unit-norm 384-dim vectors."""

    def __init__(self, model_name: str = MODEL_NAME, mean: np.ndarray | None = None) -> None:
        # Imported lazily so that importing this module (e.g. in a test that never embeds) does
        # not drag in torch.
        from sentence_transformers import SentenceTransformer

        logger.info("loading embedding model", extra={"model": model_name})
        self._model = SentenceTransformer(model_name)
        self.model_name = model_name
        self.mean = mean if mean is not None else load_mean()
        if self.mean is None:
            logger.warning(
                "no corpus mean found; embeddings are NOT centered and will not match a centered corpus",
                extra={"path": str(mean_path())},
            )
        dim = int(self._model.get_sentence_embedding_dimension())
        if dim != EMBEDDING_DIM:
            raise RuntimeError(
                f"{model_name} produces {dim}-dim vectors but case_embeddings is vector({EMBEDDING_DIM})"
            )

    def encode(self, text: str) -> list[float]:
        return self.encode_many([text])[0]

    def encode_raw_many(self, texts: Sequence[str]) -> np.ndarray:
        """Unit-norm MiniLM vectors, before centering. Used to fit the corpus mean."""
        if not texts:
            return np.zeros((0, EMBEDDING_DIM))
        return self._model.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        ).astype(np.float64)

    def encode_many(self, texts: Sequence[str]) -> list[list[float]]:
        """Centered, unit-norm embeddings, so cosine distance and inner product agree."""
        vectors = center_and_normalise(self.encode_raw_many(texts), self.mean)
        return [[float(x) for x in row] for row in vectors]


def get_embedder() -> CaseEmbedder:
    """Process-wide singleton. Safe to call from a background task or at startup."""
    global _embedder
    if _embedder is None:
        with _lock:
            if _embedder is None:
                _embedder = CaseEmbedder()
    return _embedder


def reset_embedder() -> None:
    """Test hook only."""
    global _embedder
    with _lock:
        _embedder = None
