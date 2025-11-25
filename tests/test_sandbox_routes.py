from __future__ import annotations

import importlib
from datetime import datetime, timedelta
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
from sqlmodel import select

from server.services.repository_registry import Sandbox
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


def test_sandbox_metadata_and_events(temp_env, git_repo: GitRepo, monkeypatch):
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

    events = []
    client.app.state.sandbox_manager.subscribe(events.append)

    sandbox_resp = client.post(
        f"/registry/{git_repo.repo_id}/sandboxes",
        json={"user_id": "alice", "created_by": "ci-bot", "auto_sync": False, "status": "ready"},
    )
    assert sandbox_resp.status_code == 200, sandbox_resp.text
    sandbox_data = sandbox_resp.json()
    assert sandbox_data["created_by"] == "ci-bot"
    repo_head = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=git_repo.path, text=True).strip()
    )
    assert sandbox_data["parent_commit"] == repo_head
    assert events and events[0].action == "created"

    # Upstream branch moves forward; sandbox should be marked stale.
    git_repo.write("CHANGELOG.md", "update\n")
    new_head = git_repo.commit_all("upstream change")
    summary = client.app.state.sandbox_manager.refresh_sandboxes(client.app.state.registry, ttl_hours=48)
    assert sandbox_data["id"] in summary["stale"]

    refreshed = client.get(f"/registry/{git_repo.repo_id}/sandboxes").json()[0]
    assert refreshed["status"] == "stale"
    assert refreshed["parent_commit"] == parent_commit
    assert refreshed["last_checked_at"] is not None

    stale_events = [e for e in events if e.action == "stale"]
    assert stale_events and stale_events[-1].details["head_commit"] == new_head


def test_auto_sync_and_prune_sandboxes(temp_env, git_repo: GitRepo, monkeypatch):
    git_repo.write("README.md", "# Demo\n")
    git_repo.commit_all("init sandbox repo")

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

    events = []
    client.app.state.sandbox_manager.subscribe(events.append)

    sandbox_resp = client.post(
        f"/registry/{git_repo.repo_id}/sandboxes",
        json={"user_id": "bob", "auto_sync": True},
    )
    assert sandbox_resp.status_code == 200, sandbox_resp.text
    sandbox_data = sandbox_resp.json()

    # Create a new upstream commit; auto-sync sandbox should fast-forward.
    git_repo.write("main.py", "print('hi')\n")
    new_head = git_repo.commit_all("upstream change")
    summary = client.app.state.sandbox_manager.refresh_sandboxes(client.app.state.registry, ttl_hours=72)
    assert sandbox_data["id"] in summary["fast_forwarded"]

    refreshed = client.get(f"/registry/{git_repo.repo_id}/sandboxes").json()[0]
    assert refreshed["parent_commit"] == new_head
    assert refreshed["status"] == "ready"
    assert refreshed["last_synced_at"] is not None

    # Add a second sandbox and age it past the TTL to force pruning.
    sandbox_resp_2 = client.post(
        f"/registry/{git_repo.repo_id}/sandboxes",
        json={"user_id": "charlie", "auto_sync": False},
    )
    sandbox_data_2 = sandbox_resp_2.json()
    registry = client.app.state.registry
    with registry._with_session() as session:
        sb_row = session.exec(select(Sandbox).where(Sandbox.id == sandbox_data_2["id"])).first()
        sb_row.updated_at = datetime.utcnow() - timedelta(hours=200)
        session.add(sb_row)
        session.commit()

    summary = client.app.state.sandbox_manager.refresh_sandboxes(registry, ttl_hours=24)
    assert sandbox_data_2["id"] in summary["pruned"]

    remaining = client.get(f"/registry/{git_repo.repo_id}/sandboxes").json()
    assert all(sbx["id"] != sandbox_data_2["id"] for sbx in remaining)

    pruned_events = [e for e in events if e.action == "pruned"]
    assert pruned_events and pruned_events[-1].details["reason"] in {"ttl_expired", "missing_path"}
