# Expose Registry + Indexing via MCP Tools - implementation plan

## Scope
- Add MCP tools to `server/git_rag_mcp.py` for registry status, register/upsert, and indexing (full/update/working-tree) against the existing FastAPI API.
- Derive default `repo_id` from the current git repo name with an override param; reuse API defaults for collection/model/stack type.
- Stream indexing progress back through MCP responses; keep FastAPI routers (`index_router`, `status_router`, `registry` endpoints) as the source of truth.

## Work items
- MCP tool surface
  - Add `registry_status(repo_id?)` → GET `/registry/{repo_id}` + `/repos/{repo_id}/index/status` merged summary.
  - Add `registry_register(repo_id?, name?, collection_name?, embedding_model?, stack_type?)` → POST `/registry` (idempotent upsert via API).
  - Add `index_full(repo_id?, stack_type?)`, `index_update(repo_id?, stack_type?)`, `index_working_tree(repo_id?, stack_type?)` → POST to corresponding endpoints; stream response lines to MCP client.
  - Shared helper to resolve repo_id (git basename), build URLs from `RAG_URL`, and send HTTPX requests with timeout + friendly error shaping.
- Progress handling
  - Treat FastAPI StreamingResponse as an async byte stream; yield lines back to MCP as they arrive, preserving `processed_files`, `current_file`, `last_commit`.
  - Include a short final summary message on completion or error.
- Defaults and validation
  - Use registry defaults from API (collection/model/stack type) when inputs are missing; avoid creating duplicates by calling registry `ensure` endpoint via POST.
  - Surface archived/missing repo errors clearly in MCP responses.
- Observability
  - Add concise logging around MCP tool invocations (start/end, repo_id, mode, status code).

## Risks / constraints
- Streaming responses may be large; ensure line-buffered handling and reasonable HTTPX timeouts.
- Keep MCP worker non-blocking; avoid loading entire streams into memory.
- Sandbox git detection: handle non-git directories gracefully and require explicit `repo_id` if unresolved.

## Validation
- Manual: from a sample repo run `registry_status` → `registry_register` (if absent) → `index_full` stream → `index_status`; edit a file and run `index_update` or `index_working_tree` to see updated progress.
- Automated: keep `python server/test_git_rag_api.py` and `pytest tests/test_repository_registry.py` green. Add a minimal MCP worker test (stub `RAG_URL` with httpx MockTransport) covering registry status and a short streamed index response.
