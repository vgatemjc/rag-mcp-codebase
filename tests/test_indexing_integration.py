from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from tests.rag_test_utils import GitRepo, consume_streaming_json

pytestmark = pytest.mark.integration


@pytest.fixture
def client(temp_env):
    """Spin up the FastAPI app with temp env overrides for repos/state/registry."""
    from server.config import Config

    cfg = Config(REPOS_DIR=temp_env.repos_dir, STATE_FILE=temp_env.state_file)
    app = create_app(cfg)
    with TestClient(app) as client:
        yield client


def _register_repo(client: TestClient, repo_id: str):
    cfg = client.app.state.config
    payload = {
        "repo_id": repo_id,
        "name": repo_id,
        "collection_name": cfg.COLLECTION,
        "embedding_model": cfg.EMB_MODEL,
    }
    response = client.post("/registry", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _stream_index(client: TestClient, path: str):
    with client.stream("POST", path) as response:
        response.raise_for_status()
        return consume_streaming_json(response)


def test_full_commit_and_working_tree_flow(client: TestClient, git_repo: GitRepo, temp_env):
    repo_id = git_repo.repo_id
    _register_repo(client, repo_id)

    # Initial commit with file_a.py
    git_repo.write("file_a.py", "def initialize_context():\n    return 'context initialized'\n")
    initial_commit = git_repo.commit_all("Initial commit: initialize_context")

    full_result = _stream_index(client, f"/repos/{repo_id}/index/full")
    assert full_result["status"] == "completed"
    assert full_result["last_commit"] == initial_commit

    state = json.loads(temp_env.state_file.read_text())
    assert state.get(repo_id) == initial_commit

    search_result = client.post(
        "/search",
        json={"query": "initialize context function", "repo_id": repo_id, "k": 1},
    )
    assert search_result.status_code == 200
    hits = search_result.json()
    assert hits and "file_a.py" in hits[0]["payload"]["path"]

    # Commit-based incremental index
    git_repo.write(
        "file_a.py",
        "def initialize_context():\n    return 'new context initialized'\n\n"
        "def setup_db():\n    pass\n",
    )
    git_repo.write("file_b.py", "class Controller: pass\n")
    new_commit = git_repo.commit_all("Update A and Add B")
    assert new_commit != initial_commit

    update_result = _stream_index(client, f"/repos/{repo_id}/index/update")
    assert update_result["status"] == "completed"
    assert update_result["last_commit"] == new_commit

    controller_search = client.post(
        "/search",
        json={"query": "Controller class definition", "repo_id": repo_id, "k": 1},
    )
    assert controller_search.status_code == 200
    controller_hits = controller_search.json()
    assert controller_hits and "file_b.py" in controller_hits[0]["payload"]["path"]

    noop_result = _stream_index(client, f"/repos/{repo_id}/index/update")
    assert noop_result["status"] == "noop"

    # Working-tree incremental index
    git_repo.write("file_b.py", "class Controller:\n    def run(self):\n        pass\n")
    status = client.get(f"/repos/{repo_id}/status")
    assert status.status_code == 200
    assert "file_b.py" in status.json().get("modified", [])

    local_update = _stream_index(client, f"/repos/{repo_id}/index/update")
    assert local_update["status"] == "completed"
    assert local_update["last_commit"] == new_commit

    run_search = client.post(
        "/search",
        json={"query": "Controller run method", "repo_id": repo_id, "k": 1},
    )
    assert run_search.status_code == 200
    run_hits = run_search.json()
    assert run_hits and "file_b.py" in run_hits[0]["payload"]["path"]

    git_repo.checkout("file_b.py")
    clean_status = client.get(f"/repos/{repo_id}/status").json()
    assert "file_b.py" not in clean_status.get("modified", [])

    local_noop = _stream_index(client, f"/repos/{repo_id}/index/update")
    assert local_noop["status"] == "noop"
