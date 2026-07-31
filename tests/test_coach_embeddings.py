from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from scout.sub_agents.coach import embeddings


class _FakeEncoded:
    def __init__(self, values: list[float]):
        self._values = values

    def tolist(self) -> list[float]:
        return self._values


class _FakeModel:
    instances = 0

    def __init__(self, name: str):
        _FakeModel.instances += 1
        self.name = name

    def encode(self, text, normalize_embeddings: bool = True):
        self.calls = getattr(self, "calls", 0) + 1
        if isinstance(text, str):
            return _FakeEncoded([0.1] * 384)
        return _FakeEncoded([[0.1] * 384 for _ in text])


def test_embed_returns_384_dim_list(monkeypatch):
    _FakeModel.instances = 0
    embeddings._model = None
    monkeypatch.setattr(embeddings, "SentenceTransformer", _FakeModel)
    result = embeddings.embed("a summary")
    assert len(result) == 384
    assert all(isinstance(x, float) for x in result)


def test_embed_loads_model_once(monkeypatch):
    _FakeModel.instances = 0
    embeddings._model = None
    monkeypatch.setattr(embeddings, "SentenceTransformer", _FakeModel)
    embeddings.embed("first")
    embeddings.embed("second")
    assert _FakeModel.instances == 1


class _SlowFakeModel:
    """A model whose construction takes long enough for a second thread to
    observe `_model is None` and start constructing too."""

    instances = 0
    _lock = threading.Lock()

    def __init__(self, name: str):
        time.sleep(0.05)
        with _SlowFakeModel._lock:
            _SlowFakeModel.instances += 1
        self.name = name

    def encode(self, text, normalize_embeddings: bool = True):
        if isinstance(text, str):
            return _FakeEncoded([0.1] * 384)
        return _FakeEncoded([[0.1] * 384 for _ in text])


def test_the_model_is_loaded_once_under_concurrent_callers(monkeypatch):
    """Observed in production, not hypothesised.

    Two of 755 candidates died on `NotImplementedError: Cannot copy out of meta
    tensor; no data!` in the very first chunk of the first concurrent
    aggregation run. Lazy init was unguarded, so several threads all saw
    `_model is None` and all began constructing — and sentence-transformers'
    meta-tensor device init does not survive that.

    Serial ingest could never expose it. Concurrent ingest hits it on the first
    chunk of every cold process, and `embed_many` shares the same path, so the
    retriever was exposed too.
    """
    _SlowFakeModel.instances = 0
    embeddings._model = None
    monkeypatch.setattr(embeddings, "SentenceTransformer", _SlowFakeModel)

    with ThreadPoolExecutor(max_workers=4) as pool:
        vectors = list(pool.map(lambda _: embeddings.embed("a summary"), range(4)))

    assert _SlowFakeModel.instances == 1, "the model was constructed more than once"
    assert all(len(vector) == 384 for vector in vectors)


def test_embed_many_returns_one_vector_per_text(monkeypatch):
    _FakeModel.instances = 0
    embeddings._model = None
    monkeypatch.setattr(embeddings, "SentenceTransformer", _FakeModel)
    result = embeddings.embed_many(["kubernetes", "react", "postgresql"])
    assert len(result) == 3
    assert all(len(vector) == 384 for vector in result)


def test_embed_many_uses_a_single_encode_call(monkeypatch):
    """The retriever has a whole run's skills at once; one call amortises the
    per-call overhead that N separate encodes would pay."""
    _FakeModel.instances = 0
    embeddings._model = None
    monkeypatch.setattr(embeddings, "SentenceTransformer", _FakeModel)
    embeddings.embed_many(["kubernetes", "react", "postgresql"])
    assert embeddings._model.calls == 1


def test_embed_many_of_nothing_does_not_touch_the_model(monkeypatch):
    _FakeModel.instances = 0
    embeddings._model = None
    monkeypatch.setattr(embeddings, "SentenceTransformer", _FakeModel)
    assert embeddings.embed_many([]) == []
    assert _FakeModel.instances == 0
