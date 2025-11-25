from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Optional

import pytest
import requests

# Default targets for live API hits; integration tests can override via env.
DEFAULT_API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DEFAULT_BRANCH = os.getenv("GIT_BRANCH", "head")


def _run_git(repo_path: Path, *args: str) -> str:
    """Run a git command in the given repository and return stdout."""
    return (
        subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
    )


@dataclass
class GitRepo:
    """Lightweight helper for arranging test repositories."""

    repo_id: str
    path: Path
    branch: str = DEFAULT_BRANCH

    def init(self) -> "GitRepo":
        self.path.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", str(self.path)],
            check=True,
        )
        _run_git(self.path, "init", "-b", self.branch)
        _run_git(self.path, "config", "user.email", "test@example.com")
        _run_git(self.path, "config", "user.name", "Test User")
        return self

    def write(self, rel_path: str, content: str) -> Path:
        target = self.path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return target

    def commit_all(self, message: str) -> str:
        _run_git(self.path, "add", ".")
        _run_git(self.path, "commit", "-m", message)
        return _run_git(self.path, "rev-parse", "HEAD")

    def checkout(self, *paths: str) -> None:
        _run_git(self.path, "checkout", "--", *paths)


def consume_streaming_json(response: requests.Response) -> Dict[str, Any]:
    """Read a StreamingResponse (event stream style) and return the final JSON object."""
    last_line: Optional[str] = None
    for line in response.iter_lines():
        if not line:
            continue
        decoded = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else str(line)
        last_line = decoded
    if not last_line:
        raise AssertionError("No streaming payload received from response")
    return json.loads(last_line)


@pytest.fixture
def temp_env(monkeypatch, tmp_path) -> SimpleNamespace:
    """Isolate registry DB, repos, and state file paths for a test."""
    root = tmp_path
    repos_dir = root / "repos"
    registry_dir = root / "registry"
    state_file = root / "index_state.json"

    repos_dir.mkdir(parents=True, exist_ok=True)
    registry_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("REPOS_DIR", str(repos_dir))
    monkeypatch.setenv("REGISTRY_DB_DIR", str(registry_dir))
    monkeypatch.setenv("STATE_FILE", str(state_file))
    monkeypatch.setenv("GIT_BRANCH", DEFAULT_BRANCH)

    return SimpleNamespace(
        repos_dir=repos_dir,
        registry_dir=registry_dir,
        state_file=state_file,
    )


@pytest.fixture
def git_repo(temp_env) -> GitRepo:
    """Create and initialize a fresh git repo under the temp REPOS_DIR."""
    repo = GitRepo(repo_id="test_repo", path=temp_env.repos_dir / "test_repo")
    repo.init()
    return repo


@pytest.fixture
def api_request() -> Callable[..., Any]:
    """
    Requests-backed API helper.

    Usage:
        api_request("post", "/repos/…/index/full", json={…}, stream=True)
    """

    session = requests.Session()
    base_url = DEFAULT_API_BASE_URL.rstrip("/")

    def _request(
        method: str,
        path: str,
        *,
        stream: bool = False,
        timeout: int = 30,
        **kwargs: Any,
    ):
        url = f"{base_url}{path}"
        response = session.request(method, url, stream=stream, timeout=timeout, **kwargs)
        response.raise_for_status()
        if stream:
            return consume_streaming_json(response)
        return response.json()

    return _request
