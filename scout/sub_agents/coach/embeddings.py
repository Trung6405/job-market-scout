from __future__ import annotations

from sentence_transformers import SentenceTransformer

_MODEL_NAME = "all-MiniLM-L6-v2"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
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
