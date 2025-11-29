
import os
import io
import re
import ast
import json
import hashlib
import subprocess
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any, Protocol
import uuid
from openai import OpenAI

from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, Filter, FieldCondition, MatchAny, MatchValue
import requests
import sys, logging
from dotenv import load_dotenv
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

# Load environment variables early so chunk limits pick them up.
load_dotenv()

# Heuristic limits to keep embedding requests under the model's context window.
CHUNK_TOKENS = int(os.getenv("CHUNK_TOKENS", "512"))
CHARS_PER_TOKEN_EST = float(os.getenv("CHARS_PER_TOKEN_EST", "1.5"))
CHUNK_LINES = int(os.getenv("CHUNK_LINES", "120"))
CHUNK_TOKEN_FRACTION = float(os.getenv("CHUNK_TOKEN_FRACTION", "0.6"))
# Cap characters per chunk using a conservative chars-per-token estimate; enforce a sensible floor.
MAX_CONTENT_CHARS = max(256, int(CHUNK_TOKENS * CHUNK_TOKEN_FRACTION * CHARS_PER_TOKEN_EST))

# Optional Tree-sitter
_TS_AVAILABLE = False
try:
    from tree_sitter import Parser
    from tree_sitter_languages import get_language
    _TS_AVAILABLE = True
except Exception:
    _TS_AVAILABLE = False

# Qdrant client knobs
QDRANT_UPSERT_BATCH = max(1, int(os.getenv("QDRANT_UPSERT_BATCH", "128")))
QDRANT_TIMEOUT = float(os.getenv("QDRANT_TIMEOUT", "30"))

def _is_probably_binary(data: bytes, sample_size: int = 8000, control_threshold: float = 0.3) -> bool:
    """
    Lightweight binary detector: flags content with NUL bytes or a high ratio of
    control characters. Keeps UTF-8 text (including non-ASCII) from being
    treated as binary.
    """
    if not data:
        return False
    if b"\x00" in data:
        return True
    sample = data[:sample_size]
    allowed_ctrl = {9, 10, 13}  # tab, newline, carriage return
    control_bytes = sum(1 for b in sample if b < 32 and b not in allowed_ctrl)
    return (control_bytes / max(1, len(sample))) > control_threshold

# ----------------------- utils -----------------------
def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

@dataclass
class Range:
    start_line: int
    end_line: int
    byte_start: int
    byte_end: int
    relocalize: bool = False

@dataclass
class Chunk:
    logical_id: str
    symbol: str
    path: str
    language: str
    range: Range
    content: str
    content_hash: str
    sig_hash: str
    neighbors: List[str] = None
    block_id: Optional[str] = None
    block_range: Optional[Range] = None
    meta: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.neighbors is None:
            self.neighbors = []
        if self.meta is None:
            self.meta = {}

# TEI 서버의 최대 배치 크기 (로그에서 64로 확인됨)
EMBEDDING_BATCH_SIZE = 32


class PayloadPlugin(Protocol):
    """Hook to attach stack- or domain-specific fields to a chunk payload."""

    def build_payload(self, chunk: Chunk, branch: str, commit_sha: str) -> Dict[str, Any]:
        ...


class ChunkPlugin(Protocol):
    """Hook to customize chunking for specific stacks or file types."""

    def supports(self, path: str, stack_type: Optional[str] = None) -> bool:
        ...

    def preprocess(self, src: str, path: str, repo: str) -> str:
        return src

    def postprocess(self, chunks: List[Chunk], path: str, repo: str) -> List[Chunk]:
        return chunks

    def extra_chunks(self, src: str, path: str, repo: str) -> List[Chunk]:
        return []

class Embeddings:
    def __init__(self, base_url: str, model: str, api_key: str = ""):
        """
        Initializes an Embeddings client using the OpenAI SDK, pointed at a TEI server
        with OpenAI compatibility enabled.
        """
        self.base_url = base_url.rstrip("/") + "/v1"  # Ensure OpenAI-compatible base path
        self.model = model
        self.api_key = api_key
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key if self.api_key else "unused",  # TEI may not require it; set to dummy if empty
            timeout=None
        )

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Embeds texts using the OpenAI SDK against a TEI server.
        Batches requests to avoid payload size limits.
        Returns a flat list of embedding vectors.
        """
        if not texts:
            return []

        all_embeddings = []
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[i:i + EMBEDDING_BATCH_SIZE]
            
            logger.info(f"Sending embedding request for batch {i} to {i + len(batch)}")

            try:
                response = self.client.embeddings.create(
                    input=batch,
                    model=self.model
                )
                # Extract embeddings from the response
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
                
            except Exception as e:  # Catch OpenAI SDK errors (e.g., APIError, Timeout)
                logger.error(f"Error during embedding request for batch {i}: {e}")
                # Re-raise to propagate the error
                raise

        return all_embeddings

# ----------------------- qdrant store -----------------------
class VectorStore:
    def __init__(self, collection: str, url: str, api_key: Optional[str] = None, dim: Optional[int] = None):
        self.collection = collection
        self.client = QdrantClient(url=url, api_key=api_key, timeout=QDRANT_TIMEOUT)
        self.is_new = False
        try:
            self.client.get_collection(collection_name=collection)
        except Exception:
            if dim is None:
                raise RuntimeError("Create collection manually or provide dim on first run")
            from qdrant_client.http.models import Distance, VectorParams
            self.client.recreate_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            self.is_new = True

    def upsert(self, point_id: str, vector: List[float], payload: Dict[str, Any]):
        self.upsert_points([PointStruct(id=point_id, vector=vector, payload=payload)])

    def upsert_points(self, points: List[PointStruct], batch_size: int = QDRANT_UPSERT_BATCH):
        batch = max(1, batch_size)
        for i in range(0, len(points), batch):
            self.client.upsert(collection_name=self.collection, points=points[i:i + batch])

    def set_payload(self, point_ids: List[str], payload: Dict[str, Any]):
        self.client.set_payload(collection_name=self.collection, payload=payload, points=point_ids)

    def search(self, query_vector: List[float], k: int = 5, filt: Optional[Filter] = None):
        return self.client.search(collection_name=self.collection, query_vector=query_vector, limit=k, query_filter=filt)

    def scroll_by_logical(self, logical_id: str, is_latest: Optional[bool] = None) -> List[Dict[str, Any]]:
        must = [FieldCondition(key="logical_id", match=MatchValue(value=logical_id))]
        if is_latest is not None:
            must.append(FieldCondition(key="is_latest", match=MatchValue(value=is_latest)))
        filt = Filter(must=must)
        res, _ = self.client.scroll(collection_name=self.collection, scroll_filter=filt, limit=100)
        return res

# ----------------------- git CLI wrapper -----------------------
class GitCLI:
    def __init__(self, repo_path: str):
        # Normalize to an absolute path so Git's safe.directory check matches exactly.
        self.repo_path = os.path.abspath(repo_path)
        self._ensure_repo_marked_safe()

    def _ensure_repo_marked_safe(self) -> None:
        """Make sure Git trusts this repository path."""
        try:
            subprocess.check_output(
                ["git", "config", "--global", "--add", "safe.directory", self.repo_path],
                stderr=subprocess.STDOUT,
                timeout=10,
            )
        except FileNotFoundError:
            raise RuntimeError("`git` CLI not found. Install Git or run in an environment with Git available.")
        except subprocess.TimeoutExpired:
            raise RuntimeError("git command timeout while marking safe.directory")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"failed to mark git safe.directory: {e.output.decode('utf-8', errors='ignore')}")

    def _run_bytes(self, *args: str) -> bytes:
        try:
            return subprocess.check_output(
                ["git", "--no-pager", *args],
                cwd=self.repo_path,
                stderr=subprocess.STDOUT,
                timeout=60,
            )
        except FileNotFoundError:
            raise RuntimeError("`git` CLI not found. Install Git or run in an environment with Git available.")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"git command timeout: {' '.join(args)}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"git command failed: {' '.join(args)}\n{e.output.decode('utf-8', errors='ignore')}")

    def _run(self, *args: str) -> str:
        out = self._run_bytes(*args)
        return out.decode("utf-8", errors="ignore")

    def diff_unified_0(self, base: str, head: str) -> str:
        return self._run("diff", f"{base}..{head}", "--unified=0", "--ignore-blank-lines", "--ignore-space-at-eol", "--no-color")
    
    def diff_to_working(self, base: str, paths: List[str]) -> str:
        if not paths:
            return ""
        # [수정 코멘트: _run 사용]
        # opts 리스트를 만들 필요 없이 _run에 모든 인자를 직접 전달합니다.
        # `*paths`를 사용하여 리스트를 가변 인자(separate arguments)로 펼칩니다.
        return self._run("diff",
                         "--unified=0", 
                         "--ignore-blank-lines", 
                         "--ignore-space-at-eol", 
                         "--no-color", 
                         base, 
                         "--", 
                         *paths) # paths 리스트의 각 요소를 개별 인자로 전달

    def show_file(self, commit: Optional[str], path: str) -> Optional[str]:
        # 1. 로컬 모드: Working Tree에서 파일 읽기 (commit is None)
        if commit is None:
            full_path = os.path.join(self.repo_path, path)
            try:
                with open(full_path, "rb") as f:
                    raw = f.read()
                if _is_probably_binary(raw):
                    logger.info("Skipping binary working tree file: %s", path)
                    return None
                return raw.decode("utf-8", errors="ignore")
            except FileNotFoundError:
                return None
            except RuntimeError:
                return None
            except Exception:
                # 파일 읽기 중 기타 오류 발생 시
                return None
        # 2. 커밋/참조 모드: Git 히스토리에서 파일 읽기 (commit is not None)
        else:
            try:
                raw = self._run_bytes("show", f"{commit}:{path}")
                if _is_probably_binary(raw):
                    logger.info("Skipping binary file from commit %s: %s", commit, path)
                    return None
                return raw.decode("utf-8", errors="ignore")
            except RuntimeError as e:
                # _run이 Git 명령 실패 시 RuntimeError를 발생시킨다고 가정합니다.
                error_message = str(e).lower()
                
                # Git이 "파일 없음"을 반환하는 두 가지 패턴을 확인합니다.
                # 1. 새로 추가된 파일이 base 커밋에 없는 경우
                is_new_file_not_in_base = "exists on disk, but not in" in error_message
                # 2. 일반적인 파일 없음 오류
                is_file_deleted = "does not exist" in error_message and "fatal: path" in error_message
                
                if is_new_file_not_in_base or is_file_deleted:
                    # 파일이 해당 커밋에 존재하지 않으므로, None을 반환합니다.
                    return None
                
                # 그 외의 심각한 Git 오류는 재발생시킵니다.
                raise e

    def list_files(self, commit: Optional[str] = None) -> List[str]:
        if commit:
            out = self._run("ls-tree", "-r", "--name-only", commit)
        else:
            out = subprocess.check_output(["git", "--no-pager", "ls-files"], cwd=self.repo_path, stderr=subprocess.STDOUT, timeout=60).decode("utf-8")
        return [line.strip() for line in out.splitlines() if line.strip()]

    def get_head(self) -> str:
        return self._run("rev-parse", "HEAD").strip()

# ----------------------- diff + translation -----------------------
@dataclass
class Hunk:
    base_start: int
    base_len: int
    head_start: int
    head_len: int

@dataclass
class FileDiff:
    path: str
    hunks: List[Hunk]
    is_deleted: bool = False
    old_path: Optional[str] = None
    new_path: Optional[str] = None

class DiffUtil:
    @staticmethod
    def parse_unified_diff(text: str) -> List[FileDiff]:
        """
        Robust unified-diff parser that:
         - extracts old/new paths from `diff --git a/... b/...`
         - recognizes `deleted file mode` even if it appears before ---/+++ lines
         - creates FileDiff for deletions even when no hunks are present
        """
        file_diffs: List[FileDiff] = []
        current: Optional[FileDiff] = None

        # "parsed" values from the `diff --git` header — best initial source for paths
        parsed_old: Optional[str] = None
        parsed_new: Optional[str] = None

        # per-file deleted marker (can be set by 'deleted file mode' line)
        deleted_flag = False

        for raw_line in io.StringIO(text):
            line = raw_line.rstrip("\n")

            # new file-diff header
            if line.startswith("diff --git "):
                # finalize previous fd
                if current:
                    current.is_deleted = deleted_flag or (current.new_path == "/dev/null")
                    if current.is_deleted and current.old_path:
                        current.path = current.old_path
                    file_diffs.append(current)

                # reset state for next file
                current = None
                parsed_old = None
                parsed_new = None
                deleted_flag = False

                # try to parse "diff --git a/foo b/foo" for immediate path info
                m = re.match(r"^diff --git a/(?P<old>.+?) b/(?P<new>.+)$", line)
                if m:
                    parsed_old = m.group("old")
                    parsed_new = m.group("new")
                continue

            # old path line (--- a/...)
            if line.startswith("--- a/"):
                old_path = line[6:].strip()
                # record old path if not already set by header
                if parsed_old is None:
                    parsed_old = old_path
                # set current if deletion was seen earlier and no current yet
                if deleted_flag and current is None:
                    # use the parsed_old (or old_path) as the deleted path
                    path_to_use = parsed_old or old_path
                    current = FileDiff(path=path_to_use, hunks=[], is_deleted=True, old_path=path_to_use, new_path="/dev/null")
                continue

            # new path line (+++ b/...)
            if line.startswith("+++ b/"):
                new_path = line[6:].strip()
                if parsed_new is None:
                    parsed_new = new_path
                # create FileDiff if not already created (we now have a usable path)
                if current is None:
                    # if new_path == /dev/null => deletion; prefer old path for `path`
                    if new_path == "/dev/null":
                        path_to_use = parsed_old or None
                        current = FileDiff(path=path_to_use or "/dev/null", hunks=[], is_deleted=True, old_path=parsed_old, new_path="/dev/null")
                    else:
                        current = FileDiff(path=new_path, hunks=[], is_deleted=False, old_path=parsed_old, new_path=new_path)
                else:
                    # update current metadata if it already exists
                    current.new_path = new_path
                    current.old_path = current.old_path or parsed_old
                continue

            # explicit deleted-file marker
            if line.startswith("deleted file mode"):
                deleted_flag = True
                logger.info("file delete found")
                # If we already have parsed_old (from header) and no current, create FileDiff now
                if current is None:
                    path_to_use = parsed_old or parsed_new or None
                    # Use parsed_old if possible (old path is canonical for deletions)
                    if path_to_use:
                        current = FileDiff(path=path_to_use, hunks=[], is_deleted=True, old_path=parsed_old, new_path="/dev/null")
                    # otherwise delay creation until we see --- a/ or +++ b/
                continue

            # hunk header
            if line.startswith("@@ ") and current is not None:
                pattern = r"@@ -(?P<bstart>\d+)(?:,(?P<blen>\d+))? \+(?P<hstart>\d+)(?:,(?P<hlen>\d+))? @@.*"
                m = re.match(pattern, line)
                if m:
                    blen = int(m.group('blen')) if m.group('blen') else 1
                    hlen = int(m.group('hlen')) if m.group('hlen') else 1
                    current.hunks.append(
                        Hunk(
                            int(m.group('bstart')),
                            blen,
                            int(m.group('hstart')),
                            hlen
                        )
                    )
                continue

        # finalize last file diff
        if current:
            current.is_deleted = deleted_flag or (current.new_path == "/dev/null")
            if current.is_deleted and current.old_path:
                current.path = current.old_path
            file_diffs.append(current)

        # keep file diffs that have path and either hunks or is_deleted
        return [fd for fd in file_diffs if fd.path and (fd.hunks or fd.is_deleted)]

    @staticmethod
    def translate(r: Range, hunks: List[Hunk]) -> Range:
        start, end = r.start_line, r.end_line
        rel = r.relocalize
        for h in hunks:
            delta = h.head_len - h.base_len
            base_end = h.base_start + h.base_len
            if base_end <= start:
                start += delta
                end += delta
            elif h.base_start < end and base_end > start:
                rel = True
        return Range(start, end, r.byte_start, r.byte_end, rel)

# ----------------------- chunking -----------------------
_EXT_TO_LANG = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".java": "java", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp", ".go": "go", ".rs": "rust",
}

_TS_NODE_TYPES = {
    "javascript": ["function_declaration", "method_definition", "class_declaration"],
    "typescript": ["function_declaration", "method_definition", "class_declaration"],
    "java": ["class_declaration", "interface_declaration", "method_declaration"],
    "go": ["function_declaration", "method_declaration", "type_declaration"],
    "c": ["function_definition"], 
    "cpp": ["function_definition", "class_specifier"],
    "rust": ["function_item", "impl_item", "trait_item", "struct_item", "enum_item"],
    "python": ["class_definition", "function_definition", "decorated_definition"], # 👈 Python 추가
}

# Extensions we intentionally skip during chunking (binary Excel files, etc.).
_SKIP_EXTENSIONS = {".xlsx", ".xls", ".xlsm", ".xlsb"}

class Chunker:
    @staticmethod
    def for_language(path: str) -> str:
        return _EXT_TO_LANG.get(os.path.splitext(path)[1].lower(), "generic")

    @staticmethod
    def chunks(
        src: str,
        path: str,
        repo: str,
        stack_type: Optional[str] = None,
        plugins: Optional[List[ChunkPlugin]] = None,
    ) -> List[Chunk]:
        """
        메인 청킹 진입점: Tree-sitter를 우선 사용하고, 실패 시 generic_chunks로 폴백합니다.
        """
        ext = os.path.splitext(path)[1].lower()
        if ext in _SKIP_EXTENSIONS:
            logger.info("Skipping chunking for unsupported binary file type: %s", path)
            return []

        plugins = plugins or []

        # Allow plugins to preprocess source (e.g., normalize XML) when they claim support.
        pre_src = src
        for plugin in plugins:
            try:
                if plugin.supports(path, stack_type):
                    pre_src = plugin.preprocess(pre_src, path, repo)
            except Exception:
                logger.exception("chunk plugin preprocess failed for %s", path)

        lang = Chunker.for_language(path)
        
        # 1. Tree-sitter 사용 가능하고, 해당 언어를 지원하는 경우
        if _TS_AVAILABLE and lang in _TS_NODE_TYPES:
            # ts_chunks 내부에서 오류를 처리하고 generic_chunks로 안전하게 폴백합니다.
            chunks = Chunker.ts_chunks(pre_src, path, repo, lang)
        else:
            # 2. Tree-sitter를 사용할 수 없거나 지원하지 않는 언어인 경우
            chunks = Chunker.generic_chunks(pre_src, path, repo)

        # Plugin post-processing and extra chunks.
        for plugin in plugins:
            try:
                if plugin.supports(path, stack_type):
                    chunks = plugin.postprocess(chunks, path, repo)
                    extra = plugin.extra_chunks(pre_src, path, repo)
                    if extra:
                        chunks.extend(extra)
            except Exception:
                logger.exception("chunk plugin postprocess failed for %s", path)

        return chunks

    # ----------------------- py_chunks 제거됨 -----------------------

    @staticmethod
    def ts_chunks(src: str, path: str, repo: str, lang: str, max_content_chars: int = MAX_CONTENT_CHARS) -> List[Chunk]:
        if not _TS_AVAILABLE or lang not in _TS_NODE_TYPES:
            # 이 코드는 Chunker.chunks에서 이미 걸러지지만, 방어 코드로 유지
            return Chunker.generic_chunks(src, path, repo)
        
        # Guard against misconfiguration that would produce empty chunks.
        max_content_chars = max(256, max_content_chars or MAX_CONTENT_CHARS)

        try:
            language = get_language(lang)
        except Exception as e:
            logger.error(f"Failed to load Tree-sitter language '{lang}': {e}")
            return Chunker.generic_chunks(src, path, repo)
        
        parser = Parser()
        parser.set_language(language)
        b = src.encode("utf-8")

        logger.info("ts chunk")

        try:
            tree = parser.parse(b)
            node_types = set(_TS_NODE_TYPES[lang])
            out = []

            def enclosing_block(n):
                p = n.parent
                # Python을 포함한 다양한 언어의 블록 타입을 처리하도록 업데이트
                # Python: class_definition, function_definition
                while p and p.type not in ("class_declaration", "impl_item", "trait_item", "struct_item", "enum_item", "function_definition", "class_definition"): 
                    p = p.parent
                return p

            def split_into_chunks(text: str, start_line: int, end_line: int, byte_start: int, byte_end: int, symbol: str, logical_id_base: str, sig_hash: str, block_id: str, block_range: Optional[Range], part_num: int = 1) -> List[Chunk]:
                """긴 텍스트를 max_content_chars 단위로 분할하여 여러 Chunk 생성"""
                chunks = []
                current_pos = 0
                while current_pos < len(text):
                    split_end = min(current_pos + max_content_chars, len(text))
                    # 줄 경계에서 자르기 위해 마지막 \n 찾기
                    last_nl = text.rfind('\n', current_pos, split_end)
                    if last_nl > current_pos:
                        split_end = last_nl + 1
                    sub_text = text[current_pos:split_end]
                    
                    # 위치 조정 (대략적; 정확한 byte/line 계산 필요 시 _line_to_byte 등 사용)
                    sub_start_line = start_line + text[:current_pos].count('\n')
                    sub_end_line = start_line + text[:split_end].count('\n')
                    sub_byte_start = byte_start + current_pos
                    sub_byte_end = byte_start + split_end
                    
                    part_symbol = f"{symbol}_part{part_num}"
                    part_logical_id = f"{logical_id_base}_part{part_num}"
                    part_content_hash = sha256(sub_text.encode())
                    
                    chunks.append(Chunk(
                        logical_id=part_logical_id, symbol=part_symbol, path=path, language=lang,
                        range=Range(sub_start_line, sub_end_line, sub_byte_start, sub_byte_end),
                        content=sub_text,
                        content_hash=part_content_hash, sig_hash=sig_hash,
                        block_id=block_id, block_range=block_range,
                    ))
                    
                    current_pos = split_end
                    part_num += 1
                
                if len(chunks) > 1:
                    logger.warning(f"Split {path}:{start_line}-{end_line} into {len(chunks)} chunks due to length limit")
                
                return chunks

            def walk(n):
                # ... (기존 walk 로직 유지) ...
                if n.type in node_types:
                    start_line = n.start_point[0] + 1
                    end_line = n.end_point[0] + 1
                    byte_start = n.start_byte
                    byte_end = n.end_byte
                    text = b[byte_start:byte_end].decode("utf-8", errors="ignore")
                    
                    # Tree-sitter는 구문 오류 시 ERROR 노드를 삽입하지만, 전체 AST는 파싱하므로
                    # 이 로직은 SyntaxError에 강건합니다.
                    
                    name = _ts_first_identifier(n, b) or n.type
                    prefix = "class:" if "class" in n.type or n.type in ("struct_item", "enum_item", "trait_item", "class_definition") else "func:"
                    symbol = f"{prefix}{name}"
                    logical_id = f"{repo}:{path}#{symbol}"
                    content_hash = sha256(text.encode())
                    sig_hash = sha256((n.type + ":" + name).encode())
                    blk = enclosing_block(n)
                    block_id = block_range = None
                    if blk:
                        bstart = blk.start_point[0] + 1
                        bend = blk.end_point[0] + 1
                        b_beg = blk.start_byte
                        b_end = blk.end_byte
                        bname = _ts_first_identifier(blk, b) or blk.type
                        block_id = f"block:{blk.type}:{bname}"
                        block_range = Range(bstart, bend, b_beg, b_end)
                    
                    # 길이 제한 체크 및 분할
                    if len(text) > max_content_chars:
                        logger.info(f"ts text split chunk : {len(text)}")
                        out.extend(split_into_chunks(
                            text, start_line, end_line, byte_start, byte_end,
                            symbol, logical_id, sig_hash, block_id, block_range
                        ))
                    else:
                        out.append(Chunk(
                            logical_id=logical_id, symbol=symbol, path=path, language=lang,
                            range=Range(start_line, end_line, byte_start, byte_end), content=text,
                            content_hash=content_hash, sig_hash=sig_hash, block_id=block_id, block_range=block_range,
                        ))
                for i in range(n.child_count):
                    walk(n.children[i])
            walk(tree.root_node)
            return out or Chunker.generic_chunks(src, path, repo) # 청크를 찾지 못하면 generic으로 폴백

        except Exception as e:
            # Tree-sitter 자체 오류(예: 메모리 문제, I/O)만 여기서 처리하고 폴백
            logger.error(f"Tree-sitter catastrophic error for {path}: {e}")
            return Chunker.generic_chunks(src, path, repo)
            
    @staticmethod
    def generic_chunks(src: str, path: str, repo: str, lines_per_chunk: int = CHUNK_LINES, max_content_chars: int = MAX_CONTENT_CHARS) -> List[Chunk]:
        max_content_chars = max(256, max_content_chars or MAX_CONTENT_CHARS)
        out = []
        lines = src.splitlines(True)
        i = 0
        line_no = 1
        joined = ''.join(lines)

        def split_into_chunks(text: str, start_line: int, end_line: int, byte_start: int, byte_end: int, symbol: str, logical_id_base: str, sig_hash: str, block_id: Optional[str] = None, block_range: Optional[Range] = None, part_num: int = 1) -> List[Chunk]:
            """긴 텍스트를 max_content_chars 단위로 분할하여 여러 Chunk 생성"""
            chunks = []
            current_pos = 0
            while current_pos < len(text):
                split_end = min(current_pos + max_content_chars, len(text))
                # 줄 경계에서 자르기 위해 마지막 \n 찾기
                last_nl = text.rfind('\n', current_pos, split_end)
                if last_nl > current_pos:
                    split_end = last_nl + 1
                sub_text = text[current_pos:split_end]
                
                # 위치 조정
                sub_start_line = start_line + text[:current_pos].count('\n')
                sub_end_line = start_line + text[:split_end].count('\n')
                sub_byte_start = byte_start + current_pos
                sub_byte_end = byte_start + split_end
                
                part_symbol = f"{symbol}_part{part_num}"
                part_logical_id = f"{logical_id_base}_part{part_num}"
                part_content_hash = sha256(sub_text.encode())
                
                chunks.append(Chunk(
                    logical_id=part_logical_id, symbol=part_symbol, path=path, language="generic",
                    range=Range(sub_start_line, sub_end_line, sub_byte_start, sub_byte_end),
                    content=sub_text,
                    content_hash=part_content_hash, sig_hash=sig_hash,
                    block_id=block_id, block_range=block_range,
                ))
                
                current_pos = split_end
                part_num += 1
            
            if len(chunks) > 1:
                logger.warning(f"Split {path}:{start_line}-{end_line} into {len(chunks)} chunks due to length limit")
            
            return chunks

        while i < len(lines):
            segment = lines[i:i + lines_per_chunk]
            text = ''.join(segment)
            start = line_no
            end = line_no + len(segment) - 1
            byte_start = _line_to_byte(joined, start)
            byte_end = _line_to_byte(joined, end + 1)
            symbol = f"range:{start:04d}-{end:04d}"
            logical_id = f"{repo}:{path}#{symbol}"
            sig_hash = sha256(symbol.encode())
            
            # 길이 제한 체크 및 분할
            if len(text) > max_content_chars:
                logger.info(f"gen split chunk : {len(text)}")
                out.extend(split_into_chunks(
                    text, start, end, byte_start, byte_end,
                    symbol, logical_id, sig_hash
                ))
            else:
                content_hash = sha256(text.encode())
                out.append(Chunk(
                    logical_id=logical_id, symbol=symbol, path=path, language="generic",
                    range=Range(start, end, byte_start, byte_end), content=text,
                    content_hash=content_hash, sig_hash=sig_hash,
                ))
            i += lines_per_chunk
            line_no += len(segment)
        return out

# ----------------------- relocalizer -----------------------
class Relocalizer:
    @staticmethod
    def exact_relocate(base_slice: str, head_src: str) -> Optional[Tuple[int, int]]:
        idx = head_src.find(base_slice)
        if idx == -1:
            return None
        return _byte_to_line(head_src, idx), _byte_to_line(head_src, idx + len(base_slice)) - 1

    @staticmethod
    def fuzzy_relocate(base_slice: str, head_src: str, window: int = 2000) -> Optional[Tuple[int, int]]:
        base_hash = sha256(base_slice.encode())
        for s in range(0, max(0, len(head_src) - window + 1), max(1, window // 4)):
            win = head_src[s:s + window]
            if sha256(win.encode()) == base_hash:
                return _byte_to_line(head_src, s), _byte_to_line(head_src, s + len(win)) - 1
        return None

# ----------------------- indexer -----------------------
class Indexer:
    def __init__(
        self,
        repo_path: str,
        repo_name: str,
        embeddings: Embeddings,
        store: VectorStore,
        collection: str,
        payload_plugins: Optional[List[PayloadPlugin]] = None,
        base_payload: Optional[Dict[str, Any]] = None,
        chunk_plugins: Optional[List[ChunkPlugin]] = None,
        stack_type: Optional[str] = None,
    ):
        self.repo_path = repo_path
        self.repo_name = repo_name
        self.emb = embeddings
        self.store = store
        self.collection = collection
        self.git = GitCLI(repo_path)
        self.payload_plugins = payload_plugins or []
        self.base_payload = base_payload or {}
        self.chunk_plugins = chunk_plugins or []
        self.stack_type = stack_type

    def _build_payload(self, c: Chunk, branch: str, commit_sha: str) -> Dict[str, Any]:
        unique_identifier = f"{c.logical_id}:{c.content_hash}"
        # [변경 코멘트: Qdrant ID 최종 수정 (UUID 방식)] 
        # Qdrant가 요구하는 UUID 형식의 ID를 생성하기 위해 UUID v5를 사용합니다. 
        # UUID v5는 입력 문자열(unique_identifier)이 동일하면 항상 동일한 UUID를 생성합니다.
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_identifier))
        payload = {
            "point_id": point_id,
            "logical_id": c.logical_id,
            "repo": self.repo_name,
            "path": c.path,
            "symbol": c.symbol,
            "branch": branch,
            "commit_sha": commit_sha,
            "content_hash": c.content_hash,
            "sig_hash": c.sig_hash,
            "is_latest": True,
            "lines": [c.range.start_line, c.range.end_line],
            "byte_range": [c.range.byte_start, c.range.byte_end],
            "language": c.language,
            "neighbors": c.neighbors,
            "block_id": c.block_id,
            "block_lines": [c.block_range.start_line, c.block_range.end_line] if c.block_range else None,
            "block_byte_range": [c.block_range.byte_start, c.block_range.byte_end] if c.block_range else None,
        }
        if self.base_payload:
            payload.update(self.base_payload)
        for plugin in self.payload_plugins:
            try:
                extra = plugin.build_payload(c, branch, commit_sha)
            except Exception:
                logger.exception("payload plugin failed for %s", c.path)
                continue
            if extra:
                payload.update(extra)
        return payload

    def full_index(self, head: str, branch: str = "main"):
        files = self.git.list_files(head)
        logger.info(f"full index files {files}")
        to_embed = []
        for path in files:
            head_src = self.git.show_file(head, path) or ""
            logger.debug(f"full index head src {head_src}")
            if head_src:
                to_embed.extend(
                    Chunker.chunks(
                        head_src,
                        path,
                        self.repo_name,
                        stack_type=self.stack_type,
                        plugins=self.chunk_plugins,
                    )
                )
        if to_embed:
            texts = [c.content for c in to_embed]
            vectors = self.emb.embed(texts)
            points = [PointStruct(id=self._build_payload(c, branch, head)["point_id"], vector=v, payload=self._build_payload(c, branch, head)) for c, v in zip(to_embed, vectors)]
            self.store.upsert_points(points)

    def index_commit(self, base: str, head: Optional[str] = None, branch: str = "main"):
        commit_sha = head or base  # For local mode, use base commit
        if head is None:
            # Local mode: changes to working tree
            status_out = self.git._run("status", "--porcelain", "--untracked-files=no")
 
            # None 방지 (이전 수정 유지)
            status_out = status_out or "" 
            
            logger.info(f"local mode status out : {status_out}")
            
            # 변경된 파일 경로 목록 추출
            # [수정 코멘트: 로컬 변경 감지 오류 수정]
            # X (Staged) 또는 Y (Unstaged) 컬럼에 변경을 나타내는 문자(M, A, D, R 등)가 있는지 확인합니다.
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
                # [변경 코멘트: 논리적 오류 수정] 로컬 변경사항이 없으면 즉시 종료해야 합니다.
                raise RuntimeError("no changes in working directory")
            diff_text = self.git.diff_to_working(base, changed_paths)
            file_diffs = DiffUtil.parse_unified_diff(diff_text)
            commit_sha = base
        else:
            # Commit mode
            diff_text = self.git.diff_unified_0(base, head)
            logger.info(f"[DEBUG] Raw Diff Text received (first 500 chars): \n{diff_text[:500]}")
            file_diffs = DiffUtil.parse_unified_diff(diff_text)
            # [변경 코멘트: 디버깅 로직 추가] diff가 없는데도 file_diffs가 비어 있다면 diff_text를 출력합니다.
            if not file_diffs and diff_text.strip():
                logger.error(f"Diff parsing failed, file_diffs is empty but diff_text is NOT. Raw diff: {diff_text[:500]}")
            # [변경 코멘트: 논리적 오류 수정] 커밋 모드에서 변경사항이 없으면 즉시 종료해야 합니다.
            if not file_diffs:
                raise RuntimeError("no changes between commits")
        # [변경 코멘트: 로직 개선] 원래 잘못된 위치에 있던 로컬 모드 로직을 삭제하고, 
        # file_diffs를 얻는 로직을 모드별로 분리했습니다.
        # for fd in file_diffs: ... 는 아래로 이동.

        # 공통 인덱싱 로직 (diff/file_diffs가 준비된 후)
        logger.info(f"diff test {diff_text[:500]}")
        logger.info(f"file diffs {file_diffs}")

        for fd in file_diffs:
            # 로컬 모드에서는 head_src를 파일 시스템에서 읽어옵니다.
            # 커밋 모드에서는 git.show_file(head, ...)를 사용합니다.
            head_src = self.git.show_file(head, fd.path) or ""
            logger.debug(f"index commit : head_src {head_src}")
            
            if not head_src:
                continue
            try:
                # [수정 코멘트: Chunking 오류 방지] 구문 분석 오류 발생 시 로깅 후 다음 파일로 넘어감
                head_chunks = {
                    c.symbol: c
                    for c in Chunker.chunks(
                        head_src,
                        fd.path,
                        self.repo_name,
                        stack_type=self.stack_type,
                        plugins=self.chunk_plugins,
                    )
                }
                logger.info(f"Successfully chunked {fd.path}. Chunks count: {len(head_chunks)}") # b 대신 성공 로그 표시
            except Exception as e:
                logger.error(f"FATAL: Failed to chunk file {fd.path} due to: {e.__class__.__name__}: {e}")
                # 이 파일은 인덱싱 대상에서 제외하고 다음 루프로 넘어갑니다.
                continue

            base_src = self.git.show_file(base, fd.path) or ""
            logger.debug(f"index commit : base_src {base_src}")
            to_embed = []
            to_update_only_pos = []
            for _, ch in head_chunks.items():
                prev_points = self.store.scroll_by_logical(ch.logical_id, is_latest=True)
                if not prev_points:
                    to_embed.append(ch)
                    continue
                prev = prev_points[0]
                if prev.payload.get("content_hash") != ch.content_hash:
                    to_embed.append(ch)
                else:
                    translated = DiffUtil.translate(ch.range, fd.hunks)
                    if translated.relocalize and base_src:
                        br = prev.payload.get("byte_range", [ch.range.byte_start, ch.range.byte_end])
                        base_slice = base_src[br[0]:br[1]] if 0 <= br[0] <= br[1] <= len(base_src) else ""
                        if base_slice:
                            loc = Relocalizer.exact_relocate(base_slice, head_src) or Relocalizer.fuzzy_relocate(base_slice, head_src)
                            if loc:
                                translated = Range(loc[0], loc[1], br[0], br[1], False)
                    to_update_only_pos.append((ch, translated))
            if to_embed:
                texts = [c.content for c in to_embed]
                vectors = self.emb.embed(texts)
                points = []
                for c, v in zip(to_embed, vectors):
                    olds = self.store.scroll_by_logical(c.logical_id, is_latest=True)
                    if olds:
                        self.store.set_payload([p.id for p in olds], {"is_latest": False})
                    payload = self._build_payload(c, branch, commit_sha)
                    points.append(PointStruct(id=payload["point_id"], vector=v, payload=payload))
                self.store.upsert_points(points)
            if to_update_only_pos:
                ids = [p.id for _, olds in [(None, self.store.scroll_by_logical(ch.logical_id, is_latest=True)) for ch, _ in to_update_only_pos] for p in olds if olds]
                if ids:
                    # Batch update positions (simplified; group by unique range if needed)
                    for ch, r in to_update_only_pos:
                        olds = self.store.scroll_by_logical(ch.logical_id, is_latest=True)
                        if olds:
                            self.store.set_payload([p.id for p in olds], {"lines": [r.start_line, r.end_line]})

# ----------------------- retriever -----------------------
class Retriever:
    def __init__(self, store: VectorStore, emb: Embeddings, repo_path: Optional[str] = None):
        self.store = store
        self.emb = emb
        self.repo_path = repo_path
        logger.info(f"repo path for Retriever {repo_path}")

# [변경 코멘트: 함수 인자 오류 수정] repo 인자가 함수 정의에 누락되어 있습니다.
    def search(
        self,
        query: str,
        k: int = 5,
        branch: str = "main",
        repo: Optional[str] = None,
        stack_type: Optional[str] = None,
        component_type: Optional[str] = None,
        screen_name: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        vec = self.emb.embed([query])[0]
        
        # [변경 코멘트: 논리적 오류 수정] 필터 생성 로직이 두 번 반복되고 'repo: Optional[str] = None'이 필터 정의 내부에 잘못 삽입되어 있었습니다.
        must_conditions = [
            FieldCondition(key="is_latest", match=MatchValue(value=True)),
            FieldCondition(key="branch", match=MatchValue(value=branch)),
        ]
        if repo:
            must_conditions.append(FieldCondition(key="repo", match=MatchValue(value=repo)))
        if stack_type:
            must_conditions.append(FieldCondition(key="stack_type", match=MatchValue(value=stack_type)))
        if component_type:
            must_conditions.append(FieldCondition(key="component_type", match=MatchValue(value=component_type)))
        if screen_name:
            must_conditions.append(FieldCondition(key="screen_name", match=MatchValue(value=screen_name)))
        if tags:
            must_conditions.append(FieldCondition(key="tags", match=MatchAny(any=sorted(set(tags)))))

        filt = Filter(must=must_conditions)
        
        hits = self.store.search(vec, k=k, filt=filt)
        results = []

        logger.debug(f"hits {hits}")

        for h in hits:
            item = {"id": h.id, "score": h.score, "payload": h.payload}
            p = h.payload
            if self.repo_path and p.get("path") and p.get("block_lines"):
                file_path = os.path.join(self.repo_path, p["path"])
                logger.debug(f"file path for Retriever{file_path}")
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        src = f.read()
                    bl = p["block_lines"]
                    if bl:
                        b_start, b_end = bl
                        b_beg = _line_to_byte(src, b_start)
                        b_fin = _line_to_byte(src, b_end + 1)
                        item["block_text"] = src[b_beg:b_fin]
                        l = p.get("lines")
                        if l:
                            s, e = l
                            s_b = _line_to_byte(src, s)
                            e_b = _line_to_byte(src, e + 1)
                            item["focus_text"] = src[s_b:e_b]
                except Exception as e:
                    logger.error(f"file open error {e}")
                    pass
            results.append(item)
        return results

# ----------------------- helpers -----------------------
def _line_to_byte(src: str, line_no: int) -> int:
    if line_no <= 1:
        return 0
    idx = 0
    cur = 1
    while cur < line_no and idx < len(src):
        nl = src.find("\n", idx)
        if nl == -1:
            return len(src)
        idx = nl + 1
        cur += 1
    return idx

def _byte_to_line(src: str, byte_off: int) -> int:
    return src.count("\n", 0, max(0, min(byte_off, len(src)))) + 1

def _py_signature_str(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        bases = [ast.unparse(b) if hasattr(ast, 'unparse') else getattr(b, 'id', '?') for b in node.bases]
        return f"class {node.name}({','.join(bases)})"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = [a.arg for a in node.args.args]
        ret = ast.unparse(node.returns) if getattr(node, 'returns', None) and hasattr(ast, 'unparse') else ''
        return f"def {node.name}({','.join(args)})->{ret}"
    return ""

def _ts_first_identifier(node, bsrc: bytes) -> Optional[str]:
    for c in node.children:
        if getattr(c, 'field_name', None) in ("name", "declarator", "type", "trait", "item"):
            txt = bsrc[c.start_byte:c.end_byte].decode('utf-8', errors='ignore')
            m = re.search(r"[A-Za-z_][A-Za-z0-9_]*", txt)
            if m:
                return m.group(0)
        if c.type in ("identifier", "type_identifier", "scoped_identifier"):
            txt = bsrc[c.start_byte:c.end_byte].decode('utf-8', errors='ignore')
            m = re.search(r"[A-Za-z_][A-Za-z0-9_]*", txt)
            if m:
                return m.group(0)
    return None


# ----------------------- example CLI -----------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", nargs="?", help="path to git repo")
    parser.add_argument("base", nargs="?", help="base commit sha or ref")
    parser.add_argument("head", nargs="?", help="head commit sha or ref")
    parser.add_argument("--collection", default="auto", help="Qdrant collection name or 'auto'")
    parser.add_argument("--env", default=os.getenv("APP_ENV", "dev"), help="environment tag for auto collection name")
    parser.add_argument("--repo-name", default="repo")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--qdrant-key", default=os.getenv("QDRANT_API_KEY", ""))
    parser.add_argument("--tei-base", default=os.getenv("TEI_BASE_URL", "http://localhost:8080/v1"))
    parser.add_argument("--tei-model", default=os.getenv("TEI_MODEL", os.getenv("TEI_MODEL_NAME", "text-embedding-3-large")))
    parser.add_argument("--dim", type=int, default=None, help="vector dimension when creating collection")
    args = parser.parse_args()

    if not (args.repo and args.head):
        raise SystemExit("Usage: python git-aware-code-indexer.py <repo> [<base>] <head> [--collection ...]")

    emb = Embeddings(base_url=args.tei_base, model=args.tei_model, api_key=os.getenv("OPENAI_API_KEY", ""))
    if args.collection == "auto":
        modelslug = re.sub(r"[^a-z0-9]+", "", args.tei_model.lower())
        repopart = re.sub(r"[^a-z0-9]+", "-", args.repo_name.lower())
        args.collection = f"{args.env}-{modelslug}-{repopart}"
    store = VectorStore(collection=args.collection, url=args.qdrant_url, api_key=args.qdrant_key, dim=args.dim)

    indexer = Indexer(repo_path=args.repo, repo_name=args.repo_name, embeddings=emb, store=store, collection=args.collection)
    if store.is_new:
        indexer.full_index(head=args.head)
    else:
        base = args.base or ""
        if not base:
            raise SystemExit("Base commit required for incremental indexing.")
        indexer.index_commit(base=base, head=args.head)

    r = Retriever(store, emb, repo_path=args.repo)
    out = r.search("initialize controller", k=5)
    print(json.dumps(out, ensure_ascii=False, indent=2))
