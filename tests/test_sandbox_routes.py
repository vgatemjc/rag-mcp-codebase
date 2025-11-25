from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient

from tests.rag_test_utils import GitRepo


def test_create_list_update_sandbox(temp_env, git_repo: GitRepo, monkeypatch):
    git_repo.write("README.md", "# Demo\n")
    parent_commit = git_repo.commit_all("init sandbox repo")

    monkeypatch.setenv("SKIP_COLLECTION_INIT", "1")
    module = importlib.import_module("server.git_rag_api")
    module = importlib.reload(module)
    client = TestClient(module.app)

    cfg = client.app.state.config
    create_repo_resp = client.post(
        "/registry",
        json={
            "repo_id": git_repo.repo_id,
            "name": "Sandbox Repo",
            "url": "https://example.com/sandbox.git",
            "collection_name": cfg.COLLECTION,
            "embedding_model": cfg.EMB_MODEL,
        },
    )
    assert create_repo_resp.status_code == 200, create_repo_resp.text

    sandbox_resp = client.post(
        f"/registry/{git_repo.repo_id}/sandboxes",
        json={"user_id": "alice", "auto_sync": True},
    )
    assert sandbox_resp.status_code == 200, sandbox_resp.text
    sandbox_data = sandbox_resp.json()
    sandbox_path = Path(sandbox_data["path"])
    assert sandbox_path.exists()
    assert (sandbox_path / ".git").exists()
    assert sandbox_data["parent_commit"] == parent_commit
    assert sandbox_data["upstream_url"] == "https://example.com/sandbox.git"

    list_resp = client.get(f"/registry/{git_repo.repo_id}/sandboxes")
    assert list_resp.status_code == 200
    sandboxes = list_resp.json()
    assert len(sandboxes) == 1
    assert sandboxes[0]["user_id"] == "alice"

    update_resp = client.patch(
        f"/registry/{git_repo.repo_id}/sandboxes/{sandbox_data['id']}",
        json={"status": "dirty", "auto_sync": False},
    )
    assert update_resp.status_code == 200, update_resp.text
    updated = update_resp.json()
    assert updated["status"] == "dirty"
    assert updated["auto_sync"] is False
