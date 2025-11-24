from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from server.config import Config
from server.routers.index_router import _ensure_repo_registry_entry


class _StubRegistry:
    def __init__(self, archived: bool = False):
        self.archived = archived
        self.calls = []

    def ensure_repository(self, repo_id, defaults):
        self.calls.append((repo_id, defaults))
        return SimpleNamespace(
            repo_id=repo_id,
            name=defaults["name"],
            collection_name=defaults["collection_name"],
            embedding_model=defaults["embedding_model"],
            archived=self.archived,
            last_indexed_commit=None,
        )


def _make_request(config: Config, registry: _StubRegistry):
    state = SimpleNamespace(config=config, registry=registry)
    app = SimpleNamespace(state=state)
    return SimpleNamespace(app=app)


def test_registry_entry_defaults_used(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EMB_MODEL", "demo-model")
    config = Config(ENV="test", EMB_MODEL="demo-model")
    registry = _StubRegistry()
    request = _make_request(config, registry)

    repo = _ensure_repo_registry_entry(request, "sample-repo")

    assert registry.calls == [
        (
            "sample-repo",
            {
                "name": "sample-repo",
                "collection_name": config.COLLECTION,
                "embedding_model": "demo-model",
            },
        )
    ]
    assert repo.collection_name == config.COLLECTION
    assert repo.embedding_model == "demo-model"
    assert repo.archived is False


def test_registry_archived_rejected(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    config = Config()
    registry = _StubRegistry(archived=True)
    request = _make_request(config, registry)

    with pytest.raises(HTTPException) as excinfo:
        _ensure_repo_registry_entry(request, "archived-repo")

    assert excinfo.value.status_code == 400
    assert "archived" in excinfo.value.detail
