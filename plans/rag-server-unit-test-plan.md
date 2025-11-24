## RAG Server Unit Test Plan (derived from `server/test_git_rag_api.py`)

### Objectives
- Preserve the existing end-to-end coverage of repository indexing/search flows while migrating them into structured, repeatable unit/integration tests.
- Validate Git-aware indexing behavior for clean, commit-based, and working-tree states, plus search relevance after each step.
- Ensure state tracking (`index_state.json`) and noop handling remain stable across reruns.

### Environment & Fixtures
- Launch dependencies via compose before testing: `docker compose -f docker-compose.embedding.yml up -d --build` then `docker compose -f docker-compose.rag.yml up -d --build`.
- Target API base URL: `http://localhost:8000`.
- Register repositories through `/registry` before indexing, matching README guidance; use in-memory/temp SQLite via `REGISTRY_DB_DIR` for isolation.
- Temporary repo fixture: `/workspace/myrepo/test_repo` on branch `head`; configure Git `user.email`/`user.name` and add repo to `safe.directory`.
- State file location: `index_state.json` (ensure cleanup between tests).
- Use Requests client with short timeouts; handle streaming responses for indexing endpoints (consume lines, assert final JSON payload).

### Registry Coverage (aligns with `tests/test_repository_registry.py`)
- Exercise CRUD and webhook flows via API and direct `RepositoryRegistry` class:
  - Create repo with `repo_id`, `collection_name`, `embedding_model`, optional `archived`.
  - Fetch by id and update fields (e.g., `name`, `archived`).
  - Update `last_indexed_commit` and verify persistence.
  - Webhook creation path `/registry/webhook` populates missing repos.
  - Delete repo and confirm 204 + absence.
- Add lightweight unit coverage for index-router/registry integration (e.g., `tests/test_index_registry_alignment.py`):
  - Ensure `_ensure_repo_registry_entry` calls `ensure_repository` with `Config` defaults (collection and embedding model).
  - Assert archived repositories raise HTTP 400 before indexing proceeds.
- Ensure registry-based metadata is consulted during indexing/search flows (end-to-end tests should retrieve repo config through registry rather than bypassing it).

### Test Cases
- **Full index (baseline)**
  - Create initial commit containing `file_a.py` with `initialize_context`.
  - POST `/repos/{id}/index/full`; expect `status=completed`, `last_commit` == initial SHA.
  - Assert `index_state.json` maps repo id to initial SHA.
  - POST `/search` for “initialize context function”; expect hit in `file_a.py`.
- **Commit-based incremental index**
  - Modify `file_a.py` (change return text, add `setup_db`) and add `file_b.py` with `Controller` class; commit changes.
  - POST `/repos/{id}/index/update`; expect `status=completed`, `last_commit` == new SHA.
  - POST `/search` for “Controller class definition”; expect hit in `file_b.py`.
  - Repeat `/index/update` with no new commits; expect `status=noop`.
- **Working-tree incremental index**
  - Edit `file_b.py` without committing (e.g., add `run` method).
  - GET `/repos/{id}/status`; expect `modified` includes `file_b.py`.
  - POST `/repos/{id}/index/update` with working tree changes; expect `status=completed`, `last_commit` unchanged (new commit SHA).
  - POST `/search` for “Controller run method”; expect hit reflecting local change.
  - Revert working tree (`git checkout -- file_b.py`); GET status should be clean; `/index/update` should return `status=noop`.

### Structure & Implementation Notes
- Convert the procedural script into pytest functions/fixtures:
  - Session-scoped fixture to spin up the temp repo and capture SHAs.
  - Helper fixture for `api_call` that supports streaming responses for `/index/*`.
  - Fixture to reset `index_state.json` per test run.
- Add fixtures for temporary registry DB and FastAPI client (`TestClient`) to cover router-level CRUD in parallel with direct class tests.
- Mark tests that require live Qdrant/embedding as integration (e.g., `@pytest.mark.integration`) for selective execution.
- Keep logs minimal; prefer assertions with clear failure messages.

### Validation & Execution
- Primary command: `docker compose -f docker-compose.rag.yml run --rm rag-server python server/test_git_rag_api.py` (legacy) and `docker compose -f docker-compose.rag.yml run --rm rag-server pytest tests/<new_file>.py`.
- Run after changes to Git plumbing, indexing logic, streaming response handling, or search payload shape.
