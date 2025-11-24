from __future__ import annotations

from typing import List

from pydantic import BaseModel


class StatusResponse(BaseModel):
    modified: List[str]
    added: List[str]
    deleted: List[str]
    renamed: List[str]
