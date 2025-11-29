"""Shared structural edge types and helpers."""

from .edge_types import EdgePayload, EdgeType
from .builder import build_edge, dedupe_edges, merge_edges, normalize_id, normalize_layout_target
from .plugins import StructuralEdgePlugin

__all__ = [
    "EdgePayload",
    "EdgeType",
    "build_edge",
    "dedupe_edges",
    "merge_edges",
    "normalize_id",
    "normalize_layout_target",
    "StructuralEdgePlugin",
]
