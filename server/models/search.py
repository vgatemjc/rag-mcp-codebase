from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    repo_id: Optional[str] = None
    k: int = 5
    stack_type: Optional[str] = None
    component_type: Optional[str] = None
    screen_name: Optional[str] = None
    tags: Optional[List[str]] = None
