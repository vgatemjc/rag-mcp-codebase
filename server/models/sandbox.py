from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class SandboxCreate(BaseModel):
    user_id: str
    created_by: Optional[str] = None
    auto_sync: bool = False
    status: Optional[str] = None


class SandboxUpdate(BaseModel):
    status: Optional[str] = None
    auto_sync: Optional[bool] = None
    parent_commit: Optional[str] = None
    upstream_url: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None


class SandboxOut(BaseModel):
    id: int
    repo_id: str
    user_id: str
    created_by: Optional[str] = None
    path: str
    status: str
    auto_sync: bool
    parent_commit: Optional[str] = None
    upstream_url: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
