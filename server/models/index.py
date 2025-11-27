from __future__ import annotations

from typing import Optional
from datetime import datetime

from pydantic import BaseModel
from pydantic import ConfigDict


class IndexResponse(BaseModel):
    status: str
    message: str
    last_commit: Optional[str] = None


class IndexProgress(BaseModel):
    status: str
    message: str
    file: Optional[str] = None
    total_files: Optional[int] = None
    processed_files: Optional[int] = None
    last_commit: Optional[str] = None


class IndexStatus(BaseModel):
    repo_id: str
    last_indexed_commit: Optional[str] = None
    last_indexed_at: Optional[datetime] = None
    last_index_mode: Optional[str] = None
    last_index_status: Optional[str] = None
    last_index_error: Optional[str] = None
    last_index_started_at: Optional[datetime] = None
    last_index_finished_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
