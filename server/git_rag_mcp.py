import asyncio
import os
import json
import numpy as np
import httpx
from fastmcp import FastMCP
from mcp.types import TextContent
from importlib.metadata import version as get_version  # 버전 정보를 가져오기 위한 import
import sys, logging
import pathlib
import asyncio
import re

# CHANGED: repo2md_ts 모듈을 직접 임포트하여 function call 방식으로 사용합니다.
#         (프로세스 호출이 아님)
try:
    from services import repo2md_ts as r2m  # type: ignore
except ImportError:  # 실행 경로에 따라 server 패키지 경로가 필요할 수 있음
    from server.services import repo2md_ts as r2m  # type: ignore

# 강제로 stdout 플러시
print(">>> TEST PRINT <<<", flush=True)

# 로거 재구성
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger(__name__)
logger.info(">>> TEST LOGGER <<<")
logger = logging.getLogger(__name__)

# ----------------------
# 환경 변수 설정
# ----------------------
RAG_URL = os.getenv("RAG_URL", "http://localhost:8000")
REPO_ROOT = os.getenv("REPO_ROOT", "/workspace/myrepo")
MCP_PORT = int(os.getenv("MCP_PORT", "8083"))

# ---- **추가: 런타임 FastMCP 버전 확인** ----
try:
    MCP_VERSION = get_version("mcp")
except Exception:
    MCP_VERSION = "unknown"

logger.info(f"Loaded FastMCP Version: {MCP_VERSION}")
# -----------------------------------------------

# 1. MCP 인스턴스 초기화
mcp = FastMCP("rag-mcp")

logger.info(dir(mcp))

# ----------------------
# MCP 도구 정의
# ----------------------

import os
import re
from typing import List

@mcp.tool()
async def search_code(query: str, k: int = 8, repo: str | None = None):
    """
    Search the codebase that match
    the given `query` using grep-like keyword search. Each result contains:

      * A location string (``repo/path#line``)
      * The matched line identifier
      * A similarity score (fixed at 1.0 for matches)
      * The snippet text (line with context)

    Parameters
    ----------
    query : str
        Text describing what you’re looking for (case-insensitive substring match).
    k : int, optional
        Number of top results to return (default 8).
    repo : str | None, optional
        Restrict the search to a particular repository ID. If omitted,
        all repositories indexed under REPO_ROOT are searched.

    Returns
    -------
    TextContent
        A formatted string containing one block per result, suitable for
        display or further processing by the LLM.
    """
    logger.info(f"called search_code : {query}")
    try:
        # Determine repos to search
        if repo:
            repos = [repo]
        else:
            repos = [d for d in os.listdir(REPO_ROOT) if os.path.isdir(os.path.join(REPO_ROOT, d))]
        
        formatted_results: List[str] = []
        search_count = 0
        
        # Simple regex for code files (extend as needed)
        code_file_pattern = re.compile(r'\.(py|js|java|c|cpp|h|ts|jsx|html|css|json|md|txt)$', re.IGNORECASE)
        
        for repo_name in repos:
            if search_count >= k:
                break
            repo_root = os.path.join(REPO_ROOT, repo_name)
            if not os.path.exists(repo_root):
                continue
            
            for root, dirs, files in os.walk(repo_root):
                if search_count >= k:
                    break
                for filename in files:
                    if search_count >= k:
                        break
                    if not code_file_pattern.search(filename):
                        continue
                    
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, repo_root)
                    
                    try:
                        with open(full_path, "r", errors="ignore") as f:
                            lines = f.readlines()
                        
                        query_lower = query.lower()
                        for line_num, line in enumerate(lines, 1):
                            if search_count >= k:
                                break
                            if query_lower in line.lower():
                                # Extract snippet with 1 line context before/after
                                start_line = max(0, line_num - 2)
                                end_line = min(len(lines), line_num + 1)
                                snippet_lines = lines[start_line:end_line]
                                code_snippet = ''.join(snippet_lines).rstrip()
                                
                                # Simple symbol extraction: look for nearest def/class/function
                                symbol_match = re.search(r'(def|class|function)\s+(\w+)', code_snippet)
                                symbol = symbol_match.group(2) if symbol_match else f"line_{line_num}"
                                
                                location = f"{repo_name}/{rel_path}#{line_num}"
                                score_str = "score=1.0000"  # Fixed score for grep match
                                
                                formatted_results.append(
                                    f"{location}\n{symbol}\n{score_str}\n\n{code_snippet}\n{'-'*60}\n"
                                )
                                search_count += 1
                    except Exception as file_e:
                        logger.warning(f"Error reading {full_path}: {str(file_e)}")
                        continue
        
        if not formatted_results:
            return TextContent(type="text", text="No matches found for the query.")
        
        logger.info(f"found {len(formatted_results)} results")
        return TextContent(type="text", text="".join(formatted_results))
    except Exception as e:
        logger.error(f"Error in search_code: {str(e)}")
        return TextContent(type="text", text=f"Error: {str(e)}")

@mcp.tool()
async def semantic_code_search(
    query: str,
    k: int = 8,
    repo: str | None = None,
    stack_type: str | None = None,
    component_type: str | None = None,
    screen_name: str | None = None,
    tags: list[str] | None = None,
):
    """
    Search the codebase for the *k* most semantically relevant snippets that match
    the given `query`. The request is forwarded to the RAG service and each result
    contains:

      * A location string (``repo/path#symbol:start-end``)
      * The matched symbol name
      * A similarity score
      * The snippet text (either from the RAG payload or read directly from disk)

    Parameters
    ----------
    query : str
        Text describing what you’re looking for.
    k : int, optional
        Number of top results to return (default 8).
    repo : str | None, optional
        Restrict the search to a particular repository ID. If omitted,
        all repositories indexed by the RAG server are searched.
    stack_type : str | None, optional
        Optional stack hint (e.g., "android_app") to scope plugin filters.
    component_type : str | None, optional
        Filter to a specific component type when the stack supports it.
    screen_name : str | None, optional
        Filter to a particular screen/view name when provided by the stack plugin.
    tags : list[str] | None, optional
        Filter by any matching tag attached to chunks (e.g., "layout", "navgraph").

    Returns
    -------
    TextContent
        A formatted string containing one block per result, suitable for
        display or further processing by the LLM.
    """
    logger.info(f"called search_code : {query}")
    try:
        payload = {"query": query, "repo_id": repo, "k": k}
        if stack_type:
            payload["stack_type"] = stack_type
        if component_type:
            payload["component_type"] = component_type
        if screen_name:
            payload["screen_name"] = screen_name
        if tags:
            payload["tags"] = tags
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{RAG_URL}/search",
                json=payload,
            )
            resp.raise_for_status()
            results = resp.json()

        formatted_results = []
        for r in results:
            payload = r["payload"]
            repo_name = payload.get('repo', repo or 'unknown')
            path = payload.get("path", "unknown")
            symbol = payload.get("symbol", "unknown")
            lines = payload.get("lines", [0, 0])
            start, end = lines[0], lines[1]
            score = r.get("score", 0.0)
            
            # Use focus_text from payload (chunk content) if available, else fallback to reading file
            code_snippet = payload.get("focus_text", None)
            if not code_snippet:
                try:
                    full_path = os.path.join(REPO_ROOT, repo_name, path)
                    if os.path.exists(full_path):
                        with open(full_path, "r", errors="ignore") as f:
                            content = f.read()
                        actual_lines = content.splitlines(True)[start-1:end]  # 1-based, inclusive
                        code_snippet = ''.join(actual_lines).rstrip()
                    else:
                        code_snippet = f"File not found: {full_path}"
                except Exception as e:
                    code_snippet = f"Error reading file: {str(e)}"
            
            location = f"{repo_name}/{path}#{symbol}:{start}-{end}"
            score_str = f"score={score:.4f}"
            
            formatted_results.append(
                f"{location}\n{symbol}\n{score_str}\n\n{code_snippet}\n{'-'*60}\n"
            )
        logger.info(f"result {formatted_results}")
        return TextContent(type="text", text="".join(formatted_results))
    except Exception as e:
        return TextContent(type="text", text=f"Error: {str(e)}")

@mcp.tool()
async def list_functions(repo: str):
    """
    Retrieve a plain‑text list of every top‑level function and class method
    defined in the specified `repo`. The search uses a generic function‑
    detection query and returns entries in the form:

        path:start-end  function_or_class_name

    Parameters
    ----------
    repo : str
        Repository ID to scan.

    Returns
    -------
    TextContent
        One line per symbol, sorted by file and line numbers.
    """
    logger.info(f"called list_functions : {repo}")
    try:
        # Use a broad query to retrieve function/class chunks semantically
        query = "functions classes methods definitions code"
        k = 10000  # Large k to aim for all relevant chunks
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{RAG_URL}/search",
                json={"query": query, "repo_id": repo, "k": k}
            )
            resp.raise_for_status()
            results = resp.json()

        # Filter for function and class symbols
        items = []
        for r in results:
            payload = r["payload"]
            symbol = payload.get("symbol", "")
            if symbol.startswith(("func:", "class:")):
                path = payload.get("path", "unknown")
                lines = payload.get("lines", [0, 0])
                start, end = lines[0], lines[1]
                name = symbol.split(":", 1)[1] if ":" in symbol else symbol
                items.append(f"{path}:{start}-{end} {name}")

        logger.info(f"result {items}")
        return TextContent(type="text", text="\n".join(items))
    except Exception as e:
        return TextContent(type="text", text=f"Error: {str(e)}")


@mcp.tool()
async def retrieve_snippet(repo: str, file: str, start: int, end: int):
    """
    Pull the exact source code from `file` in `repo` between line `start`
    and line `end` (inclusive). Lines are 1‑based and the function
    silently truncates if the file or range does not exist.

    Parameters
    ----------
    repo : str
        Repository ID where the file resides.
    file : str
        Path to the file relative to the repository root.
    start : int
        1‑based starting line number.
    end : int
        1‑based ending line number.

    Returns
    -------
    TextContent
        The raw snippet text or an error message.
    """
    logger.info(f"called retrieve_snippet : {repo} {file} {start}-{end}")
    try:
        path = os.path.join(REPO_ROOT, repo, file)
        if not os.path.exists(path):
            return TextContent(type="text", text=f"not found: {path}")
        with open(path, "r", errors="ignore") as f:
            lines = f.readlines()[start - 1:end]

        logger.info(f"result {lines}")
        return TextContent(type="text", text="".join(lines))
    except Exception as e:
        return TextContent(type="text", text=f"Error: {str(e)}")


@mcp.tool()
async def analyze_issue(question: str, repo: str | None = None, k: int = 16):
    """
    Given an issue description or bug report in `question`, return the
    *k* most relevant code regions that might be related to the problem.
    The output is a JSON array where each entry contains:

      * file : path to the file
      * start : starting line number
      * end   : ending line number
      * score : similarity score from the RAG model

    Parameters
    ----------
    question : str
        Natural‑language description of the problem.
    repo : str | None, optional
        Restrict the search to a single repository. If omitted,
        all indexed repositories are considered.
    k : int, optional
        Number of candidate regions to return (default 16).

    Returns
    -------
    TextContent
        JSON‑formatted list of candidate locations.
    """
    logger.info(f"called analyze_issue : {question}")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{RAG_URL}/search",
                json={"query": question, "repo_id": repo, "k": k}
            )
            resp.raise_for_status()
            results = resp.json()

        items = []
        for r in results:
            payload = r["payload"]
            items.append({
                "file": payload.get("path", "unknown"),
                "start": payload.get("lines", [0, 0])[0],
                "end": payload.get("lines", [0, 0])[1],
                "score": r.get("score", 0.0)
            })

        logger.info(f"result {items}")
        return TextContent(type="text", text=json.dumps(items, ensure_ascii=False, indent=2))
    except Exception as e:
        return TextContent(type="text", text=f"Error: {str(e)}")

# CHANGED: repo_tree_md를 repo_id 기반으로 사용하도록 변경
@mcp.tool()
async def repo_tree_md(
    repo_id: str,               # ✅ path 삭제 → repo_id만 받도록 변경
    depth: int = 3, 
    max_lines: int = 10
):
    """
    Generate a Markdown report of the repository using repo_id, matching RAG server path rules.

    Parameters
    ----------
    repo_id : str
        Repository name (same as RAG server's /workspace/myrepo/<repo_id>)
    depth : int
        Tree/definition depth (0~3)
    max_lines : int
        Max snippet lines for depth >= 3
    """

    logger.info(f"repo_tree_md called repo_id={repo_id} depth={depth}")

    # ✅ RAG 서버와 동일한 repo root 사용
    # CHANGED: path = Path("/workspace/myrepo") / repo_id
    base_root = pathlib.Path("/workspace/myrepo")     # ✅ RAG server constant
    repo_path = base_root / repo_id                  # ✅ repo_id 기반으로 통합

    # ✅ repo validation (RAG API와 동일한 체크)
    # CHANGED: .git 확인
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return TextContent(
            type="text",
            text=f"Invalid repo_id: {repo_id} (path: {repo_path})"
        )

    # ✅ 기존 walk_repo 호출 방식 그대로 (function call 방식)
    md = await asyncio.to_thread(
        r2m.walk_repo,
        repo_path,
        int(depth),
        int(max_lines)
    )

    # (Optional) 너무 큰 결과 truncate
    if len(md) > 800000:
        md = md[:800000] + "\n\n[TRUNCATED: output > 800KB]"

    return TextContent(type="text", text=md)

@mcp.tool()
async def list_mcp_tools():
    """
    Return a newline-separated list of available MCP tool names and short descriptions
    where possible. This helps an LLM know what actions the MCP server supports.
    """
    import sys, inspect
    logger.info("called list_mcp_tools")

    try:
        tools = []

        # ✅ FastMCP 2.12.5: 정확한 registry
        try:
            tool_mgr = getattr(mcp, "_tool_manager", None)
            if tool_mgr and hasattr(tool_mgr, "_tools"):
                for name, tool in tool_mgr._tools.items():
                    # ✅ FastMCP stores the description here
                    desc = tool.description or ""
                    if not desc:
                        # fallback: check function docstring
                        func = getattr(tool, "func", None)
                        if func and func.__doc__:
                            desc = func.__doc__.strip().splitlines()[0]

                    tools.append(f"{name} : {desc}")
        except Exception as e:
            logger.warning(f"Tool list from tool_manager failed: {e}")

        # ✅ fallback: 모듈 introspection
        this_mod = sys.modules[__name__]
        for name, obj in inspect.getmembers(this_mod, inspect.iscoroutinefunction):
            if getattr(obj, "__wrapped__", None) is not None:
                desc = obj.__doc__.strip().splitlines()[0] if obj.__doc__ else ""
                tools.append(f"{name} : {desc}")

        # ✅ dedup
        seen = set()
        out = []
        for t in tools:
            if t not in seen:
                seen.add(t)
                out.append(t)

        return TextContent(type="text", text="\n".join(out))

    except Exception as e:
        logger.exception("list_mcp_tools error")
        return TextContent(type="text", text=f"Error: {str(e)}")

if __name__ == "__main__":
    logger.info("🚀 Starting MCP 2.0.0 server with HTTP transport...")
    asyncio.run(mcp.run_async(transport="http", host="0.0.0.0", port=8083))
