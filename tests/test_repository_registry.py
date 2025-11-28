from datetime import datetime

import importlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.services.repository_registry import RepositoryRegistry


def test_repository_registry_crud(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'registry.db'}"
    registry = RepositoryRegistry(db_url=db_url)

    repo = registry.ensure_repository(
        "demo",
        {
            "name": "Demo Repo",
            "stack_type": "android_app",
            "collection_name": "demo-collection",
            "embedding_model": "demo-model",
        },
    )
    assert repo.repo_id == "demo"
    assert repo.collection_name == "demo-collection"
    assert repo.embedding_model == "demo-model"
    assert repo.stack_type == "android_app"

    updated = registry.update_repository("demo", {"name": "Updated Demo", "stack_type": "web"})
    assert updated.name == "Updated Demo"
    assert updated.stack_type == "web"

    registry.update_last_indexed_commit("demo", "abc123")
    refreshed = registry.get_repository("demo")
    assert refreshed.last_indexed_commit == "abc123"
    assert refreshed.last_index_status == "completed"

    registry.archive_repository("demo", archived=True)
    archived = registry.get_repository("demo")
    assert archived.archived is True

    now = datetime.utcnow()
    registry.update_index_status("demo", status="running", mode="full", started_at=now)
    refreshed = registry.get_repository("demo")
    assert refreshed.last_index_status == "running"
    assert refreshed.last_index_mode == "full"
    assert refreshed.last_index_total_files is None

    registry.update_index_status(
        "demo",
        status="running",
        mode="full",
        started_at=now,
        total_files=10,
        processed_files=2,
        current_file="demo.py",
    )
    refreshed = registry.get_repository("demo")
    assert refreshed.last_index_total_files == 10
    assert refreshed.last_index_processed_files == 2
    assert refreshed.last_index_current_file == "demo.py"

    registry.delete_repository("demo")
    assert registry.get_repository("demo") is None


def test_registry_router_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("REGISTRY_DB_DIR", str(tmp_path))
    monkeypatch.setenv("SKIP_COLLECTION_INIT", "1")
    module = importlib.import_module("server.git_rag_api")
    module = importlib.reload(module)
    client = TestClient(module.app)

    payload = {
        "repo_id": "sample",
        "name": "Sample Repo",
        "collection_name": "sample-collection",
        "embedding_model": "sample-model",
        "stack_type": "android_app",
    }
    resp = client.post("/registry", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["repo_id"] == "sample"
    assert data["stack_type"] == "android_app"

    resp = client.get("/registry/sample")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Sample Repo"

    resp = client.put("/registry/sample", json={"archived": True})
    assert resp.status_code == 200
    assert resp.json()["archived"] is True

    resp = client.get("/repos/sample/index/status")
    assert resp.status_code == 200
    status = resp.json()
    assert status["repo_id"] == "sample"
    assert status["last_indexed_commit"] is None
    assert status["last_index_total_files"] is None
    assert status["last_index_processed_files"] is None

    webhook_payload = {
        "action": "push",
        "repo_id": "webhook-repo",
        "name": "Webhook Repo",
    }
    resp = client.post("/registry/webhook", json=webhook_payload)
    assert resp.status_code == 200
    assert resp.json()["repo_id"] == "webhook-repo"

    resp = client.delete("/registry/sample")
    assert resp.status_code == 204
