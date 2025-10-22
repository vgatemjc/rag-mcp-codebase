import os, glob, json, uuid
from typing import List, Dict, Tuple
import httpx
import numpy as np
# 가정: vecdb, chunking, graph, settings는 정상적으로 import됨
from vecdb import VecDB 
from chunking import chunk_code
from graph import list_functions
from settings import settings
import logging

logger = logging.getLogger(__name__)

# 파일 확장자에 따른 언어 매핑
EXT_LANG = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
    ".java": "java", ".go": "go", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp", ".c": "c",
    ".rs": "rs", ".kt": "kt", ".swift": "swift"
}

# TEI 서버의 최대 배치 크기 (로그에서 64로 확인됨)
MAX_EMBEDDING_BATCH_SIZE = 64 

class Indexer:
    def __init__(self):
        self.db = VecDB(settings.qdrant_url)
        # _embed는 동기 함수를 사용하도록 수정
        self.dim = self._embed(["dimension check"]).shape[1] 
        self.db.ensure_collection(settings.collection_code, self.dim)
        self.db.ensure_collection(settings.collection_funcs, self.dim)
        logger.info(f"Indexer 초기화 완료. 벡터 차원: {self.dim}")

    async def _embed_async(self, texts: List[str]) -> np.ndarray:
        """비동기 임베딩 호출 (FastAPI 엔드포인트에서 사용 가능)"""
        async with httpx.AsyncClient(timeout=60) as cli:
            r = await cli.post(f"{settings.tei_url}/embed", json={"inputs": texts})
            r.raise_for_status()
            # TEI가 리스트를 반환한다고 가정
            return np.array(r.json(), dtype=np.float32)

    def _embed(self, texts: List[str]) -> np.ndarray:
        """동기 임베딩 호출 (초기화 및 동기 함수에서 사용)"""
        r = httpx.post(f"{settings.tei_url}/embed", json={"inputs": texts}, timeout=60)
        r.raise_for_status()
        # TEI가 리스트를 반환한다고 가정
        return np.array(r.json(), dtype=np.float32)

    def _embed_in_batches(self, texts: List[str]) -> np.ndarray:
        """
        텍스트를 MAX_EMBEDDING_BATCH_SIZE 단위로 나누어 임베딩을 수행하고 결과를 합칩니다.
        """
        all_embeddings = []
        n = len(texts)
        
        for i in range(0, n, MAX_EMBEDDING_BATCH_SIZE):
            batch = texts[i:i + MAX_EMBEDDING_BATCH_SIZE]
            logger.info(f"Embedding batch {i//MAX_EMBEDDING_BATCH_SIZE + 1} of {len(batch)} items (Total: {n})")
            
            # _embed 함수를 사용하여 각 배치를 동기적으로 임베딩
            try:
                batch_emb = self._embed(batch)
                all_embeddings.append(batch_emb)
            except httpx.HTTPStatusError as e:
                logger.error(f"Embedding failed for batch starting at index {i}: {e}")
                # 임베딩에 실패하면 해당 배치는 건너뛸 수 있도록 처리 (여기서는 예외를 다시 발생시켜야 함)
                raise # 413 오류의 경우 이 예외가 발생할 것입니다.
        # 🌟 FIX: 모든 임베딩 배열을 단일 NumPy 배열로 연결하여 반환 🌟
        
        if not all_embeddings:
            # 임베딩 결과가 없는 경우 빈 배열을 반환합니다.
            # 초기화 시점에 `self.dim`을 이미 확인했으므로, 차원 0인 배열을 생성할 수 있습니다.
            return np.zeros((0, self.dim), dtype=np.float32) 
            
        return np.concatenate(all_embeddings, axis=0)

    def _detect_lang(self, path: str) -> str:
        return EXT_LANG.get(os.path.splitext(path)[1].lower(), "")

    def _iter_files(self, root: str) -> List[str]:
        ignore = {".git", "node_modules", "build", "dist", ".venv", "venv", "__pycache__"}
        for dirpath, dirnames, filenames in os.walk(root):
            # 탐색에서 제외할 디렉토리 설정
            dirnames[:] = [d for d in dirnames if d not in ignore]
            for f in filenames:
                p = os.path.join(dirpath, f)
                # 언어를 감지할 수 있는 파일만 포함
                if self._detect_lang(p):
                    yield p

    def index_repo(self, repo_path: str, repo_name: str):
        # 전체 repo에 대해 단일 배치로 데이터를 수집할 리스트
        code_ids, code_vecs, code_payloads = [], [], []
        func_ids, func_vecs, func_payloads = [], [], []

        for path in self._iter_files(repo_path):
            lang = self._detect_lang(path)
            # path가 repo_path를 포함하는 경우를 대비하여 relpath 계산
            relative_path = os.path.relpath(path, repo_path)
            
            logger.info(f"--> [INDEX] Processing file: {relative_path} (Lang: {lang})")
            
            try:
                # 'r' 모드로 열고 인코딩 오류 무시
                with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
                    text = fp.read()
            except IOError as e:
                logger.error(f"Error reading file {path}: {e}")
                continue # 파일 읽기 실패 시 다음 파일로 이동

            # 1. 청크 처리 (Chunks)
            for (start, end, chunk) in chunk_code(text, max_lines=200, overlap=20):
                eid = str(uuid.uuid4())
                code_ids.append(eid)
                code_payloads.append({
                    "repo": repo_name, "file": relative_path,
                    "start": start, "end": end, "lang": lang, "type": "chunk"
                })
                code_vecs.append(chunk)

            # 2. 함수 처리 (Functions)
            # list_functions는 bytes를 받으므로 인코딩
            funcs = list_functions(lang, text.encode('utf-8'))
            lines = text.splitlines()
            
            for name, fstart, fend in funcs:
                eid = str(uuid.uuid4())
                func_ids.append(eid)
                
                # --- 버그 2 수정: 함수 라인을 리스트가 아닌 문자열로 결합 ---
                # 라인 번호는 1부터 시작하므로 인덱스는 fstart-1부터 fend-1까지입니다.
                func_body = "\n".join(lines[fstart-1:fend]) 
                
                # 함수 이름과 본문을 결합하여 임베딩 텍스트 생성
                func_text_for_embed = f"{name}\n{func_body}"
                
                func_payloads.append({
                    "repo": repo_name, "file": relative_path,
                    "start": fstart, "end": fend, "lang": lang, 
                    "name": name, "type": "function"
                })
                func_vecs.append(func_text_for_embed)

        # ----------------------------------------------------
        # --- 수정된 부분: _embed_in_batches 사용 ---
        # ----------------------------------------------------
        
        indexed_chunks = 0
        indexed_functions = 0
        
        # 청크 임베딩 및 업서트
        if code_vecs:
            logger.info(f"Starting batch embedding for {len(code_vecs)} code chunks...")
            code_emb = self._embed_in_batches(code_vecs) # 배치 임베딩 사용
            self.db.upsert(settings.collection_code, code_ids, code_emb, code_payloads)
            indexed_chunks = len(code_vecs)
        else:
            logger.warning("No code chunks found for indexing.")
        
        # 함수 임베딩 및 업서트
        if func_vecs:
            logger.info(f"Starting batch embedding for {len(func_vecs)} functions...")
            func_emb = self._embed_in_batches(func_vecs) # 배치 임베딩 사용
            self.db.upsert(settings.collection_funcs, func_ids, func_emb, func_payloads)
            indexed_functions = len(func_vecs)
        else:
            logger.warning("No functions found for indexing.")
            
        return {"chunks": indexed_chunks, "functions": indexed_functions}