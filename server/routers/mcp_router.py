from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Request

from server.config import Config
from server.models.mcp import MCPInvokeRequest, MCPInvokeResponse, MCPTool
from server.services.mcp_service import MCPService

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _config(request: Request) -> Config:
    return request.app.state.config


def _mcp_service(request: Request) -> MCPService:
    service: MCPService | None = getattr(request.app.state, "mcp_service", None)
    if not service:
        raise HTTPException(status_code=503, detail="MCP service is disabled.")
    return service


@router.get("/tools", response_model=List[MCPTool])
def list_tools(request: Request):
    if not _config(request).EXPOSE_MCP_UI:
        raise HTTPException(status_code=404, detail="MCP endpoints are disabled.")
    service = _mcp_service(request)
    return service.list_tools()


@router.post("/tools/{tool_name}", response_model=MCPInvokeResponse)
async def invoke_tool(tool_name: str, payload: MCPInvokeRequest, request: Request):
    if not _config(request).EXPOSE_MCP_UI:
        raise HTTPException(status_code=404, detail="MCP endpoints are disabled.")
    service = _mcp_service(request)
    try:
        return await service.invoke_tool(tool_name, payload.args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
