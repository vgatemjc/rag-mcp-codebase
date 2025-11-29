# Structural Edge Plugins

This guide explains how to add structural edge extraction for new stack types using the shared helpers in `server/services/edges/`.

## Core Types
- `EdgeType` enum: `BINDS_LAYOUT`, `NAV_DESTINATION`, `NAV_ACTION`, `NAVIGATES_TO`, `USES_VIEWMODEL`, `CALLS_API` (extend if a new stack needs more).
- `EdgePayload`: `{"type": str, "target": str, "meta": dict | optional}`; keep targets normalized and lowercase where possible.
- Helpers: `build_edge(type, target, meta=None)`, `dedupe_edges(edges)`, `merge_edges(*lists)`, `normalize_id(value)`, `normalize_layout_target(name)`.
- Plugin protocol: `StructuralEdgePlugin.build_edges(self, chunk: Chunk) -> List[EdgePayload]`.

## Indexer Integration
`Indexer` accepts `edge_plugins` (list of `StructuralEdgePlugin`). During indexing it:
1) Builds payload via payload plugins.
2) Calls each edge plugin for the current chunk.
3) Dedupes combined edges and attaches them to the payload.

Routers select plugins per stack; see `server/routers/index_router.py::_stack_plugins`.

## Building a Plugin (example: web_frontend)
```python
# server/services/web_edges.py
from server.services.edges import StructuralEdgePlugin, build_edge, EdgeType, normalize_id

class WebFrontendEdgePlugin(StructuralEdgePlugin):
    """Extract simple navigation/layout edges from web chunks."""

    def build_edges(self, chunk):
        edges = []
        content = getattr(chunk, "content", "") or ""
        path = chunk.path.lower()

        # Link/route detection
        for match in re.findall(r'href="/([^"#?]+)', content):
            edges.append(build_edge(EdgeType.NAVIGATES_TO, normalize_id(match)))

        # Template binding
        if path.endswith(".html"):
            edges.append(build_edge(EdgeType.BINDS_LAYOUT, f"template/{path}"))

        return edges
```

## Wiring a New Stack
1) Create chunk/payload/edge plugins for the stack (payload plugin may add `stack_type`, `component_type`, etc.).
2) Update router stack selection to include the edge plugin:
```python
# server/routers/index_router.py
from server.services.web_edges import WebFrontendEdgePlugin, WebPayloadPlugin, WebChunkPlugin

def _stack_plugins(stack_type):
    if stack_type == "web_frontend":
        chunk = WebChunkPlugin()
        payload = WebPayloadPlugin(stack_type)
        edge = WebFrontendEdgePlugin()
        return [chunk], [payload], [edge], {"stack_type": stack_type}
    ...
```
3) Ensure the registry `stack_type` matches your new stack so the router selects these plugins.

## Testing Expectations
- Add unit tests for normalization and deduping logic.
- Add plugin-specific tests that feed sample chunks and assert emitted edges.
- Prefer an integration test that indexes a fixture repo and asserts `edges` appear in search/MCP responses.

## Conventions
- Keep targets stable and lowercase; use repo-relative paths where helpful.
- Do not add new Qdrant filter fields for edges; attach edges to payloads instead.
- Use logging sparingly; avoid print statements.***
