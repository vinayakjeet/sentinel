"""CaseEmbedder — sentence-transformers MiniLM, loaded exactly once (DESIGN §8).

The model is ~90 MB and takes several seconds to construct, so it is a process-level singleton
behind a lock. Lane A's lifespan hook can warm it at startup with `get_embedder()`; if it does
not, the first request pays the cost once and every later request is fast.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence

logger = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_lock = threading.Lock()
_embedder: CaseEmbedder | None = None


class CaseEmbedder:
    """Encodes case narratives into unit-norm 384-dim vectors."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        # Imported lazily so that importing this module (e.g. in a test that never embeds) does
        # not drag in torch.
        from sentence_transformers import SentenceTransformer

        logger.info("loading embedding model", extra={"model": model_name})
        self._model = SentenceTransformer(model_name)
        self.model_name = model_name
        dim = int(self._model.get_sentence_embedding_dimension())
        if dim != EMBEDDING_DIM:
            raise RuntimeError(
                f"{model_name} produces {dim}-dim vectors but case_embeddings is vector({EMBEDDING_DIM})"
            )

    def encode(self, text: str) -> list[float]:
        return self.encode_many([text])[0]

    def encode_many(self, texts: Sequence[str]) -> list[list[float]]:
        """Normalised embeddings, so cosine distance and inner product agree."""
        if not texts:
            return []
        vectors = self._model.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
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
