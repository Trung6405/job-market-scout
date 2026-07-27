from __future__ import annotations

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

    def encode(self, text: str, normalize_embeddings: bool = True):
        return _FakeEncoded([0.1] * 384)


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
