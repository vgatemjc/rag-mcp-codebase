# MCP Tool Quickstart for Android (for downstream LLMs, incl. gpt-oss)

Purpose: help an LLM drive the MCP tools to verify Android structural edges (navgraph, ViewModel) and layouts in an indexed repo.

## Pre-checks
- Ensure the repo was indexed with Android plugins enabled: set `STACK_TYPE=android_app` or call `/repos/{id}/index/full?stack_type=android_app`.
- Reindex after plugin changes so nav/layout/ViewModel edges are stored.
- MCP `semantic_code_search` output hides payloads; use the RAG `/search` API when you need to see `payload.edges`.

## Core MCP tools
- `semantic_code_search(query, k=8, repo, stack_type, component_type, screen_name, tags)` — semantic search with filters. Set `stack_type="android_app"` when testing Android edges. Payload contains `edges`, but the tool prints only snippet text.
- `search_code(query, k=8, repo)` — grep-style substring search; good for verifying patterns like `viewModels<`.

## Recommended test queries
Run these via MCP (omit `tags`/`component_type` if your driver doesn’t support nulls):

Navgraph edges (NAV_DESTINATION/NAV_ACTION):
```json
{
  "query": "NAV_DESTINATION",
  "repo": "nami-mediagate_mirror",
  "stack_type": "android_app",
  "component_type": "navgraph",
  "k": 5
}
```

ViewModel edges from Kotlin fragments:
```json
{
  "query": "viewModels<",
  "repo": "nami-mediagate_mirror",
  "stack_type": "android_app",
  "tags": ["viewmodel"],
  "k": 8
}
```

Layouts with data binding (if present):
```json
{
  "query": "variable name=\"",
  "repo": "nami-mediagate_mirror",
  "stack_type": "android_app",
  "component_type": "layout",
  "k": 5
}
```

## Seeing edge payloads (when needed)
- The MCP tool doesn’t render edges. To inspect them, call the RAG API directly:
  ```bash
  curl -X POST "$RAG_URL/search" \
    -H "Content-Type: application/json" \
    -d '{"query":"viewModels<","repo_id":"nami-mediagate_mirror","stack_type":"android_app","tags":["viewmodel"],"k":3}'
  ```
  Inspect `payload.edges` in the JSON response.
- If desired, add a temporary `include_payload` flag to `semantic_code_search` to print a compact payload summary; remove before shipping.

## Tips for gpt-oss
- Always pass `stack_type="android_app"` so Android plugins are honored.
- Use `tags`/`component_type` filters to narrow (e.g., `tags:["viewmodel"]`, `component_type:"navgraph"`).
- Prefer the `/search` API for verification steps that require payload fields; avoid guessing whether edges are present.***
