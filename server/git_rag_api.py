from fastapi import FastAPI, HTTPException
import httpx
import numpy as np
import sys, logging
from pydantic import BaseModel
from pathlib import Path
from typing import Dict, Any, Optional, List
import os
import json
import uvicorn
import logging
import sys
import textwrap
from dataclasses import dataclass
import ast
import re
import hashlib
from git_aware_code_indexer import (
    VectorStore, Embeddings, Retriever, Indexer, GitCLI, DiffUtil, Range, Hunk, Chunker,
    Relocalizer, _TS_AVAILABLE
)
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

REPOS_DIR = Path("/workspace/myrepo")
STATE_FILE = Path("index_state.json")
class Config:
    ENV: str = os.getenv("APP_ENV", "dev")
    QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    QDRANT_API_KEY: str = os.getenv("QDRANT_API_KEY", "")
    TEI_BASE_URL: str = os.getenv("TEI_BASE_URL", "http://localhost:8080/v1")
    TEI_MODEL: str = os.getenv("TEI_MODEL", "text-embedding-3-large")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    DIM: Optional[int] = int(os.getenv("DIM", "0")) or None
    BRANCH: str = "main"

config = Config()
modelslug = re.sub(r"[^a-z0-9]+", "", config.TEI_MODEL.lower())
config.COLLECTION = f"git_rag-{config.ENV}-{modelslug}"

# Global instances
emb = Embeddings(base_url=config.TEI_BASE_URL, model=config.TEI_MODEL, api_key=config.OPENAI_API_KEY)
store = VectorStore(collection=config.COLLECTION, url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY, dim=config.DIM)  # Re-init with new collection

# State management
def load_state() -> Dict[str, str]:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(state: Dict[str, str]):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_repo_path(repo_id: str) -> Path:
    path = REPOS_DIR / repo_id
    if not path.exists() or not (path / ".git").exists():
        raise ValueError(f"Invalid repo: {repo_id}")
    return path

app = FastAPI(title="Git RAG API")

class SearchRequest(BaseModel):
    query: str
    repo_id: Optional[str] = None
    k: int = 5

class IndexResponse(BaseModel):
    status: str
    message: str
    last_commit: Optional[str] = None

class StatusResponse(BaseModel):  # Added
    modified: List[str]
    added: List[str]
    deleted: List[str]
    renamed: List[str]

@app.get("/repos", response_model=List[str])
def list_repos():
    repos = []
    for item in REPOS_DIR.iterdir():
        if item.is_dir() and (item / ".git").exists():
            repos.append(item.name)
    return repos

@app.post("/repos/{repo_id}/index/full", response_model=IndexResponse)
def full_index(repo_id: str):
    try:  # Fixed GitCLI call, assuming get_head added        
        repo_path = get_repo_path(repo_id)
        git = GitCLI(str(repo_path))
        head = git.get_head()
        indexer = Indexer(str(repo_path), repo_id, emb, store, config.COLLECTION)
        indexer.full_index(head, config.BRANCH)
        logger.info("full index done")
        state = load_state()
        state[repo_id] = head
        save_state(state)
        return IndexResponse(status="success", message="Full index completed", last_commit=head)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/repos/{repo_id}/index/update", response_model=IndexResponse)
def update_index(repo_id: str):
    try:
        repo_path = get_repo_path(repo_id)
        git = GitCLI(str(repo_path))
        head = git.get_head()
        state = load_state()
        base = state.get(repo_id)

        logger.info(f"Update Index: Base={base}, Head={head}")

        if not base:
            raise ValueError("No base commit found; run full index first.")
        
        indexer = Indexer(str(repo_path), repo_id, emb, store, config.COLLECTION)
        
        # [변경 코멘트: 논리적 오류 수정] 베이스 == 헤드일 때 로컬 변경사항을 인덱싱해야 하며,
        # 베이스 != 헤드일 때 커밋 변경사항을 인덱싱해야 합니다.

        if base != head:
            # Commit mode
            logger.info(f"indexing commit mode ")
            try:
                indexer.index_commit(base, head, config.BRANCH)
                message = "Incremental index (commit) completed"
            except RuntimeError as e:
                # [변경 코멘트: 논리적 오류 수정] 커밋 모드에서 변경사항이 없을 때의 noop 처리가 누락되어 있었습니다.
                if "no changes between commits" in str(e).lower():
                    return IndexResponse(status="noop", message="No changes detected between commits", last_commit=head)
                raise
        else:
            # Local mode (base == head, check working tree)
            logger.info(f"indexing local mode ")
            try:
                # head=None을 전달하여 working tree 변경사항을 인덱싱하도록 합니다.
                indexer.index_commit(base, None, config.BRANCH)
                message = "Incremental index (local changes) completed"
            except RuntimeError as e:
                # [변경 코멘트: 논리적 오류 수정] 로컬 모드에서 변경사항이 없을 때의 noop 처리가 누락되어 있었습니다.
                if "no changes in working directory" in str(e).lower():
                    return IndexResponse(status="noop", message="No local changes detected", last_commit=head)
                raise

        state[repo_id] = head
        save_state(state)
        return IndexResponse(status="success", message=message, last_commit=head)
    except ValueError as e:  # Handle no base
        raise HTTPException(status_code=400, detail=str(e))
        # [변경 코멘트: 오류 처리 간소화] 일반 예외 처리를 마지막에 둡니다.
    except Exception as e:
        # [변경 코멘트: 오류 처리 간소화] 일반 예외 처리를 마지막에 둡니다.
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/repos/{repo_id}/status", response_model=StatusResponse)
def get_local_status(repo_id: str):
    try:
        repo_path = get_repo_path(repo_id)
        git = GitCLI(str(repo_path))
        status_out = git._run("status", "--porcelain", "--untracked-files=no")
        logger.info(f"get_local_status status out : {status_out}")
        modified = []
        added = []
        deleted = []
        renamed = []
        
        STATUS_LETTERS = ('M', 'A', 'D', 'R')

        for line in status_out.splitlines():
            if len(line) < 3:
                continue
            x_status = line[0] # Staged (X) 상태
            y_status = line[1] # Unstaged (Y) 상태
            file_path = line[3:].strip()

            # [수정 2: Staged/Unstaged 변경 모두 감지]
            # Staged 변경(X)을 우선하고, Staged 변경이 없으면 Unstaged 변경(Y)을 status로 사용합니다.
            status = ''
            if x_status in STATUS_LETTERS:
                status = x_status
            elif y_status in STATUS_LETTERS:
                status = y_status
            
            if not status:
                continue

            if status == 'M':
                modified.append(file_path)
            elif status == 'A':
                added.append(file_path)
            elif status == 'D':
                deleted.append(file_path)
            elif status == 'R':
                renamed.append(file_path)
        return StatusResponse(modified=modified, added=added, deleted=deleted, renamed=renamed)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/search", response_model=List[Dict[str, Any]])
def search(req: SearchRequest):
    try:
        repo_path = None
        if req.repo_id:
            repo_path = get_repo_path(req.repo_id)
        retriever = Retriever(store, emb, str(repo_path) if repo_path else None)
        # [변경 코멘트: 함수 호출 인자 수정] Retriever.search의 인자가 변경되었으므로 (repo 추가) 수정합니다.
        results = retriever.search(req.query, req.k, config.BRANCH, repo=req.repo_id)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/test", response_model=Dict[str, Any])
def run_selftests():
    results = []
    passed = True

    # Test 1: translate no overlap
    try:
        r = Range(100, 120, 0, 0)
        hunks = [Hunk(10, 3, 10, 10)]
        tr = DiffUtil.translate(r, hunks)
        assert tr.start_line == 107 and tr.end_line == 127 and not tr.relocalize
        results.append("Test 1: translate shift passed")
    except AssertionError as e:
        results.append(f"Test 1: translate shift failed - {e}")
        passed = False

    # ... (other tests similar to original _run_selftests, adapted without print)

    # Test 3: python chunker extracts symbols
    try:
        src_py = textwrap.dedent('''
        class Foo:
            def a(self, x):
                return x

        def b(y:int)->int:
            return y+1
        ''')
        chs = Chunker.py_chunks(src_py, "mod.py", "repo")
        kinds = sorted(c.symbol.split(":")[0] for c in chs)
        assert kinds == ["class", "func"]
        results.append("Test 3: Python chunker passed")
    except AssertionError as e:
        results.append(f"Test 3: Python chunker failed - {e}")
        passed = False

    # Test 4 & 5: Tree-sitter (if available, similar)
    if _TS_AVAILABLE:
        # JS test
        src_js = textwrap.dedent('''
        class C { m(x) { return x } }
        function f(y){ return y+1 }
        ''')
        chs_js = Chunker.ts_chunks(src_js, "a.js", "repo", "javascript")
        assert any(s.symbol.startswith("class:") for s in chs_js)
        assert any(s.symbol.startswith("func:") for s in chs_js)
        results.append("Test 4: Tree-sitter JS passed")
    else:
        results.append("Test 4: Tree-sitter JS skipped (not available)")

    if _TS_AVAILABLE:
        # Rust test
        src_rs = textwrap.dedent('''
        struct S { v: i32 }
        impl S { fn m(&self, x:i32) -> i32 { x + 1 } }
        fn f(y:i32) -> i32 { y + 2 }
        ''')
        chs_rs = Chunker.ts_chunks(src_rs, "lib.rs", "repo", "rust")
        assert any(s.symbol.startswith("func:") for s in chs_rs)
        assert any("struct:" in s.symbol or s.symbol.startswith("class:") for s in chs_rs)
        results.append("Test 5: Tree-sitter Rust passed")
    else:
        results.append("Test 5: Tree-sitter Rust skipped (not available)")

    status = "All selftests passed" if passed else "Some selftests failed"
    return {"status": status, "details": results}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)