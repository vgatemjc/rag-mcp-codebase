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
    """Searches the entire codebase for the 'k' most semantically similar code snippets to the given query.
    
    The result is returned as a list of text strings, including the code's location information (e.g., 'repo/path#symbol:start-end'), similarity score, symbol, and the actual code snippet (chunk content).
    The search scope can be narrowed by specifying a particular 'repo'.
    This tool is used to identify the approximate location of relevant code.
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
    """Returns a list of all top-level functions and class methods contained within the specified repository ('repo').
    
    The result is a list of text strings including the file location (e.g., 'file:start-end') and the name of each function.
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
    """Retrieves and returns the exact code content as text, spanning from the 'start' line to the 'end' line within a specific file ('file') of the given repository ('repo').
    
    This tool is used to convert location information obtained from 'search_code' or 'list_functions' into the concrete code content.
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
    """Searches for the 'k' most relevant code regions that might be the source of a problem, based on an issue description or bug report ('question').
    
    The result is returned as a **JSON array** containing the **file name, start line, end line, and similarity score**.
    (e.g., [{"file": "...", "start": 10, "end": 20, "score": 0.85}])
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