import importlib

from fastapi.testclient import TestClient


def build_client(tmp_path, monkeypatch):
    monkeypatch.setenv("REGISTRY_DB_DIR", str(tmp_path))
    monkeypatch.setenv("SKIP_COLLECTION_INIT", "1")
    module = importlib.import_module("server.git_rag_api")
    module = importlib.reload(module)
    return TestClient(module.app), module.app.state.config


def test_registry_ui_endpoints(tmp_path, monkeypatch):
    client, cfg = build_client(tmp_path, monkeypatch)

    resp = client.get("/registry/ui")
    assert resp.status_code == 200
    assert "/static/registry_ui/app.js" in resp.text

    meta = client.get("/registry/ui/meta").json()
    assert meta["config"]["collection"] == cfg.COLLECTION
    assert meta["config"]["embedding_model"] == cfg.EMB_MODEL
    assert isinstance(meta.get("embedding_options"), list)
    assert isinstance(meta.get("qdrant_collections"), list)

    preview = client.post("/registry/preview", json={"repo_id": "demo"}).json()
    assert preview["target"] == "/registry"
    assert preview["payload"]["collection_name"] == cfg.COLLECTION
    assert preview["payload"]["embedding_model"] == cfg.EMB_MODEL

    # Ensure preview did not persist.
    registry = client.get("/registry").json()
    assert registry == []
