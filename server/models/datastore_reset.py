from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class DatastoreResetRequest(BaseModel):
    confirm: str


class RegistryResetResult(BaseModel):
    path: Optional[str] = None
    removed: bool = False
    status: Optional[str] = None
    message: Optional[str] = None


class QdrantResetResult(BaseModel):
    url: Optional[str] = None
    target_collections: List[str] = Field(default_factory=list)
    dropped: List[str] = Field(default_factory=list)
    failed: Dict[str, str] = Field(default_factory=dict)
    storage_path: Optional[str] = None
    storage_removed: bool = False
    storage_message: Optional[str] = None
    connect_error: Optional[str] = None


class DatastoreResetResponse(BaseModel):
    registry_db: RegistryResetResult
    qdrant: QdrantResetResult
