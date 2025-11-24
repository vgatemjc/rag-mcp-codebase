from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import threading

from sqlmodel import SQLModel, Field, Session, create_engine, select


class Repository(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    repo_id: str = Field(index=True, unique=True)
    name: str
    url: Optional[str] = None
    collection_name: str
    embedding_model: str
    last_indexed_commit: Optional[str] = None
    archived: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class Sandbox(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    repo_id: str = Field(foreign_key="repository.repo_id")
    user_id: str
    path: str
    status: str = Field(default="ready")
    auto_sync: bool = Field(default=False)
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

    def __init__(self, db_url: Optional[str] = None):
        db_file = db_url
        if not db_file:
            base_dir = Path(os.getenv("REGISTRY_DB_DIR") or Path(__file__).resolve().parent)
            base_dir.mkdir(parents=True, exist_ok=True)
            db_file = f"sqlite:///{(base_dir / 'registry.db').as_posix()}"
        self.engine = create_engine(db_file, connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        self._lock = threading.Lock()

    def _with_session(self):
        return Session(self.engine)

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
        with self._lock:
            with self._with_session() as session:
                repo = session.exec(select(Repository).where(Repository.repo_id == repo_id)).first()
                if not repo:
                    return
                repo.last_indexed_commit = commit_sha
                repo.updated_at = datetime.utcnow()
                session.add(repo)
                session.commit()

    def handle_webhook(self, action: str, payload: Dict[str, Optional[str]]) -> Optional[Repository]:
        action = action.lower()
        if action == "push":
            defaults = {
                "name": payload.get("name") or payload["repo_id"],
                "url": payload.get("url"),
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
