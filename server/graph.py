from tree_sitter_languages import get_language, get_parser
from typing import Dict, List, Tuple

# Extract function spans and names for common langs
LANG_MAP = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "java": "java",
    "go": "go",
    "cpp": "cpp",
    "c": "c",
    "rs": "rust",
    "kt": "kotlin",
    "swift": "swift",
}

NODE_TYPES = {
    "python": ["function_definition"],
    "javascript": ["function_declaration", "method_definition"],
    "typescript": ["function_declaration", "method_definition"],
    "java": ["method_declaration"],
    "go": ["function_declaration", "method_declaration"],
    "cpp": ["function_definition"],
    "c": ["function_definition"],
    "rust": ["function_item"],
    "kotlin": ["function_declaration"],
    "swift": ["function_declaration"],
}

def list_functions(lang: str, code: bytes) -> List[Tuple[str, int, int]]:
    key = LANG_MAP.get(lang)
    if not key:
        return []
    parser = get_parser(key)
    tree = parser.parse(code)
    types = NODE_TYPES.get(lang, [])
    results = []
    def walk(node):
        if node.type in types:
            name = None
            for c in node.children:
                if c.type in ("identifier", "name"):
                    name = code[c.start_byte:c.end_byte].decode('utf-8', errors='ignore')
                    break
            start = node.start_point[0] + 1
            end = node.end_point[0] + 1
            results.append((name or "<anon>", start, end))
        for ch in node.children:
            walk(ch)
    walk(tree.root_node)
    return results
