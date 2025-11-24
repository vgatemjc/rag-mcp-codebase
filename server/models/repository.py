from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class RepositoryIn(BaseModel):
    repo_id: str
    name: Optional[str] = None
    url: Optional[str] = None
    collection_name: Optional[str] = None
    embedding_model: Optional[str] = None
    last_indexed_commit: Optional[str] = None


class RepositoryUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    collection_name: Optional[str] = None
    embedding_model: Optional[str] = None
    last_indexed_commit: Optional[str] = None
    archived: Optional[bool] = None


class RepositoryOut(BaseModel):
    repo_id: str
    name: str
    url: Optional[str] = None
    collection_name: str
    embedding_model: str
    last_indexed_commit: Optional[str] = None
    archived: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RegistryWebhook(BaseModel):
    action: Literal["push", "archive", "delete"]
    repo_id: str
    name: Optional[str] = None
    url: Optional[str] = None
    collection_name: Optional[str] = None
    embedding_model: Optional[str] = None
