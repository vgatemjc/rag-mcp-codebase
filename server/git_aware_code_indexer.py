from __future__ import annotations
import os
import io
import re
import ast
import json
import hashlib
import subprocess
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any

from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, Filter, FieldCondition, MatchValue
import requests

# Optional Tree-sitter
_TS_AVAILABLE = False
try:
    from tree_sitter import Parser
    from tree_sitter_languages import get_language
    _TS_AVAILABLE = True
except Exception:
    _TS_AVAILABLE = False

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

    def __post_init__(self):
        if self.neighbors is None:
            self.neighbors = []

# ----------------------- embedding -----------------------
class Embeddings:
    def __init__(self, base_url: str, model: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def embed(self, texts: List[str]) -> List[List[float]]:
        url = f"{self.base_url}/embeddings"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = requests.post(url, headers=headers, json={"model": self.model, "input": texts}, timeout=120)
        resp.raise_for_status()
        return [item["embedding"] for item in resp.json()["data"]]

# ----------------------- qdrant store -----------------------
class VectorStore:
    def __init__(self, collection: str, url: str, api_key: Optional[str] = None, dim: Optional[int] = None):
        self.collection = collection
        self.client = QdrantClient(url=url, api_key=api_key)
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
        self.client.upsert(collection_name=self.collection, points=[PointStruct(id=point_id, vector=vector, payload=payload)])

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
        self.repo_path = repo_path

    def _run(self, *args: str) -> str:
        try:
            out = subprocess.check_output(["git", "--no-pager", *args], cwd=self.repo_path, stderr=subprocess.STDOUT, timeout=60)
            return out.decode("utf-8", errors="ignore")
        except FileNotFoundError:
            raise RuntimeError("`git` CLI not found. Install Git or run in an environment with Git available.")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"git command timeout: {' '.join(args)}")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"git command failed: {' '.join(args)}\n{e.output.decode('utf-8', errors='ignore')}")

    def diff_unified_0(self, base: str, head: str) -> str:
        return self._run("diff", f"{base}..{head}", "--unified=0", "--ignore-blank-lines", "--ignore-space-at-eol", "--no-color")

    def show_file(self, commit: str, path: str) -> Optional[str]:
        try:
            return self._run("show", f"{commit}:{path}")
        except RuntimeError:
            return None

    def list_files(self, commit: Optional[str] = None) -> List[str]:
        if commit:
            out = self._run("ls-tree", "-r", "--name-only", commit)
        else:
            out = subprocess.check_output(["git", "--no-pager", "ls-files"], cwd=self.repo_path, stderr=subprocess.STDOUT, timeout=60).decode("utf-8")
        return [line.strip() for line in out.splitlines() if line.strip()]

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

class DiffUtil:
    @staticmethod
    def parse_unified_diff(text: str) -> List[FileDiff]:
        file_diffs = []
        current = None
        current_path = None
        for line in io.StringIO(text):
            if line.startswith("diff --git "):
                if current:
                    file_diffs.append(current)
                current = None
                current_path = None
                continue
            if line.startswith("+++ b/"):
                current_path = line.strip()[6:]
                current = FileDiff(path=current_path, hunks=[])
                continue
            if line.startswith("@@ ") and current is not None:
                m = re.match(r"@@ -(?P<bstart>\d+),(?P<blen>\d+) \+(?P<hstart>\d+),(?P<hlen>\d+) @@", line)
                if m:
                    current.hunks.append(Hunk(int(m['bstart']), int(m['blen']), int(m['hstart']), int(m['hlen'])))
        if current:
            file_diffs.append(current)
        return [fd for fd in file_diffs if fd.path and fd.hunks]

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
    "c": ["function_definition"], "cpp": ["function_definition", "class_specifier"],
    "rust": ["function_item", "impl_item", "trait_item", "struct_item", "enum_item"],
}

class Chunker:
    @staticmethod
    def for_language(path: str) -> str:
        return _EXT_TO_LANG.get(os.path.splitext(path)[1].lower(), "generic")

    @staticmethod
    def py_chunks(src: str, path: str, repo: str) -> List[Chunk]:
        out = []
        tree = ast.parse(src)
        parent = {}
        def _walk(n, p=None):
            parent[n] = p
            for ch in ast.iter_child_nodes(n):
                _walk(ch, n)
        _walk(tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = getattr(node, 'name', 'anon')
                start = node.lineno
                end = getattr(node, 'end_lineno', node.lineno)
                byte_start = _line_to_byte(src, start)
                byte_end = _line_to_byte(src, end + 1)
                text = src[byte_start:byte_end]
                symbol = ("class:" if isinstance(node, ast.ClassDef) else "func:") + name
                logical_id = f"{repo}:{path}#{symbol}"
                content_hash = sha256(text.encode())
                sig = _py_signature_str(node)
                sig_hash = sha256(sig.encode())
                block_id = block_range = None
                par = parent.get(node)
                while par and not isinstance(par, ast.ClassDef):
                    par = parent.get(par)
                if isinstance(par, ast.ClassDef):
                    bstart = par.lineno
                    bend = getattr(par, 'end_lineno', par.lineno)
                    b_beg = _line_to_byte(src, bstart)
                    b_end = _line_to_byte(src, bend + 1)
                    block_id = f"class:{par.name}"
                    block_range = Range(bstart, bend, b_beg, b_end)
                out.append(Chunk(
                    logical_id=logical_id, symbol=symbol, path=path, language="python",
                    range=Range(start, end, byte_start, byte_end), content=text,
                    content_hash=content_hash, sig_hash=sig_hash, block_id=block_id, block_range=block_range,
                ))
        return out or Chunker.generic_chunks(src, path, repo)

    @staticmethod
    def ts_chunks(src: str, path: str, repo: str, lang: str) -> List[Chunk]:
        if not _TS_AVAILABLE or lang not in _TS_NODE_TYPES:
            return Chunker.generic_chunks(src, path, repo)
        try:
            language = get_language(lang)
        except Exception:
            return Chunker.generic_chunks(src, path, repo)
        parser = Parser()
        parser.set_language(language)
        b = src.encode("utf-8")
        tree = parser.parse(b)
        node_types = set(_TS_NODE_TYPES[lang])
        out = []

        def enclosing_block(n):
            p = n.parent
            while p and p.type not in ("class_declaration", "impl_item", "trait_item", "struct_item", "enum_item"):
                p = p.parent
            return p

        def walk(n):
            if n.type in node_types:
                start_line = n.start_point[0] + 1
                end_line = n.end_point[0] + 1
                byte_start = n.start_byte
                byte_end = n.end_byte
                text = b[byte_start:byte_end].decode("utf-8", errors="ignore")
                name = _ts_first_identifier(n, b) or n.type
                prefix = "class:" if "class" in n.type or n.type in ("struct_item", "enum_item", "trait_item") else "func:"
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
                out.append(Chunk(
                    logical_id=logical_id, symbol=symbol, path=path, language=lang,
                    range=Range(start_line, end_line, byte_start, byte_end), content=text,
                    content_hash=content_hash, sig_hash=sig_hash, block_id=block_id, block_range=block_range,
                ))
            for i in range(n.child_count):
                walk(n.children[i])
        walk(tree.root_node)
        return out or Chunker.generic_chunks(src, path, repo)

    @staticmethod
    def generic_chunks(src: str, path: str, repo: str, lines_per_chunk: int = 120) -> List[Chunk]:
        out = []
        lines = src.splitlines(True)
        i = 0
        line_no = 1
        joined = ''.join(lines)
        while i < len(lines):
            segment = lines[i:i + lines_per_chunk]
            text = ''.join(segment)
            start = line_no
            end = line_no + len(segment) - 1
            byte_start = _line_to_byte(joined, start)
            byte_end = _line_to_byte(joined, end + 1)
            symbol = f"range:{start:04d}-{end:04d}"
            logical_id = f"{repo}:{path}#{symbol}"
            out.append(Chunk(
                logical_id=logical_id, symbol=symbol, path=path, language="generic",
                range=Range(start, end, byte_start, byte_end), content=text,
                content_hash=sha256(text.encode()), sig_hash=sha256(symbol.encode()),
            ))
            i += lines_per_chunk
            line_no += len(segment)
        return out

    @staticmethod
    def chunks(src: str, path: str, repo: str) -> List[Chunk]:
        lang = Chunker.for_language(path)
        if lang == "python":
            return Chunker.py_chunks(src, path, repo)
        if lang in _TS_NODE_TYPES:
            return Chunker.ts_chunks(src, path, repo, lang)
        return Chunker.generic_chunks(src, path, repo)

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
    def __init__(self, repo_path: str, repo_name: str, embeddings: Embeddings, store: VectorStore, collection: str):
        self.repo_path = repo_path
        self.repo_name = repo_name
        self.emb = embeddings
        self.store = store
        self.collection = collection
        self.git = GitCLI(repo_path)

    def _build_payload(self, c: Chunk, branch: str, head: str) -> Dict[str, Any]:
        return {
            "point_id": f"{c.logical_id}:{c.content_hash}",
            "logical_id": c.logical_id, "repo": self.repo_name, "path": c.path, "symbol": c.symbol,
            "branch": branch, "commit_sha": head, "content_hash": c.content_hash, "sig_hash": c.sig_hash,
            "is_latest": True, "lines": [c.range.start_line, c.range.end_line],
            "byte_range": [c.range.byte_start, c.range.byte_end], "language": c.language,
            "neighbors": c.neighbors, "block_id": c.block_id,
            "block_lines": [c.block_range.start_line, c.block_range.end_line] if c.block_range else None,
            "block_byte_range": [c.block_range.byte_start, c.block_range.byte_end] if c.block_range else None,
        }

    def full_index(self, head: str, branch: str = "main"):
        files = self.git.list_files(head)
        to_embed = []
        for path in files:
            head_src = self.git.show_file(head, path) or ""
            if head_src:
                to_embed.extend(Chunker.chunks(head_src, path, self.repo_name))
        if to_embed:
            texts = [c.content for c in to_embed]
            vectors = self.emb.embed(texts)
            points = [PointStruct(id=self._build_payload(c, branch, head)["point_id"], vector=v, payload=self._build_payload(c, branch, head)) for c, v in zip(to_embed, vectors)]
            self.store.client.upsert(collection_name=self.collection, points=points)

    def index_commit(self, base: str, head: str, branch: str = "main"):
        diff_text = self.git.diff_unified_0(base, head)
        file_diffs = DiffUtil.parse_unified_diff(diff_text)
        for fd in file_diffs:
            head_src = self.git.show_file(head, fd.path) or ""
            if not head_src:
                continue
            head_chunks = {c.symbol: c for c in Chunker.chunks(head_src, fd.path, self.repo_name)}
            base_src = self.git.show_file(base, fd.path) or ""
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
                    point_id = f"{c.logical_id}:{c.content_hash}"
                    olds = self.store.scroll_by_logical(c.logical_id, is_latest=True)
                    if olds:
                        self.store.set_payload([p.id for p in olds], {"is_latest": False})
                    payload = self._build_payload(c, branch, head)
                    points.append(PointStruct(id=point_id, vector=v, payload=payload))
                self.store.client.upsert(collection_name=self.collection, points=points)
            if to_update_only_pos:
                ids = []
                for c, r in to_update_only_pos:
                    olds = self.store.scroll_by_logical(c.logical_id, is_latest=True)
                    if olds:
                        ids.extend([p.id for p in olds])
                if ids:
                    self.store.set_payload(ids, {"lines": [r.start_line, r.end_line] for _, r in to_update_only_pos[0]} )  # Simplified, assuming uniform

# ----------------------- retriever -----------------------
class Retriever:
    def __init__(self, store: VectorStore, emb: Embeddings, repo_path: Optional[str] = None):
        self.store = store
        self.emb = emb
        self.repo_path = repo_path

    def search(self, query: str, k: int = 5, branch: str = "main") -> List[Dict[str, Any]]:
        vec = self.emb.embed([query])[0]
        filt = Filter(must=[
            FieldCondition(key="is_latest", match=MatchValue(value=True)),
            FieldCondition(key="branch", match=MatchValue(value=branch)),
        ])
        hits = self.store.search(vec, k=k, filt=filt)
        results = []
        for h in hits:
            item = {"id": h.id, "score": h.score, "payload": h.payload}
            p = h.payload
            if self.repo_path and p.get("path") and p.get("block_lines"):
                file_path = os.path.join(self.repo_path, p["path"])
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
                except Exception:
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

# ----------------------- tests -----------------------
def _run_selftests():
    import textwrap
    # Test 1: translate no overlap
    r = Range(100, 120, 0, 0)
    hunks = [Hunk(10, 3, 10, 10)]
    tr = DiffUtil.translate(r, hunks)
    assert tr.start_line == 107 and tr.end_line == 127 and not tr.relocalize, "translate shift failed"
    # Test 2: translate overlap triggers relocalize
    r2 = Range(15, 20, 0, 0)
    hunks2 = [Hunk(18, 4, 18, 1)]
    tr2 = DiffUtil.translate(r2, hunks2)
    assert tr2.relocalize, "overlap should relocalize"
    # Test 3: python chunker extracts symbols
    src_py = textwrap.dedent('''
    class Foo:
        def a(self, x):
            return x

    def b(y:int)->int:
        return y+1
    ''')
    chs = Chunker.py_chunks(src_py, "mod.py", "repo")
    kinds = sorted(c.symbol.split(":")[0] for c in chs)
    assert kinds == ["class", "func"], f"unexpected symbols {kinds}"
    # Test 4: Tree-sitter JS (if available)
    if _TS_AVAILABLE:
        src_js = textwrap.dedent('''
        class C { m(x) { return x } }
        function f(y){ return y+1 }
        ''')
        chs_js = Chunker.ts_chunks(src_js, "a.js", "repo", "javascript")
        assert any(s.symbol.startswith("class:") for s in chs_js), "expected class chunk in JS"
        assert any(s.symbol.startswith("func:") for s in chs_js), "expected func chunk in JS"
        # Test 5: Tree-sitter Rust (if available)
        src_rs = textwrap.dedent('''
        struct S { v: i32 }
        impl S { fn m(&self, x:i32) -> i32 { x + 1 } }
        fn f(y:i32) -> i32 { y + 2 }
        ''')
        chs_rs = Chunker.ts_chunks(src_rs, "lib.rs", "repo", "rust")
        assert any(s.symbol.startswith("func:") for s in chs_rs), "expected function chunk in Rust"
        assert any("struct:" in s.symbol or s.symbol.startswith("class:") or s.language=="rust" for s in chs_rs), "expected struct/impl chunk in Rust"
    print("All selftests passed.")

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
    parser.add_argument("--selftest", action="store_true", help="run built-in tests and exit")
    args = parser.parse_args()

    if args.selftest:
        _run_selftests()
        raise SystemExit(0)

    if not (args.repo and args.head):
        raise SystemExit("Usage: python git-aware-code-indexer.py <repo> [<base>] <head> [--collection ...]")

    emb = Embeddings(base_url=args.tei_base, model=args.tei_model, api_key=os.getenv("OPENAI_API_KEY", ""))
    if args.collection == "auto":
        modelslug = re.sub(r"[^a-z0-9]+", "", args.tei_model.lower())
        args.collection = f"{args.env}-{modelslug}" if args.env else modelslug
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