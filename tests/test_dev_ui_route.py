import os

from fastapi.testclient import TestClient

from server.app import create_app


def test_dev_ui_route(monkeypatch, tmp_path):
    monkeypatch.setenv("SKIP_COLLECTION_INIT", "1")
    monkeypatch.setenv("REGISTRY_DB_DIR", str(tmp_path))
    app = create_app()
    client = TestClient(app)

    resp = client.get("/dev-ui")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
