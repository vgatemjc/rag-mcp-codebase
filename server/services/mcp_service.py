from __future__ import annotations

import importlib
import inspect
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from mcp.types import TextContent


class MCPService:
    """Thin wrapper to inspect and invoke MCP tools defined in git_rag_mcp."""

    def __init__(self, module_path: str = "server.git_rag_mcp") -> None:
        self.module_path = module_path
        self._module = None

    def _load_module(self):
        if self._module is None:
            self._module = importlib.import_module(self.module_path)
        return self._module

    def _annotation_name(self, annotation: Any) -> Optional[str]:
        if annotation is inspect.Signature.empty or annotation is None:
            return None
        if isinstance(annotation, str):
            return annotation
        return getattr(annotation, "__name__", str(annotation))

    def _serialize_tool(self, name: str, func: Any, description: Optional[str] = None) -> Dict[str, Any]:
        desc = description or ""
        target_func = func
        if not target_func and hasattr(func, "fn"):
            target_func = getattr(func, "fn")
        if not desc and target_func and target_func.__doc__:
            desc = target_func.__doc__.strip().splitlines()[0]

        parameters: List[Dict[str, Any]] = []
        if target_func:
            real_func = getattr(target_func, "__wrapped__", target_func)
            sig = inspect.signature(real_func)
            for param in sig.parameters.values():
                if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                    continue
                parameters.append(
                    {
                        "name": param.name,
                        "required": param.default is inspect.Signature.empty,
                        "default": None if param.default is inspect.Signature.empty else param.default,
                        "annotation": self._annotation_name(param.annotation),
                    }
                )

        return {"name": name, "description": desc, "parameters": parameters}

    def list_tools(self) -> List[Dict[str, Any]]:
        module = self._load_module()
        tools: List[Dict[str, Any]] = []

        tool_manager = getattr(getattr(module, "mcp", None), "_tool_manager", None)
        if tool_manager and hasattr(tool_manager, "_tools"):
            for name, tool in tool_manager._tools.items():
                func = getattr(tool, "func", None) or getattr(tool, "fn", None)
                tools.append(self._serialize_tool(name, func, getattr(tool, "description", None)))

        if not tools:
            for name, func in inspect.getmembers(module, inspect.iscoroutinefunction):
                if getattr(func, "__wrapped__", None) is None:
                    continue
                tools.append(self._serialize_tool(name, func))

        deduped = []
        seen = set()
        for tool in tools:
            if tool["name"] in seen:
                continue
            seen.add(tool["name"])
            deduped.append(tool)
        return deduped

    def _resolve_tool(self, name: str):
        module = self._load_module()
        tool_manager = getattr(getattr(module, "mcp", None), "_tool_manager", None)
        if tool_manager and hasattr(tool_manager, "_tools") and name in tool_manager._tools:
            tool = tool_manager._tools[name]
            func = getattr(tool, "func", None) or getattr(tool, "fn", None)
            if func:
                return func

        func = getattr(module, name, None)
        if func and inspect.iscoroutinefunction(func):
            return func
        if func and inspect.isfunction(func) and inspect.iscoroutinefunction(getattr(func, "__wrapped__", func)):
            return getattr(func, "__wrapped__", func)
        raise ValueError(f"Tool '{name}' not found")

    def _extract_text(self, result: Any) -> Optional[str]:
        if result is None:
            return None
        if isinstance(result, TextContent):
            return result.text
        if isinstance(result, bytes):
            return result.decode("utf-8", errors="ignore")
        if isinstance(result, str):
            return result
        return str(result)

    def _safe_json(self, value: Any) -> Any:
        if isinstance(value, TextContent):
            return {"type": value.type, "text": value.text}
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        if isinstance(value, dict):
            return {k: self._safe_json(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._safe_json(item) for item in value]
        return repr(value)

    def _parse_json_text(self, value: Optional[str]) -> Any:
        if not value or not isinstance(value, str):
            return None
        try:
            return json.loads(value)
        except Exception:
            return None

    async def invoke_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        func = self._resolve_tool(name)
        real_func = getattr(func, "__wrapped__", func)
        sig = inspect.signature(real_func)
        normalized_args = args or {}
        if "repo_id" in sig.parameters and "repo" in normalized_args and "repo_id" not in normalized_args:
            normalized_args = {**normalized_args, "repo_id": normalized_args.get("repo")}
        accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values())
        filtered_args = normalized_args if accepts_kwargs else {k: v for k, v in normalized_args.items() if k in sig.parameters}
        try:
            bound = sig.bind(**filtered_args)
        except TypeError as exc:
            raise ValueError(f"Invalid arguments for tool '{name}': {exc}") from exc
        bound.apply_defaults()

        started_at = datetime.utcnow()
        result = await func(*bound.args, **bound.kwargs)
        finished_at = datetime.utcnow()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        content_type = None
        if isinstance(result, TextContent):
            content_type = result.type or "text"
        text_out = self._extract_text(result)
        raw_result = self._safe_json(result)
        parsed_json = raw_result if isinstance(raw_result, (dict, list)) else self._parse_json_text(text_out)

        return {
            "tool": name,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "output_text": text_out,
            "raw_result": raw_result,
            "parsed_json": parsed_json,
            "content_type": content_type or "text",
            "stdout": text_out,
            "stderr": None,
            "success": True,
        }
