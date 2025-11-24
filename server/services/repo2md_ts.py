#!/usr/bin/env python3
"""
repo2md_ts.py
- tree‑sitter 기반 파싱
- .gitignore 반영
- depth 0 : 트리만
- depth 1 : 클래스/구조체 정의만
- depth 2 : 함수 정의까지 (스니펫 제외)
- depth 3 : 코드 스니펫까지 포함
"""
import os
import sys
import pathlib
import argparse
import textwrap
from tree_sitter import Parser
from tree_sitter_languages import get_language
from typing import Callable, Optional, List, Dict, Any

LANGUAGES = {
    'python': 'python',
    'javascript': 'javascript',
    'typescript': 'typescript',
    'java': 'java',
    'c': 'c',
    'cpp': 'cpp',
    'go': 'go',
    'rust': 'rust',
    'ruby': 'ruby',
}

# ----------------------------------------------------------------------
# 2. 파서 캐시
# ----------------------------------------------------------------------
language_objs = {lang: get_language(lang) for lang in LANGUAGES}
parser_cache: dict[str, Parser] = {}

def get_parser_for_lang(lang: str) -> Parser:
    if lang not in parser_cache:
        parser = Parser()
        parser.set_language(language_objs[lang])
        parser_cache[lang] = parser
    return parser_cache[lang]

# ----------------------------------------------------------------------
# 3. 언어 별 node‑type 목록
# ----------------------------------------------------------------------
class_types = {
    'python': {'class_definition'},
    'javascript': {'class_declaration', 'class_expression'},
    'typescript': {'class_declaration', 'interface_declaration', 'enum_declaration'},
    'java': {'class_declaration', 'record_declaration', 'interface_declaration', 'annotation_declaration'},
    'c': {'class_specifier', 'struct_specifier', 'union_specifier', 'enum_specifier'},
    'cpp': {'class_specifier', 'struct_specifier', 'enum_specifier'},
    'go': {'struct_type', 'type_spec'},              # `go` 에는 별도의 class_type 가 없으므로 `struct_type` 으로 취급
    'rust': {'struct_item', 'enum_item', 'impl_item', 'trait_item'},
    'ruby': {'class', 'module'},
}

func_types = {
    'python': {'function_definition'},
    'javascript': {'function_declaration', 'method_definition', 'function'},
    'typescript': {'function_declaration', 'method_signature', 'method_declaration'},
    'java': {'method_declaration', 'constructor_declaration', 'initializer_declaration'},
    'c': {'function_definition'},
    'cpp': {'function_definition', 'method_definition'},
    'go': {'func_declaration', 'func_type'},
    'rust': {'function_item', 'fn_item'},
    'ruby': {'def', 'method', 'lambda'},
}

# ----------------------------------------------------------------------
# 4. 정의 추출
# ----------------------------------------------------------------------
def extract_definitions(source: bytes, lang: str):
    """
    Returns a nested list of definitions:
        [
            {
                "type": "class_definition",
                "name": "MyClass",
                "start": 10,
                "end": 200,
                "children": [ ... ]      # functions, nested classes
            },
            { ... }                     # top‑level functions
        ]
    """
    parser = get_parser_for_lang(lang)
    tree = parser.parse(source)
    root = tree.root_node
    
    def get_definition_name(source, node, lang):
        """노드 타입별로 정의 이름 노드를 찾아 정확한 이름을 추출합니다."""
        # Tree-sitter 쿼리를 사용하거나, 일반적인 자식 노드 탐색 로직을 사용할 수 있습니다.
        # 대부분의 언어에서 'identifier' 또는 'name' 필드를 가진 자식 노드가 이름입니다.
        
        # 간략화된 노드 이름 추출 (Identifier 노드를 찾음)
        name_node = None
        for child in node.children:
            if child.type == 'identifier':
                return source[child.start_byte:child.end_byte].decode(errors="replace").strip()

        if name_node:
            return source[name_node.start_byte:name_node.end_byte].decode(errors="replace")

        # 이름 노드를 찾지 못하면 기존 방식(첫 줄)으로 폴백
        return source[node.start_byte:node.end_byte].decode(errors="replace").splitlines()[0].strip()
    
    def walk(node, parent):
        """Recursively collect nodes that match `class_types` or `func_types`."""
        if node.type in class_types.get(lang, set()):
            cls = {
                "type": node.type,
                "name": get_definition_name(source, node, lang),
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_byte": node.start_byte,
                "end_byte": node.end_byte,
                "children": [],
            }
            parent.append(cls)
            # walk inside the class body
            for child in node.children:
                walk(child, cls["children"])
            return
        elif node.type in func_types.get(lang, set()):
            fn = {
                "type": node.type,
                "name": get_definition_name(source, node, lang),
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "start_byte": node.start_byte,
                "end_byte": node.end_byte,
            }
            parent.append(fn)
            return

        # other children (e.g., nested classes/functions)
        for child in node.children:
            walk(child, parent)

    top: list[dict] = []
    walk(root, top)
    return top

# ----------------------------------------------------------------------
# 5. .gitignore 로드
# ----------------------------------------------------------------------
def load_gitignore(root: pathlib.Path) -> Optional[Callable[[str], bool]]:
    """
    Returns a function f(rel_path) -> bool that tells whether a path
    (relative to *root*) should be ignored.

    1. Tries to import `gitignore_parser.parse_gitignore`.
    2. Falls back to `pathspec` (gitwildmatch) if the former is missing.
    3. Returns None if there is no .gitignore or a failure occurs.
    """
    gitignore_file = root / ".gitignore"
    if not gitignore_file.is_file():
        return None

    # ---- Fallback: pathspec (gitwildmatch) -------------------------
    try:
        import pathspec  # type: ignore
        with open(gitignore_file, encoding="utf-8") as f:
            raw = f.read().splitlines()

            # Clean patterns: strip comments, inline comments and empty lines
            patterns = []
            for line in raw:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "#" in line:                # inline comment
                    line = line.split("#", 1)[0].strip()
                if line:
                    patterns.append(line)

        spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
        # pathspec’s API works with `match_file()` – wrap it in a callable
        return lambda rel: spec.match_file(rel)
#        return lambda rel: spec.match_file(rel) or spec.match_file(rel + os.sep)
    except Exception as e:
        print(f"loading error {e}")
        return None

# ----------------------------------------------------------------------
# 2. Determine if a path should be ignored
# ----------------------------------------------------------------------
def is_ignored(path: pathlib.Path, ignore_func: Optional[Callable[[str], bool]], root: pathlib.Path) -> bool:
    """
    `ignore_func` is either:
        * a callable returned by `gitignore_parser.parse_gitignore`
        * a callable that wraps a `pathspec` PathSpec
        * None (no .gitignore)

    The function always receives `path` as an absolute `Path`,
    `root` is the repository root.
    """
    if ignore_func is None:
        return False

    # Compute the path *relative* to the repo root, in Posix form
    rel_path = os.path.relpath(path, root).replace(os.sep, "/")
    # Git‑ignore treats directories with a trailing slash specially
    if path.is_dir() and not rel_path.endswith("/"):
        rel_path += "/"

    try:
        is_it_ignored = ignore_func(rel_path)
        return is_it_ignored
    except Exception as e:
        # If something goes wrong, be conservative and ignore nothing
        print(f"무시 함수 실행 중 예외 발생: {e}")
        return False

# ----------------------------------------------------------------------
# 6. 파일 별 Markdown 생성
# ----------------------------------------------------------------------
def make_md_for_file(path: pathlib.Path, max_lines: int, def_depth: int):
    if def_depth == 0:
        return None          # 정의는 표시하지 않음

    content = path.read_bytes()
    ext = path.suffix.lower()
    lang_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
    }
    lang = lang_map.get(ext)
    if not lang:
        return None

    definitions = extract_definitions(content, lang)

    # depth 1 : 클래스/구조체만
    # depth >=2 : 함수까지 포함
    # depth >=3 : 스니펫까지 표시
    def allowed(node_type: str, depth: int) -> bool:
        """depth 1 → 클래스만, depth ≥ 2 → 클래스+함수"""
        if depth == 1:
            return node_type in class_types.get(lang, set())
        return node_type in class_types.get(lang, set()) or \
               node_type in func_types.get(lang, set())

    md_lines = [f"### `{path.name}`", ""]
    # --------------------------------------------------------------------
    # Recursive helper that formats a definition node
    def format_node(node: Dict[str, Any], indent: str = "") -> None:
        if not allowed(node["type"], def_depth):
            return

        snippet = content[node["start_byte"]:node["end_byte"]].decode(errors="replace")
        first_line = snippet.splitlines()[0].strip()
        md_lines.append(f"{indent}- **{node['type']}** ({node['start_line']}-{node['end_line']}): `{first_line}`")

        # 스니펫(depth=3) 추가
        if def_depth >= 3 and "children" in node:
            md_lines.append(f"{indent}  ```{lang}")
            md_lines.extend(f"{indent}  {l}" for l in snippet.splitlines()[:max_lines])
            md_lines.append(f"{indent}  ```")
            md_lines.append("")  # 빈 줄

        # 재귀: nested children
        if "children" in node:
            for child in node["children"]:
                # 한 단계 더 들여쓰기: 공백 두 개 + `-`
                format_node(child, indent + "  ")
    for d in definitions:
        format_node(d, indent="  ")

    return "\n".join(md_lines)

# ----------------------------------------------------------------------
# 7. 리포트 트리 및 정의 생성
# ----------------------------------------------------------------------
def walk_repo(root: pathlib.Path, def_depth: int, max_lines: int):
    md = ["# Repository Tree & Definitions", ""]
    gitignore_spec = load_gitignore(root)

    def recurse(p: pathlib.Path, level: int):
        indent = "   " * level
        for entry in sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            if entry.name.startswith('.'):
                continue
            if gitignore_spec and is_ignored(entry, gitignore_spec, root):
                continue

            if entry.is_dir():
                md.append(f"{indent}├─ {entry.name}/")
                recurse(entry, level + 1)
            else:
                md.append(f"{indent}├─ {entry.name}")
                frag = make_md_for_file(entry, max_lines, def_depth)
                if frag:
                    md.append(textwrap.indent(frag, indent + "│   "))

    recurse(root, 0)
    return "\n".join(md)

# CHANGED: 외부에서 간편하게 호출 가능한 wrapper 추가
def generate_repo_md(path: str, depth: int = 3, max_lines: int = 10) -> str:
    """
    Convenience wrapper to generate the Markdown report for `path`.
    Returns the markdown string. This is intended for programmatic use
    (e.g., called by an MCP tool) instead of invoking CLI.

    Parameters
    ----------
    path : str
        Path to repository root.
    depth : int
        Depth as defined in CLI (0..3).
    max_lines : int
        Max snippet lines when depth >= 3.
    """
    root = pathlib.Path(path).resolve()
    return walk_repo(root, def_depth=depth, max_lines=max_lines)

# ----------------------------------------------------------------------
# 8. CLI
# ----------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Tree‑Sitter + .gitignore → Markdown 변환",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("path", help="리포트 경로")
    parser.add_argument(
        "-d",
        "--depth",
        type=int,
        default=3,
        choices=[0, 1, 2, 3],
        help="정의 표시 깊이 (0: 트리만, 1: 클래스/구조체, 2: 함수까지, 3: 스니펫까지)",
    )
    parser.add_argument(
        "-m",
        "--max-lines",
        type=int,
        default=10,
        help="스니펫에 표시할 최대 줄 수",
    )
    args = parser.parse_args()

    root = pathlib.Path(args.path).resolve()
    if not root.is_dir():
        print(f"❌ {root} 은(는) 디렉터리가 아닙니다.", file=sys.stderr)
        sys.exit(1)

    print(walk_repo(root, args.depth, args.max_lines))