from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import threading

from sqlmodel import SQLModel, Field, Session, create_engine, select


class Repository(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    repo_id: str = Field(index=True, unique=True)
    name: str
    url: Optional[str] = None
    stack_type: Optional[str] = Field(default=None, index=True)
    collection_name: str
    embedding_model: str
    last_indexed_commit: Optional[str] = None
    last_indexed_at: Optional[datetime] = None
    last_index_mode: Optional[str] = None
    last_index_status: Optional[str] = None
    last_index_error: Optional[str] = None
    last_index_started_at: Optional[datetime] = None
    last_index_finished_at: Optional[datetime] = None
    last_index_total_files: Optional[int] = None
    last_index_processed_files: Optional[int] = None
    last_index_current_file: Optional[str] = None
    archived: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class Sandbox(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    repo_id: str = Field(foreign_key="repository.repo_id", index=True)
    user_id: str
    created_by: Optional[str] = None
    path: str
    status: str = Field(default="ready")
    auto_sync: bool = Field(default=False)
    parent_commit: Optional[str] = None
    upstream_url: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class Report(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    repo_id: str = Field(foreign_key="repository.repo_id")
    query: str
    path: str
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class RepositoryRegistry:
    """Lightweight SQLModel-backed registry for repositories, sandboxes, and reports."""

    def __init__(self, db_url: Optional[str] = None, db_path: Optional[Path] = None, db_dir: Optional[Path] = None):
        self.db_path = self._resolve_db_path(db_url=db_url, db_path=db_path, db_dir=db_dir)
        engine_url = db_url
        if not engine_url:
            if not self.db_path:
                raise ValueError("Unable to resolve registry database path.")
            engine_url = f"sqlite:///{self.db_path.as_posix()}"
        self._engine_url = engine_url
        self._connect_args = {"check_same_thread": False}
        self.engine = create_engine(self._engine_url, connect_args=self._connect_args)
        SQLModel.metadata.create_all(self.engine)
        self._ensure_schema()
        self._lock = threading.Lock()

    def _resolve_db_path(self, *, db_url: Optional[str], db_path: Optional[Path], db_dir: Optional[Path]) -> Optional[Path]:
        if db_path:
            resolved = Path(db_path).expanduser()
        elif db_url and db_url.startswith("sqlite:///"):
            resolved = Path(db_url.replace("sqlite:///", "")).expanduser()
        else:
            explicit_path = os.getenv("REGISTRY_DB_PATH")
            if explicit_path:
                resolved = Path(explicit_path).expanduser()
            else:
                base_dir = Path(
                    db_dir
                    or os.getenv("REGISTRY_DB_DIR")
                    or (os.getenv("HOST_REPO_PATH") or "/workspace/myrepo") + "/registry_db"
                )
                base_dir.mkdir(parents=True, exist_ok=True)
                resolved = base_dir / "registry.db"
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    def reinitialize(self) -> None:
        """Recreate engine after on-disk reset to ensure new DB file is used."""
        with self._lock:
            try:
                self.engine.dispose()
            except Exception:
                pass
            self.engine = create_engine(self._engine_url, connect_args=self._connect_args)
            SQLModel.metadata.create_all(self.engine)
            self._ensure_schema()

    def _with_session(self):
        return Session(self.engine)

    def _ensure_schema(self) -> None:
        """Best-effort schema alignment for existing SQLite registries."""
        if self.engine.url.get_backend_name() != "sqlite":
            return
        with self.engine.begin() as conn:
            result = conn.exec_driver_sql("PRAGMA table_info(repository)")
            existing_cols = {row[1] for row in result.fetchall()}
            desired = {
                "last_indexed_at": "DATETIME",
                "last_index_mode": "VARCHAR(50)",
                "last_index_status": "VARCHAR(50)",
                "last_index_error": "TEXT",
                "last_index_started_at": "DATETIME",
                "last_index_finished_at": "DATETIME",
                "last_index_total_files": "INTEGER",
                "last_index_processed_files": "INTEGER",
                "last_index_current_file": "TEXT",
                "stack_type": "VARCHAR(100)",
            }
            for col, ddl in desired.items():
                if col not in existing_cols:
                    conn.exec_driver_sql(f"ALTER TABLE repository ADD COLUMN {col} {ddl}")

    def list_repositories(self, include_archived: bool = False) -> List[Repository]:
        with self._with_session() as session:
            statement = select(Repository)
            if not include_archived:
                statement = statement.where(Repository.archived == False)  # noqa: E712
            return list(session.exec(statement).all())

    def get_repository(self, repo_id: str) -> Optional[Repository]:
        with self._with_session() as session:
            statement = select(Repository).where(Repository.repo_id == repo_id)
            return session.exec(statement).first()

    def ensure_repository(self, repo_id: str, defaults: Optional[Dict[str, str]] = None) -> Repository:
        defaults = defaults or {}
        with self._lock:
            repo = self.get_repository(repo_id)
            if repo:
                return repo
            repo = Repository(
                repo_id=repo_id,
                name=defaults.get("name") or repo_id,
                url=defaults.get("url"),
                stack_type=defaults.get("stack_type"),
                collection_name=defaults.get("collection_name") or defaults.get("collection") or "git_rag-default",
                embedding_model=defaults.get("embedding_model") or defaults.get("model") or "text-embedding-3-large",
                last_indexed_commit=defaults.get("last_indexed_commit"),
            )
            with self._with_session() as session:
                session.add(repo)
                session.commit()
                session.refresh(repo)
                return repo

    def create_repository(self, data: Dict[str, Optional[str]]) -> Repository:
        with self._lock:
            existing = self.get_repository(data["repo_id"])
            if existing:
                raise ValueError(f"Repository {data['repo_id']} already exists")
            repo = Repository(
                repo_id=data["repo_id"],
                name=data.get("name") or data["repo_id"],
                url=data.get("url"),
                stack_type=data.get("stack_type"),
                collection_name=data.get("collection_name") or data.get("collection") or "git_rag-default",
                embedding_model=data.get("embedding_model") or data.get("model") or "text-embedding-3-large",
                last_indexed_commit=data.get("last_indexed_commit"),
            )
            with self._with_session() as session:
                session.add(repo)
                session.commit()
                session.refresh(repo)
                return repo

    def update_repository(self, repo_id: str, data: Dict[str, Optional[str]]) -> Repository:
        with self._lock:
            with self._with_session() as session:
                repo = session.exec(select(Repository).where(Repository.repo_id == repo_id)).first()
                if not repo:
                    raise ValueError(f"Repository {repo_id} not found")
                updated = False
                for field, value in data.items():
                    if value is None:
                        continue
                    if hasattr(repo, field):
                        setattr(repo, field, value)
                        updated = True
                if data.get("archived") is not None:
                    repo.archived = bool(data["archived"])
                    updated = True
                if updated:
                    repo.updated_at = datetime.utcnow()
                session.add(repo)
                session.commit()
                session.refresh(repo)
                return repo

    def archive_repository(self, repo_id: str, archived: bool = True) -> Repository:
        return self.update_repository(repo_id, {"archived": archived})

    def delete_repository(self, repo_id: str) -> None:
        with self._lock:
            with self._with_session() as session:
                repo = session.exec(select(Repository).where(Repository.repo_id == repo_id)).first()
                if not repo:
                    return
                session.delete(repo)
                session.commit()

    def update_last_indexed_commit(self, repo_id: str, commit_sha: str) -> None:
        self.update_index_status(repo_id, last_indexed_commit=commit_sha, status="completed")

    def update_index_status(
        self,
        repo_id: str,
        *,
        last_indexed_commit: Optional[str] = None,
        status: Optional[str] = None,
        mode: Optional[str] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        error: Optional[str] = None,
        total_files: Optional[int] = None,
        processed_files: Optional[int] = None,
        current_file: Optional[str] = None,
    ) -> None:
        with self._lock:
            with self._with_session() as session:
                repo = session.exec(select(Repository).where(Repository.repo_id == repo_id)).first()
                if not repo:
                    return
                now = datetime.utcnow()
                if last_indexed_commit is not None:
                    repo.last_indexed_commit = last_indexed_commit
                if mode is not None:
                    repo.last_index_mode = mode
                if status is not None:
                    repo.last_index_status = status
                if started_at is not None:
                    repo.last_index_started_at = started_at
                if finished_at is not None:
                    repo.last_index_finished_at = finished_at
                    repo.last_indexed_at = finished_at
                if error is not None:
                    repo.last_index_error = error
                if total_files is not None:
                    repo.last_index_total_files = total_files
                if processed_files is not None:
                    repo.last_index_processed_files = processed_files
                if current_file is not None:
                    repo.last_index_current_file = current_file
                repo.updated_at = now
                session.add(repo)
                session.commit()

    def handle_webhook(self, action: str, payload: Dict[str, Optional[str]]) -> Optional[Repository]:
        action = action.lower()
        if action == "push":
            defaults = {
                "name": payload.get("name") or payload["repo_id"],
                "url": payload.get("url"),
                "stack_type": payload.get("stack_type"),
                "collection_name": payload.get("collection_name"),
                "embedding_model": payload.get("embedding_model"),
            }
            return self.ensure_repository(payload["repo_id"], defaults)
        if action == "archive":
            return self.archive_repository(payload["repo_id"], archived=True)
        if action == "delete":
            self.delete_repository(payload["repo_id"])
            return None
        raise ValueError(f"Unsupported webhook action: {action}")

    def list_sandboxes(self, repo_id: str) -> List[Sandbox]:
        with self._with_session() as session:
            statement = select(Sandbox).where(Sandbox.repo_id == repo_id)
            return list(session.exec(statement).all())

    def list_all_sandboxes(self) -> List[Sandbox]:
        with self._with_session() as session:
            statement = select(Sandbox)
            return list(session.exec(statement).all())

    def get_sandbox(self, sandbox_id: int, repo_id: Optional[str] = None) -> Optional[Sandbox]:
        with self._with_session() as session:
            statement = select(Sandbox).where(Sandbox.id == sandbox_id)
            if repo_id:
                statement = statement.where(Sandbox.repo_id == repo_id)
            return session.exec(statement).first()

    def create_sandbox(self, data: Dict[str, Any]) -> Sandbox:
        with self._lock:
            sandbox = Sandbox(
                repo_id=data["repo_id"],
                user_id=data["user_id"],
                created_by=data.get("created_by") or data["user_id"],
                path=data["path"],
                status=data.get("status") or "ready",
                auto_sync=bool(data.get("auto_sync", False)),
                parent_commit=data.get("parent_commit"),
                upstream_url=data.get("upstream_url"),
                last_synced_at=data.get("last_synced_at"),
                last_checked_at=data.get("last_checked_at"),
            )
            with self._with_session() as session:
                session.add(sandbox)
                session.commit()
                session.refresh(sandbox)
                return sandbox

    def update_sandbox(self, sandbox_id: int, data: Dict[str, Any], repo_id: Optional[str] = None) -> Sandbox:
        with self._lock:
            with self._with_session() as session:
                statement = select(Sandbox).where(Sandbox.id == sandbox_id)
                if repo_id:
                    statement = statement.where(Sandbox.repo_id == repo_id)
                sandbox = session.exec(statement).first()
                if not sandbox:
                    raise ValueError(f"Sandbox {sandbox_id} not found")
                updated = False
                custom_updated_at = data.get("updated_at")
                for field, value in data.items():
                    if value is None or not hasattr(sandbox, field):
                        continue
                    setattr(sandbox, field, value)
                    updated = True
                if updated:
                    sandbox.updated_at = custom_updated_at or datetime.utcnow()
                session.add(sandbox)
                session.commit()
                session.refresh(sandbox)
                return sandbox

    def delete_sandbox(self, sandbox_id: int, repo_id: Optional[str] = None) -> None:
        with self._lock:
            with self._with_session() as session:
                statement = select(Sandbox).where(Sandbox.id == sandbox_id)
                if repo_id:
                    statement = statement.where(Sandbox.repo_id == repo_id)
                sandbox = session.exec(statement).first()
                if not sandbox:
                    return
                session.delete(sandbox)
                session.commit()
