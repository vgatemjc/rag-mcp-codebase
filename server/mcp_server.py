import asyncio
import os
import json
import numpy as np
import httpx
from fastapi import FastAPI
#from mcp.server.fastmcp import FastMCP
from fastmcp import FastMCP
from mcp.types import TextContent
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from importlib.metadata import version as get_version # 버전 정보를 가져오기 위한 import
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
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
TEI_URL = os.getenv("TEI_URL", "http://tei:80")
CODE_COL = os.getenv("COLLECTION_CODE", "code_chunks")
FUNC_COL = os.getenv("COLLECTION_FUNCS", "functions")
REPO_ROOT = os.getenv("REPO_ROOT", ".")
MCP_PORT = int(os.getenv("MCP_PORT", "8083"))


# ---- **추가: 런타임 FastMCP 버전 확인** ----
try:
    MCP_VERSION = get_version("mcp")
except Exception:
    MCP_VERSION = "unknown"

logger.info(f"Loaded FastMCP Version: {MCP_VERSION}")
# -----------------------------------------------

# 1. MCP 인스턴스 초기화 (이름은 Docker Compose 서비스 이름과 일치시키지 않아도 됨)
#mcp = FastMCP("rag-mcp-agent", host="0.0.0.0", port=MCP_PORT)

mcp = FastMCP("rag-mcp")

# ----------------------
# 임베딩 유틸리티
# ----------------------
async def _embed(texts):
    """Sends text to the TEI server to obtain embedding vectors"""
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.post(f"{TEI_URL}/embed", json={"inputs": texts})
            r.raise_for_status()
            return np.array(r.json(), dtype=np.float32)
    except Exception as e:
        raise RuntimeError(f"Embedding failed: {str(e)}")


# ----------------------
# Qdrant Client
# ----------------------
cli = QdrantClient(url=QDRANT_URL)


# ----------------------
# MCP 도구 정의
# ----------------------

@mcp.tool()
async def search_code(query: str, k: int = 8, repo: str | None = None):
    """Searches the entire codebase for the 'k' most semantically similar code snippets to the given query.
    
    The result is returned as a list of text strings, including the code's location information (e.g., 'repo/file:start-end') and similarity score.
    The search scope can be narrowed by specifying a particular 'repo'.
    This tool is used to identify the approximate location of relevant code.
    """
    logger.info(f"called search_code : {str}")
    try:
        vec = (await _embed([query]))[0].tolist()
        f = None
        if repo:
            f = qm.Filter(must=[qm.FieldCondition(key="repo", match=qm.MatchValue(value=repo))])
        res = cli.search(collection_name=CODE_COL, query_vector=vec, limit=k, query_filter=f)
        results = []
        for h in res:
            p = h.payload
            results.append(
                f"{p.get('repo','unknown')}/{p.get('file','unknown')}:{p.get('start',0)}-{p.get('end',0)} "
                f"score={getattr(h, 'score', 0.0):.4f}"
            )
        logger.info(f"result {results}")
        return TextContent(type="text", text="\n".join(results))
    except Exception as e:
        return TextContent(type="text", text=f"Error: {str(e)}")


@mcp.tool()
async def list_functions(repo: str):
    """Returns a list of all top-level functions and class methods contained within the specified repository ('repo').
    
    The result is a list of text strings including the file location (e.g., 'file:start-end') and the name of each function.
    """
    logger.info(f"called list functions : {str}")
    try:
        f = qm.Filter(must=[
            qm.FieldCondition(key="repo", match=qm.MatchValue(value=repo)),
            qm.FieldCondition(key="type", match=qm.MatchValue(value="function"))
        ])
        res, _ = cli.scroll(collection_name=FUNC_COL, limit=10000, scroll_filter=f)
        items = []
        for r in res:
            p = r.payload
            items.append(f"{p.get('file','unknown')}:{p.get('start',0)}-{p.get('end',0)} {p.get('name','unknown')}")
        logger.info(f"result {items}")
        return TextContent(type="text", text="\n".join(items))
    except Exception as e:
        return TextContent(type="text", text=f"Error: {str(e)}")


@mcp.tool()
async def retrieve_snippet(repo: str, file: str, start: int, end: int):
    """Retrieves and returns the exact code content as text, spanning from the 'start' line to the 'end' line within a specific file ('file') of the given repository ('repo').
    
    This tool is used to convert location information obtained from 'search_code' or 'list_functions' into the concrete code content.
    """
    logger.info(f"called snippet : {str}")
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
    logger.info(f"called analyze issue : {str}")
    try:
        vec = (await _embed([question]))[0].tolist()
        f = None
        if repo:
            f = qm.Filter(must=[qm.FieldCondition(key="repo", match=qm.MatchValue(value=repo))])
        res = cli.search(collection_name=CODE_COL, query_vector=vec, limit=k, query_filter=f)
        items = []
        for h in res:
            p = h.payload
            items.append({
                "file": p.get("file", "unknown"),
                "start": p.get("start", 0),
                "end": p.get("end", 0),
                "score": getattr(h, "score", 0.0)
            })

        logger.info(f"result {items}")

        return TextContent(type="text", text=json.dumps(items, ensure_ascii=False, indent=2))
    except Exception as e:
        return TextContent(type="text", text=f"Error: {str(e)}")

if __name__ == "__main__":
    logger.info("🚀 Starting MCP 2.0.0 server with HTTP transport...")
    asyncio.run(mcp.run_async(transport="http", host="0.0.0.0", port=8083))
