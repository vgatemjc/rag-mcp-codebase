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
from qdrant_client.models import PointStruct
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
    EMB_BASE_URL: str = os.getenv("EMB_BASE_URL", "http://localhost:8080/v1")
    EMB_MODEL: str = os.getenv("EMB_MODEL", "text-embedding-3-large")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    DIM: Optional[int] = int(os.getenv("DIM", "0")) or None
    BRANCH: str = "main"

config = Config()
modelslug = re.sub(r"[^a-z0-9]+", "", config.EMB_MODEL.lower())
config.COLLECTION = f"git_rag-{config.ENV}-{modelslug}"

from qdrant_client import QdrantClient  # Ensure this is imported if not already (for type hints)
from qdrant_client.models import Distance, VectorParams
from qdrant_client.http.exceptions import UnexpectedResponse  # For better error handling

def ensure_collection():
    """컬렉션이 없으면 생성 (DIM 동적 계산 포함)."""
    try:
        if store.client.collection_exists(config.COLLECTION):  # Fixed: Use collection_exists instead of has_collection
            logger.info(f"Collection '{config.COLLECTION}' already exists.")
            # Check existing DIM for mismatch
            col_info = store.client.get_collection(config.COLLECTION)
            existing_dim = col_info.config.params.vectors.size
            if config.DIM and config.DIM != existing_dim:
                logger.warning(f"DIM mismatch: config={config.DIM}, existing={existing_dim}. Reindex after recreating collection.")
            return

        # DIM이 None/0이면 샘플 임베딩으로 동적 계산
        if not config.DIM or config.DIM == 0:
            logger.info("DIM not set; computing dynamically from sample embedding.")
            sample_text = "This is a sample text for dimension detection."
            sample_vector = emb.embed([sample_text])[0]  # 단일 텍스트 임베딩 (list로 호출)
            dynamic_dim = len(sample_vector)
            logger.info(f"Detected embedding dimension: {dynamic_dim}")
        else:
            dynamic_dim = config.DIM

        # 컬렉션 생성
        store.client.create_collection(
            collection_name=config.COLLECTION,
            vectors_config=VectorParams(
                size=dynamic_dim,
                distance=Distance.COSINE  # 일반적인 임베딩 거리 메트릭
            )
        )
        logger.info(f"Created collection '{config.COLLECTION}' with dim={dynamic_dim}.")
    except Exception as e:
        logger.error(f"Failed to ensure collection '{config.COLLECTION}': {e}")
        # Optional: Don't raise here to allow server startup (handle lazily in endpoints), but for strict setup, keep:
        raise HTTPException(status_code=500, detail=f"Collection setup failed: {str(e)}")


# Global instances
emb = Embeddings(base_url=config.EMB_BASE_URL, model=config.EMB_MODEL, api_key=config.OPENAI_API_KEY)
store = VectorStore(collection=config.COLLECTION, url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY, dim=config.DIM)  # Re-init with new collection
ensure_collection()

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

class IndexProgress(BaseModel):
    status: str
    message: str
    file: Optional[str] = None
    total_files: Optional[int] = None
    processed_files: Optional[int] = None
    last_commit: Optional[str] = None

from fastapi.responses import StreamingResponse
import io

def generate_full_index_progress(repo_id: str):
    try:
        repo_path = get_repo_path(repo_id)
        git = GitCLI(str(repo_path))
        head = git.get_head()
        indexer = Indexer(str(repo_path), repo_id, emb, store, config.COLLECTION)
        files = indexer.git.list_files(head)
        total_files = len(files)
        processed = 0
        
        # 초기 상태 전송
        yield json.dumps({
            "status": "started",
            "message": "Starting full index",
            "total_files": total_files,
            "processed_files": 0,
            "last_commit": head
        }) + "\n"
        
        to_embed_all = []  # 전체 chunks를 모으지 말고, 파일별로 처리
        for path in files:
            head_src = indexer.git.show_file(head, path) or ""
            logger.debug(f"full index head src {head_src}")
            if head_src:
                file_chunks = Chunker.chunks(head_src, path, repo_id)
                if file_chunks:
                    # 파일별로 embed 호출 (배치지만 파일 단위로)
                    texts = [c.content for c in file_chunks]
                    vectors = emb.embed(texts)
                    points = []
                    for c, v in zip(file_chunks, vectors):
                        payload = indexer._build_payload(c, config.BRANCH, head)
                        point_id = payload["point_id"]
                        points.append(PointStruct(id=point_id, vector=v, payload=payload))
                    if points:
                        store.client.upsert(collection_name=config.COLLECTION, points=points)
                    
                    processed += 1
                    yield json.dumps({
                        "status": "processing",
                        "message": f"Processed file: {path}",
                        "file": path,
                        "total_files": total_files,
                        "processed_files": processed,
                        "last_commit": head
                    }) + "\n"
                else:
                    processed += 1
                    yield json.dumps({
                        "status": "processing",
                        "message": f"Skipped empty file: {path}",
                        "file": path,
                        "total_files": total_files,
                        "processed_files": processed,
                        "last_commit": head
                    }) + "\n"
            else:
                processed += 1
                yield json.dumps({
                    "status": "processing",
                    "message": f"Skipped missing file: {path}",
                    "file": path,
                    "total_files": total_files,
                    "processed_files": processed,
                    "last_commit": head
                }) + "\n"
        
        # 완료 상태
        state = load_state()
        state[repo_id] = head
        save_state(state)
        yield json.dumps({
            "status": "completed",
            "message": "Full index completed",
            "total_files": total_files,
            "processed_files": processed,
            "last_commit": head
        }) + "\n"
        logger.info("full index done")
    except Exception as e:
        yield json.dumps({
            "status": "error",
            "message": str(e)
        }) + "\n"
        logger.error(f"Full index error: {e}")

def generate_update_index_progress(repo_id: str):
    try:
        repo_path = get_repo_path(repo_id)
        git = GitCLI(str(repo_path))
        head = git.get_head()
        state = load_state()
        base = state.get(repo_id)

        logger.info(f"Update Index: Base={base}, Head={head}")

        if not base:
            yield json.dumps({
                "status": "error",
                "message": "No base commit found; run full index first.",
                "last_commit": head
            }) + "\n"
            return
        
        indexer = Indexer(str(repo_path), repo_id, emb, store, config.COLLECTION)
        
        # [변경 코멘트: 논리적 오류 수정] 베이스 == 헤드일 때 로컬 변경사항을 인덱싱해야 하며,
        # 베이스 != 헤드일 때 커밋 변경사항을 인덱싱해야 합니다.

        if base != head:
            # Commit mode
            logger.info(f"indexing commit mode ")
            diff_text = indexer.git.diff_unified_0(base, head)
            logger.info(f"[DEBUG] Raw Diff Text received (first 500 chars): \n{diff_text[:500]}")
            file_diffs = DiffUtil.parse_unified_diff(diff_text)
            if not file_diffs and diff_text.strip():
                logger.error(f"Diff parsing failed, file_diffs is empty but diff_text is NOT. Raw diff: {diff_text[:500]}")
            if not file_diffs:
                yield json.dumps({
                    "status": "noop",
                    "message": "No changes detected between commits",
                    "last_commit": head
                }) + "\n"
                return
            total_files = len(file_diffs)
            processed = 0
            commit_sha = head
        else:
            # Local mode (base == head, check working tree)
            logger.info(f"indexing local mode ")
            status_out = indexer.git._run("status", "--porcelain", "--untracked-files=no")
            status_out = status_out or "" 
            logger.info(f"local mode status out : {status_out}")
            STATUS_LETTERS = ('M', 'A', 'D', 'R', 'C', 'U', 'T')
            changed_paths = [
                line[3:].strip() 
                for line in status_out.splitlines() 
                if len(line) >= 3 and (
                    line[0] in STATUS_LETTERS or # Staged changes (e.g., 'M ')
                    line[1] in STATUS_LETTERS    # Unstaged changes (e.g., ' M')
                )
            ]
            if not changed_paths:
                yield json.dumps({
                    "status": "noop",
                    "message": "No local changes detected",
                    "last_commit": head
                }) + "\n"
                return
            diff_text = indexer.git.diff_to_working(base, changed_paths)
            file_diffs = DiffUtil.parse_unified_diff(diff_text)
            commit_sha = base
            total_files = len(file_diffs)
            processed = 0

        # 초기 상태 전송
        yield json.dumps({
            "status": "started",
            "message": "Starting incremental index",
            "total_files": total_files,
            "processed_files": 0,
            "last_commit": head
        }) + "\n"

        logger.info(f"diff test {diff_text[:500]}")
        logger.info(f"file diffs {file_diffs}")

        for fd in file_diffs:

            # ------------------------------------------------------
            # ✅ FILE REMOVED CASE — 완전 삭제
            # ------------------------------------------------------
            if fd.is_deleted:
                logger.info(f"[DELETE] File removed: {fd.path}")

                base_src = indexer.git.show_file(base, fd.path) or ""
                if base_src:
                    try:
                        base_chunks = {
                            c.symbol: c for c in Chunker.chunks(base_src, fd.path, repo_id)
                        }
                        remove_ids = []

                        for _, ch in base_chunks.items():
                            olds = store.scroll_by_logical(ch.logical_id, is_latest=True)
                            remove_ids.extend([p.id for p in olds])

                        if remove_ids:
                            store.client.delete(
                                collection_name=config.COLLECTION,
                                points=remove_ids
                            )
                            logger.info(f"[DELETE] Removed {len(remove_ids)} vectors for {fd.path}")
                    except Exception as e:
                        logger.error(f"[ERROR] Failed to remove deleted file {fd.path}: {e}")

                processed += 1
                yield json.dumps({
                    "status": "processing",
                    "message": f"Removed deleted file: {fd.path}",
                    "file": fd.path,
                    "total_files": total_files,
                    "processed_files": processed,
                    "last_commit": head
                }) + "\n"
                continue

            # ------------------------------------------------------
            # ✅ NORMAL CASE — FILE EXISTS
            # ------------------------------------------------------
            head_src = indexer.git.show_file(head if base != head else None, fd.path) or ""
            logger.debug(f"index commit : head_src {head_src}")
            
            if not head_src:
                processed += 1
                yield json.dumps({
                    "status": "processing",
                    "message": f"Skipped missing file (not deleted but no head src): {fd.path}",
                    "file": fd.path,
                    "total_files": total_files,
                    "processed_files": processed,
                    "last_commit": head
                }) + "\n"
                continue
            try:
                head_chunks = {c.symbol: c for c in Chunker.chunks(head_src, fd.path, repo_id)}
                logger.info(f"Successfully chunked {fd.path}. Chunks count: {len(head_chunks)}")
            except Exception as e:
                logger.error(f"FATAL: Failed to chunk file {fd.path} due to: {e.__class__.__name__}: {e}")
                processed += 1
                yield json.dumps({
                    "status": "processing",
                    "message": f"Failed to chunk file: {fd.path} ({str(e)})",
                    "file": fd.path,
                    "total_files": total_files,
                    "processed_files": processed,
                    "last_commit": head
                }) + "\n"
                continue

            base_src = indexer.git.show_file(base, fd.path) or ""
            logger.debug(f"index commit : base_src {base_src}")
            to_embed = []
            to_update_only_pos = []
            for _, ch in head_chunks.items():
                prev_points = store.scroll_by_logical(ch.logical_id, is_latest=True)
                if not prev_points:
                    to_embed.append(ch)
                    continue
                prev = prev_points[0]
                if prev.payload.get("content_hash") != ch.content_hash:
                    to_embed.append(ch)
                else:
                    translated = DiffUtil.translate(ch.range, fd.hunks)
                    if translated.relocalize and base_src:
                        br = prev.payload.get("byte_range", [ch.range.byte_start, ch.range.end_line])
                        base_slice = base_src[br[0]:br[1]] if 0 <= br[0] <= br[1] <= len(base_src) else ""
                        if base_slice:
                            loc = Relocalizer.exact_relocate(base_slice, head_src) or Relocalizer.fuzzy_relocate(base_slice, head_src)
                            if loc:
                                translated = Range(loc[0], loc[1], br[0], br[1], False)
                    to_update_only_pos.append((ch, translated))
            
            # 파일별 embed 및 upsert
            if to_embed:
                texts = [c.content for c in to_embed]
                vectors = emb.embed(texts)
                points = []
                for c, v in zip(to_embed, vectors):
                    olds = store.scroll_by_logical(c.logical_id, is_latest=True)
                    if olds:
                        store.set_payload([p.id for p in olds], {"is_latest": False})
                    payload = indexer._build_payload(c, config.BRANCH, commit_sha)
                    point_id = payload["point_id"]
                    points.append(PointStruct(id=point_id, vector=v, payload=payload))
                if points:
                    store.client.upsert(collection_name=config.COLLECTION, points=points)
            
            if to_update_only_pos:
                for ch, r in to_update_only_pos:
                    olds = store.scroll_by_logical(ch.logical_id, is_latest=True)
                    if olds:
                        store.set_payload([p.id for p in olds], {"lines": [r.start_line, r.end_line]})
            
            processed += 1
            yield json.dumps({
                "status": "processing",
                "message": f"Processed file: {fd.path}",
                "file": fd.path,
                "total_files": total_files,
                "processed_files": processed,
                "last_commit": head
            }) + "\n"
        
        # 완료 상태
        state[repo_id] = head
        save_state(state)
        yield json.dumps({
            "status": "completed",
            "message": "Incremental index completed",
            "total_files": total_files,
            "processed_files": processed,
            "last_commit": head
        }) + "\n"
    except Exception as e:
        yield json.dumps({
            "status": "error",
            "message": str(e),
            "last_commit": head if 'head' in locals() else None
        }) + "\n"
        logger.error(f"Update index error: {e}")

@app.get("/repos", response_model=List[str])
def list_repos():
    repos = []
    for item in REPOS_DIR.iterdir():
        if item.is_dir() and (item / ".git").exists():
            repos.append(item.name)
    return repos

@app.post("/repos/{repo_id}/index/full")
def full_index(repo_id: str):
    return StreamingResponse(generate_full_index_progress(repo_id), media_type="application/json")

@app.post("/repos/{repo_id}/index/update")
def update_index(repo_id: str):
    return StreamingResponse(generate_update_index_progress(repo_id), media_type="application/json")

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