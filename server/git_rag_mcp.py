import asyncio
import os
import json
import numpy as np
import httpx
from fastmcp import FastMCP
from mcp.types import TextContent
from importlib.metadata import version as get_version  # 버전 정보를 가져오기 위한 import
import sys, logging

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


# ----------------------
# MCP 도구 정의
# ----------------------

@mcp.tool()
async def search_code(query: str, k: int = 8, repo: str | None = None):
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

    Returns
    -------
    TextContent
        A formatted string containing one block per result, suitable for
        display or further processing by the LLM.
    """
    logger.info(f"called search_code : {query}")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{RAG_URL}/search",
                json={"query": query, "repo_id": repo, "k": k}
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

if __name__ == "__main__":
    logger.info("🚀 Starting MCP 2.0.0 server with HTTP transport...")
    asyncio.run(mcp.run_async(transport="http", host="0.0.0.0", port=8083))