from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Tuple

from server.services.git_aware_code_indexer import GitCLI
from server.services.state_manager import get_repo_path


class SandboxManager:
    """Manage Git worktrees for per-user sandboxes."""

    def __init__(self, repos_dir: Path, default_branch: str):
        self.repos_dir = repos_dir
        self.default_branch = default_branch

    def sandbox_path(self, repo_id: str, user_id: str) -> Path:
        repo_path = get_repo_path(self.repos_dir, repo_id)
        return repo_path / "users" / user_id

    def ensure_worktree(self, repo_id: str, user_id: str) -> Tuple[Path, str]:
        """
        Create (or return) a worktree for the given user.
        Returns the worktree path and the parent commit SHA it was based on.
        """
        repo_path = get_repo_path(self.repos_dir, repo_id)
        target = repo_path / "users" / user_id
        target.parent.mkdir(parents=True, exist_ok=True)

        git = GitCLI(str(repo_path))
        parent_commit = git.get_head()

        if target.exists():
            if not (target / ".git").exists():
                raise RuntimeError(f"Sandbox path already exists and is not a git repo: {target}")
            return target, parent_commit

        try:
            subprocess.check_output(
                ["git", "worktree", "add", "--detach", str(target), self.default_branch],
                cwd=repo_path,
                stderr=subprocess.STDOUT,
                timeout=60,
            )
        except subprocess.CalledProcessError as exc:
            output = exc.output.decode("utf-8", errors="ignore") if exc.output else ""
            raise RuntimeError(f"Failed to create worktree for repo '{repo_id}': {output}") from exc

        return target, parent_commit
