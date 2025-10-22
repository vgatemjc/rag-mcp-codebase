import re
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)

# simple line-based code chunker with overlap
def chunk_code(text: str, max_lines: int = 200, overlap: int = 20) -> List[Tuple[int,int,str]]:
    lines = text.splitlines()
    n = len(lines)
    i = 0
    chunks = []
    logger.debug(f"chunk len : {n}")
    while i < n:
        j = min(i + max_lines, n)
        chunk = "\n".join(lines[i:j])
        chunks.append((i+1, j, chunk))
        if j == n:
            break
        i = j - overlap
    return chunks