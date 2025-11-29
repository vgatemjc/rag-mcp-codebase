import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient


class DummyQdrant:
    def __init__(self):
        self.deleted = []

    def delete_collection(self, collection_name: str):
        self.deleted.append(collection_name)

    def get_collections(self):
        return type("Resp", (), {"collections": []})()


def build_client(tmp_path, monkeypatch, allow_reset: bool = True):
    db_dir = tmp_path / "registry"
    storage_dir = tmp_path / "rag-db"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REGISTRY_DB_DIR", str(db_dir))
    monkeypatch.setenv("QDRANT_STORAGE_PATH", str(storage_dir))
    monkeypatch.setenv("HOST_REPO_PATH", str(tmp_path))
    monkeypatch.setenv("SKIP_COLLECTION_INIT", "1")
    if allow_reset:
        monkeypatch.setenv("ALLOW_DATA_RESET", "1")
    else:
        monkeypatch.delenv("ALLOW_DATA_RESET", raising=False)
    module = importlib.import_module("server.git_rag_api")
    module = importlib.reload(module)
    app = module.app
    dummy_qdrant = DummyQdrant()
    app.state.initializer._qdrant_admin = dummy_qdrant
    return TestClient(app), app, dummy_qdrant, storage_dir


def test_datastore_reset_requires_guard(tmp_path, monkeypatch):
    client, _, _, _ = build_client(tmp_path, monkeypatch, allow_reset=False)
    resp = client.request(
        "DELETE",
        "/registry/datastores",
        data=json.dumps({"confirm": "delete"}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_datastore_reset_drops_registry_and_qdrant(tmp_path, monkeypatch):
    client, app, dummy_qdrant, storage_dir = build_client(tmp_path, monkeypatch, allow_reset=True)

    payload = {
        "repo_id": "sample",
        "collection_name": "sample-collection",
        "embedding_model": "demo-model",
    }
    create_resp = client.post("/registry", json=payload)
    assert create_resp.status_code == 200

    registry_db_path = Path(app.state.registry.db_path)
    assert registry_db_path.exists()
    (storage_dir / "tmp.txt").write_text("wipe-me")

    resp = client.request(
        "DELETE",
        "/registry/datastores",
        data=json.dumps({"confirm": "delete"}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["registry_db"]["removed"] is True
    assert data["qdrant"]["target_collections"] == ["sample-collection"]
    assert dummy_qdrant.deleted == ["sample-collection"]
    assert data["qdrant"]["storage_removed"] is True
    assert registry_db_path.exists() is False
    assert list(storage_dir.iterdir()) == []
