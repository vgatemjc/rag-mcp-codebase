from typing import List, Protocol

from .edge_types import EdgePayload

try:
    from server.services.git_aware_code_indexer import Chunk
except Exception:  # pragma: no cover - import guard for typing only
    Chunk = object  # type: ignore


class StructuralEdgePlugin(Protocol):
    """Protocol for stack-specific edge emitters."""

    def build_edges(self, chunk: "Chunk") -> List[EdgePayload]:
        ...
