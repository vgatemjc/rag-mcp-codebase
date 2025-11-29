import json
import os
from typing import Iterable, List, Optional

from .edge_types import EdgePayload, EdgeType


def normalize_id(value: Optional[str]) -> Optional[str]:
    """Normalize id-like targets (strip @/+ prefixes, lower-case)."""
    if value is None:
        return None
    cleaned = value
    if "/" in cleaned:
        cleaned = cleaned.split("/", 1)[1]
    cleaned = cleaned.lstrip("@+")
    return cleaned.lower() if cleaned else None


def normalize_layout_target(name: Optional[str]) -> Optional[str]:
    """Normalize layout names to repo-relative form (layout/<name>.xml)."""
    if not name:
        return None
    base = os.path.splitext(os.path.basename(name))[0]
    return f"layout/{base}.xml"


def build_edge(edge_type: EdgeType, target: str, meta: Optional[dict] = None) -> EdgePayload:
    payload: EdgePayload = {"type": edge_type.value if isinstance(edge_type, EdgeType) else str(edge_type), "target": target}
    if meta:
        payload["meta"] = meta
    return payload


def dedupe_edges(edges: Iterable[EdgePayload]) -> List[EdgePayload]:
    """Deduplicate edges by type/target/meta content."""
    seen = set()
    result: List[EdgePayload] = []
    for edge in edges:
        meta = edge.get("meta")
        meta_key = json.dumps(meta, sort_keys=True) if isinstance(meta, dict) else str(meta)
        key = (edge.get("type"), edge.get("target"), meta_key)
        if key in seen:
            continue
        seen.add(key)
        result.append(edge)
    return result


def merge_edges(*edge_lists: Iterable[EdgePayload]) -> List[EdgePayload]:
    merged: List[EdgePayload] = []
    for edges in edge_lists:
        merged.extend(edges)
    return dedupe_edges(merged)
