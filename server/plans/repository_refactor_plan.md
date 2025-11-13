# Repository Unified Management & Sandbox Enhancement Plan

This plan scopes the refactor required to support a centralized repository registry, per-user sandboxes, and human-readable semantic search assets. All features are designed to operate smoothly with GitHub-hosted repositories that are mirrored into the runtime via worktrees.

## 1. Step-by-step Implementation Plan

### Phase 1 – Repository Registry Backbone
1. Create a persistent metadata store (SQLite + SQLModel) for repositories, sandboxes, and generated reports.
2. Add a FastAPI router `/registry` with CRUD endpoints that manage repository entries synchronized with GitHub webhooks (push, archive, delete).
3. Update the indexing startup flow so that `ensure_collection` and related workers read the registry entry (collection name, embedding model, last indexed Git commit) before touching Qdrant.

### Phase 2 – Sandbox Provisioning & Lifecycle
1. Implement sandbox provisioning endpoints `/registry/{repo_id}/sandboxes` that create Git worktrees rooted at `repos/<repo_id>/users/<user_id>` using the GitHub default branch as a baseline.
2. Record sandbox metadata (creator, parent repo SHA, upstream URL, status) and emit events when users request refresh, diff, or promotion back to GitHub.
3. Build background workers to:
   * poll for upstream GitHub changes and mark sandboxes as stale,
   * optionally fast-forward sandboxes when a user enables auto-sync,
   * prune abandoned sandboxes after configurable TTL.

### Phase 3 – Human-friendly Semantic Search Reports
1. Extend semantic search APIs to accept an `output=markdown` flag that triggers rendering of GitHub-ready reports (query summary, ranked matches, source permalinks).
2. Persist rendered Markdown under `reports/<repo_id>/<timestamp>-<query>.md` and register the artifact in the registry for later retrieval.
3. Enhance MCP tools to list/download latest reports and provide shareable GitHub permalinks when repositories are public.

### Phase 4 – Observability & Operations
1. Add structured logging with repository/sandbox IDs so GitHub Actions logs can link back to registry entries.
2. Surface Prometheus metrics (registry counts, sandbox churn, report generation latency) for monitoring.
3. Provide `/health/registry`, `/health/sandboxes`, and `/health/reports` endpoints consumed by Docker health checks and GitHub Actions smoke tests.

## 2. Existing Functions to Update
- `server/git_rag_api.py`
  - **`ensure_collection`**: consult the registry for the target collection, locking the entry during creation, and persist the last indexed GitHub commit SHA after success.
  - **`index_repo` & related handlers**: require a `repo_id` registered in the registry, resolve sandbox paths from the active request context, and optionally trigger Markdown report generation.
- `server/git_aware_code_indexer.py`
  - **`GitCLI` methods**: add helpers for creating/removing GitHub-linked worktrees, fetching upstream remotes, and reporting sandbox status back to the registry.
  - **`VectorStore` integration points**: write back index metadata (chunk counts, embedding revisions) to the registry after upserts/deletions.
- `server/git_rag_mcp.py`
  - **`semantic_code_search` tool handler**: accept report rendering flags, store the resulting Markdown path, and expose GitHub permalinks when applicable.
  - **`repo_tree_md` handler**: resolve repository root via the registry and respect sandbox isolation.

## 3. New Functions to Add
- `server/repository_registry.py`
  - **`RepositoryRegistry` class**: SQLModel-backed CRUD methods for repositories, sandboxes, and report artifacts, including GitHub webhook ingestion helpers.
  - **`SandboxManager` helper**: orchestrate worktree creation, synchronization, diffing, and cleanup with hooks for GitHub promotion workflows.
- `server/report_renderer.py`
  - **`render_search_report`**: accept semantic search results and produce GitHub-flavored Markdown with headings, permalinks, and file excerpts.
  - **`store_report`**: persist Markdown files, update the registry, and optionally open a draft GitHub Gist or issue comment.
- `server/background_tasks.py`
  - **`sync_sandbox_job`**: scheduled task that checks sandbox freshness against GitHub and triggers background fetch/merge operations.
  - **`cleanup_reports_job`**: archive or delete stale reports based on retention policy, updating the registry accordingly.

## 4. Function Relocations
- Move sandbox Git utility functions (worktree creation, cleanup, diff helpers) from `git_aware_code_indexer.py` into `SandboxManager` within `repository_registry.py` so sandbox lifecycle logic is consolidated.
- Relocate ad-hoc report formatting snippets from `git_rag_mcp.py` (and any similar helpers) into `report_renderer.py` for reuse by both the API and MCP layers.
- Centralize registry write-backs currently sprinkled across API handlers into dedicated methods on `RepositoryRegistry`, reducing cross-module coupling.
