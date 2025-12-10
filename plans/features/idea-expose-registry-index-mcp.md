# Expose Registry + Indexing via MCP Tools

## Problem / user outcome
- when we start agent like codex in a repo root.
- agent can check whether the repo is registred to rag and indexed
- if not agent can register the repo to rag server and do full index
- agent is working on the repo and update the codes and commit to the git then agent can do index update to rag to sync the latest update.

## Proposed solution
- Ship an MCP tool bundle that can 1) read registry/index status for the current repo, 2) create or update the registry entry if missing, and 3) trigger full/update/working-tree indexing against the RAG API.
- Resolve `repo_id` from the working directory git basename (with optional override) so the agent can run from any repo root without extra config.
- Stream indexing progress back through MCP so agents can surface status to users (processed file counts, current file, commit hash) and bail on errors.
- Keep the FastAPI routers as the single source of truth; MCP should call the existing registry/index/status endpoints instead of duplicating indexing logic.

## User stories / flows
- As an agent starting in an unknown repo, I can ask “is this repo registered?” and get the current registry + index status (collection, model, last indexed commit) without leaving the editor.
- If the repo is not registered, I can run a single MCP command that registers it (defaults from env, optional stack type) and immediately kicks off a full index.
- After I commit or edit files, I can request an incremental index update (commit diff or working tree) via MCP and see progress/finish/error updates.
- When troubleshooting RAG answers, I can re-run status to confirm the last index job, its mode, and any error messages.

## Tech notes
- MCP entrypoint: extend `server/git_rag_mcp.py` with new tools (`registry_status`, `registry_register`, `index_full`, `index_update`, `index_working_tree`) that call the FastAPI endpoints at `RAG_URL`.
- API touchpoints: `/registry` (POST/PUT/GET), `/repos/{repo_id}/index/full`, `/repos/{repo_id}/index/update`, `/repos/{repo_id}/index/working-tree`, `/repos/{repo_id}/index/status` (responses shaped by `IndexStatus` model).
- Registry/index plumbing already lives in `server/services/repository_registry.py`, `server/routers/index_router.py`, and `server/routers/status_router.py`; reuse their payloads and error handling. Use `server/services/state_manager.py` helpers when computing repo paths for working-tree indexes.
- Config: MCP worker already reads `RAG_URL`, `REPO_ROOT`, `MCP_PORT`; registry defaults come from API `Config` (`COLLECTION`, `EMB_MODEL`, optional `STACK_TYPE`). Allow overrides per command but keep sane defaults to stay idempotent.
- Risks/constraints: need to handle long-running StreamingResponse bodies without blocking MCP; ensure progress events stay small. Avoid creating duplicate registry rows; prefer `ensure_repository`. Respect archived repos and surface friendly MCP errors.

## Validation
- Success criteria: MCP tools can report registry/index status, register a new repo, and trigger full/update/working-tree indexing with visible progress and no duplicate registry rows. Errors (archived repo, missing git repo, server failure) are surfaced clearly.
- Quick test plan: manual MCP run from a sample git repo (`registry_status` → `registry_register` → `index_full` → `index_status`); modify a file and run `index_update` then `semantic_code_search` for the change. Automated: keep `python server/test_git_rag_api.py` and `pytest tests/test_repository_registry.py` green; add a lightweight MCP invocation test that stubs RAG_URL and asserts command responses when implemented.
