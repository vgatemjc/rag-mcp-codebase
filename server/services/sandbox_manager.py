from __future__ import annotations

import subprocess
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from server.services.git_aware_code_indexer import GitCLI
from server.services.state_manager import get_repo_path
from server.services.repository_registry import Sandbox, RepositoryRegistry


@dataclass
class SandboxEvent:
    action: str
    repo_id: str
    sandbox_id: Optional[int] = None
    user_id: Optional[str] = None
    details: Optional[Dict[str, str]] = None


class SandboxManager:
    """Manage Git worktrees for per-user sandboxes."""

    def __init__(self, repos_dir: Path, default_branch: str):
        self.repos_dir = repos_dir
        self.default_branch = default_branch
        self._subscribers: List[Callable[[SandboxEvent], None]] = []

    def subscribe(self, handler: Callable[[SandboxEvent], None]) -> None:
        """Register a handler to receive sandbox lifecycle events."""
        self._subscribers.append(handler)

    def _emit(self, event: SandboxEvent) -> None:
        for handler in self._subscribers:
            try:
                handler(event)
            except Exception:
                # Events should not break callers; ignore subscriber failures.
                continue

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

    def record_creation(self, sandbox: Sandbox) -> None:
        """Emit a creation event after the registry row is written."""
        self._emit(
            SandboxEvent(
                action="created",
                repo_id=sandbox.repo_id,
                sandbox_id=sandbox.id,
                user_id=sandbox.user_id,
                details={"path": sandbox.path, "parent_commit": sandbox.parent_commit or ""},
            )
        )

    def fast_forward_worktree(self, sandbox_path: Path, target_commit: str) -> None:
        """Move a sandbox worktree to the target commit."""
        subprocess.check_output(
            ["git", "checkout", target_commit],
            cwd=sandbox_path,
            stderr=subprocess.STDOUT,
            timeout=60,
        )

    def prune_sandbox(self, registry: RepositoryRegistry, sandbox: Sandbox, reason: str = "ttl_expired") -> None:
        """Remove a sandbox worktree and delete it from the registry."""
        repo_path = get_repo_path(self.repos_dir, sandbox.repo_id)
        target = Path(sandbox.path)
        try:
            subprocess.check_output(
                ["git", "worktree", "remove", "--force", str(target)],
                cwd=repo_path,
                stderr=subprocess.STDOUT,
                timeout=60,
            )
        except subprocess.CalledProcessError:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
        registry.delete_sandbox(sandbox.id, repo_id=sandbox.repo_id)
        self._emit(
            SandboxEvent(
                action="pruned",
                repo_id=sandbox.repo_id,
                sandbox_id=sandbox.id,
                user_id=sandbox.user_id,
                details={"reason": reason},
            )
        )

    def refresh_sandboxes(
        self,
        registry: RepositoryRegistry,
        ttl_hours: int = 72,
    ) -> Dict[str, List[int]]:
        """
        Background maintenance: mark stale sandboxes, fast-forward auto-sync sandboxes,
        and prune abandoned ones past the TTL.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=ttl_hours)
        summary: Dict[str, List[int]] = {"stale": [], "fast_forwarded": [], "pruned": []}

        for repo in registry.list_repositories(include_archived=True):
            repo_path = get_repo_path(self.repos_dir, repo.repo_id)
            if not repo_path.exists():
                continue
            git = GitCLI(str(repo_path))
            repo_head = git.get_head()
            for sandbox in registry.list_sandboxes(repo.repo_id):
                sandbox_path = Path(sandbox.path)
                if sandbox.updated_at < cutoff or not sandbox_path.exists():
                    reason = "ttl_expired" if sandbox.updated_at < cutoff else "missing_path"
                    self.prune_sandbox(registry, sandbox, reason=reason)
                    summary["pruned"].append(sandbox.id)
                    continue

                updates: Dict[str, Optional[object]] = {"last_checked_at": now}
                try:
                    sandbox_head = GitCLI(str(sandbox_path)).get_head()
                except Exception:
                    sandbox_head = sandbox.parent_commit

                baseline_commit = sandbox.parent_commit or sandbox_head
                if baseline_commit and baseline_commit != repo_head:
                    if sandbox.auto_sync:
                        try:
                            self.fast_forward_worktree(sandbox_path, repo_head)
                            updates.update(
                                {
                                    "parent_commit": repo_head,
                                    "status": "ready",
                                    "last_synced_at": now,
                                }
                            )
                            summary["fast_forwarded"].append(sandbox.id)
                            self._emit(
                                SandboxEvent(
                                    action="fast_forward",
                                    repo_id=sandbox.repo_id,
                                    sandbox_id=sandbox.id,
                                    user_id=sandbox.user_id,
                                    details={"target": repo_head},
                                )
                            )
                        except Exception:
                            updates["status"] = "sync_failed"
                    else:
                        updates["status"] = "stale"
                        summary["stale"].append(sandbox.id)
                        self._emit(
                            SandboxEvent(
                                action="stale",
                                repo_id=sandbox.repo_id,
                                sandbox_id=sandbox.id,
                                user_id=sandbox.user_id,
                                details={
                                    "parent_commit": sandbox.parent_commit or "",
                                    "head_commit": repo_head,
                                },
                            )
                        )

                if set(updates.keys()) == {"last_checked_at"}:
                    updates["updated_at"] = sandbox.updated_at
                registry.update_sandbox(sandbox.id, updates, repo_id=sandbox.repo_id)

        return summary
