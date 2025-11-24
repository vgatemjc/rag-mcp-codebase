from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


def load_state(state_file: Path) -> Dict[str, str]:
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {}


def save_state(state_file: Path, state: Dict[str, str]) -> None:
    state_file.write_text(json.dumps(state))


def sync_state_with_registry(state_file: Path, repo_id: str, last_indexed_commit: str | None) -> None:
    if not last_indexed_commit:
        return
    state = load_state(state_file)
    if state.get(repo_id) == last_indexed_commit:
        return
    state[repo_id] = last_indexed_commit
    save_state(state_file, state)


def list_git_repositories(repos_dir: Path) -> List[str]:
    repos: List[str] = []
    if not repos_dir.exists():
        return repos
    for entry in repos_dir.iterdir():
        if entry.is_dir() and (entry / ".git").exists():
            repos.append(entry.name)
    return repos


def get_repo_path(repos_dir: Path, repo_id: str) -> Path:
    repo_path = repos_dir / repo_id
    if not repo_path.exists() or not (repo_path / ".git").exists():
        raise ValueError(f"Invalid repo: {repo_id}")
    return repo_path
