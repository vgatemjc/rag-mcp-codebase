from pathlib import Path

import pytest

from server.config import Config
from server.services.datastore_reset import DatastoreResetService


class DummyRegistry:
    def __init__(self, collections, db_path=None):
        self.collections = collections
        self.reinitialized = False
        self.db_path = db_path

    def list_repositories(self, include_archived: bool = False):
        return [type("Repo", (), {"collection_name": name}) for name in self.collections]

    def reinitialize(self):
        self.reinitialized = True


class DummyQdrantClient:
    def __init__(self):
        self.deleted = []

    def delete_collection(self, collection_name: str):
        self.deleted.append(collection_name)


class DummyInitializer:
    def __init__(self, qdrant_client):
        self.qdrant_client = qdrant_client
        self.reset_called = False

    def _qdrant(self):
        return self.qdrant_client

    def reset(self):
        self.reset_called = True


def test_datastore_reset_clears_initializer_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOST_REPO_PATH", str(tmp_path))
    cfg = Config()
    cfg.ALLOW_DATA_RESET = True
    cfg.QDRANT_STORAGE_PATH = tmp_path / "rag-db"
    cfg.QDRANT_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "registry.db"
    db_path.write_text("temp", encoding="utf-8")
    cfg.REGISTRY_DB_PATH = db_path

    registry = DummyRegistry(collections=["demo-collection"], db_path=db_path)
    qdrant_client = DummyQdrantClient()
    initializer = DummyInitializer(qdrant_client)

    service = DatastoreResetService(cfg, registry, initializer)
    result = service.reset()

    assert result["registry_db"]["removed"] is True
    assert "demo-collection" in result["qdrant"]["target_collections"]
    assert initializer.reset_called is True
    assert registry.reinitialized is True
