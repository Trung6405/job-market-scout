from __future__ import annotations

import threading

from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"
_model: SentenceTransformer | None = None
_model_lock = threading.Lock()


def _get_model() -> SentenceTransformer:
    """The lazily-loaded model, constructed exactly once.

    The lock is not defensive programming — it fixes an observed production
    failure. Callers reach this from worker threads (`asyncio.to_thread`), and
    once ingest became concurrent, several threads saw ``_model is None`` at
    the same moment and all began constructing. sentence-transformers
    initialises on a meta device and moves the weights across, so the losers of
    that race raise ``NotImplementedError: Cannot copy out of meta tensor``.
    That cost two candidates in the first chunk of the first concurrent run.

    Re-checked inside the lock: without that, every thread queued at the lock
    would construct in turn, which is the same bug taking longer.
    """
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer(_MODEL_NAME)
    return _model


def embed(text: str) -> list[float]:
    return _get_model().encode(text, normalize_embeddings=True).tolist()


def embed_many(texts: list[str]) -> list[list[float]]:
    """Embed several texts in one encode call, preserving input order.

    The retriever has a whole run's distinct gap skills available at once, so
    it can amortise per-call overhead instead of paying it per skill. Returns
    vectors positionally aligned with ``texts`` — the retriever pairs them
    with skill names by index, so order is load-bearing.
    """
    if not texts:
        return []
    return _get_model().encode(texts, normalize_embeddings=True).tolist()
