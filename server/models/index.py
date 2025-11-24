from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


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
