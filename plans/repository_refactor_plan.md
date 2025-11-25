# Repository Unified Management & Sandbox Enhancement Plan

Updated to reflect the post-`create_app` architecture while keeping the remaining sandbox/report work scoped.

## Architecture Snapshot (current)
- FastAPI assembly lives in `server/app.py:create_app`, wiring `Config`, `RepositoryRegistry`, and `Initializer` into `app.state`; `server/main.py` is the uvicorn entrypoint and `server/git_rag_api.py` is a thin shim.
- API routers are split under `server/routers/` (`registry_router.py`, `index_router.py`, `status_router.py`, `search_router.py`) and lean on services + models in `server/services/*` and `server/models/*`.
- Registry storage is SQLModel/SQLite via `server/services/repository_registry.py`; `Repository` rows are used throughout indexing/search flows, while `Sandbox`/`Report` tables exist but are not yet surfaced through routes.
- Embedding/Qdrant clients are created lazily through `server/services/initializers.py`, which also ensures collections (skippable via `SKIP_COLLECTION_INIT`). Index state is tracked in `index_state.json` by `server/services/state_manager.py`.
- Indexing/search rely on `git_aware_code_indexer.py` (GitCLI, Chunker, Indexer, Retriever) with per-request collection/model resolution coming from the registry entry and `Config.REPOS_DIR`/`Config.BRANCH`.
- Tests cover registry CRUD plus end-to-end indexing/search (`tests/test_repository_registry.py`, `tests/test_indexing_integration.py`); registry DB location is controlled with `REGISTRY_DB_DIR` for test isolation.

## 1. Step-by-step Implementation Plan

### Phase 1 – Registry + Router Backbone ✅ Completed
1. **Done:** Adopted the `create_app()` pattern with router/model/service split; `git_rag_api.py` now delegates to `server/app.py`.
2. **Done:** `/registry` CRUD + webhook endpoints backed by SQLModel (`RepositoryRegistry`), with registry lookups guarding indexing/search/status requests.
3. **Done:** Indexing flows sync `last_indexed_commit` between `index_state.json` and the registry, and lazily initialize per-repo collections/clients.

### Phase 2 – Sandbox Provisioning & Lifecycle
1. **Done:** Expose `/registry/{repo_id}/sandboxes` routes that create/list/update `Sandbox` rows and spawn Git worktrees under `REPOS_DIR/<repo_id>/users/<user_id>` from the default branch (see `SandboxManager` + `Sandbox` model updates).
2. Track sandbox metadata (creator, parent SHA, upstream URL, status/auto-sync) and emit events/hooks for refresh, diff, and promotion back to GitHub (metadata persisted; hooks still needed).
3. Background workers to mark stale sandboxes from upstream changes, optionally fast-forward auto-sync sandboxes, and prune abandoned ones after a TTL.

### Phase 3 – Human-friendly Semantic Search Reports
1. Add an `output=markdown` flag to search APIs/MCP tools that renders GitHub-ready reports (query summary, ranked matches, source permalinks).
2. Persist rendered Markdown under `reports/<repo_id>/<timestamp>-<query>.md`, register artifacts in the registry, and list/download via API/MCP.
3. When repos are public, surface shareable permalinks (GitHub blobs/commits) alongside report entries.

### Phase 4 – Observability & Operations
1. Structured logging keyed by repository/sandbox IDs so compose/Actions logs map to registry entries.
2. Prometheus metrics for registry counts, sandbox churn, report generation latency; add `/health/registry`, `/health/sandboxes`, `/health/reports`.
3. Docker health checks and GitHub Action smoke tests should exercise the new health endpoints.

## 2. Existing Functions to Update
- `server/routers/index_router.py`: gate indexing by registry entry, resolve sandbox roots when present, and write index metadata back to both state + registry.
- `server/routers/registry_router.py`: surface sandbox/report CRUD plus webhook handling for sandbox lifecycle events.
- `server/routers/search_router.py`: accept sandbox context and report-rendering flags while continuing to resolve per-repo embeddings/collections via the registry.
- `server/services/git_aware_code_indexer.py`: add worktree helpers (create/remove/status), repo-to-sandbox path resolution, and vector-store write-backs tagged with sandbox/report IDs.
- `server/services/initializers.py` and `server/services/state_manager.py`: ensure collection caching and state sync cover sandbox/report metadata and per-repo overrides.
- `server/git_rag_mcp.py`: wire new sandbox/report capabilities into MCP tools (`semantic_code_search`, `repo_tree_md`, report download/listing).

## 3. New Functions to Add
- `server/services/repository_registry.py`: expand `RepositoryRegistry` with sandbox/report CRUD helpers, bulk archiving, and registry-wide health snapshots.
- `server/services/sandbox_manager.py` (or similar): orchestrate worktree creation/sync/diff/cleanup with hooks for GitHub promotion workflows and TTL pruning.
- `server/report_renderer.py`: `render_search_report` + `store_report` to generate/persist Markdown reports and update the registry (plus optional Gist/issue comment publishing).
- `server/background_tasks.py`: `sync_sandbox_job` for freshness checks/fast-forwards and `cleanup_reports_job` for retention enforcement.

## 4. Function Relocations
- Move sandbox Git helpers (worktree creation, cleanup, diff helpers) out of `git_aware_code_indexer.py` into a dedicated sandbox manager to consolidate lifecycle logic.
- Relocate report formatting currently in MCP/search layers into `report_renderer.py` for reuse by API + MCP.
- Centralize registry write-backs (index metadata, sandbox status, report artifacts) through `RepositoryRegistry` methods to reduce cross-module coupling.

## Testing Notes
- Prefer dockerized tests per `plans/docker-testing-workflow.md` and `tests/DOCKER_TESTING.md`. Example for the new sandbox flow: `HOST_REPO_PATH=$(pwd) docker compose -f docker-compose.rag.yml run --rm -e HOST_REPO_PATH=$(pwd) -e SKIP_COLLECTION_INIT=1 -e QDRANT_ENDPOINT=http://localhost:6333 -e EMB_ENDPOINT=http://localhost:8080 -e EMB_MODEL=text-embedding-3-large -w /workspace/myrepo rag-server pytest tests/test_sandbox_routes.py`.
