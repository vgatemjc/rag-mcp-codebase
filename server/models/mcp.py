from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MCPToolParameter(BaseModel):
    name: str
    required: bool = False
    default: Any = None
    annotation: Optional[str] = None


class MCPTool(BaseModel):
    name: str
    description: Optional[str] = None
    parameters: List[MCPToolParameter] = Field(default_factory=list)


class MCPInvokeRequest(BaseModel):
    args: Dict[str, Any] = Field(default_factory=dict)


class MCPInvokeResponse(BaseModel):
    tool: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    output_text: Optional[str] = None
    raw_result: Any = None
