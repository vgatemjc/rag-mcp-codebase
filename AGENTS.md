# Repository Guidelines

## Project Structure & Module Organization
`server/` contains the production code built around the `create_app()` pattern: `app.py` builds the FastAPI instance, `main.py` exposes the `uvicorn` entrypoint, `config.py` owns env parsing, routers live under `server/routers/`, Pydantic schemas under `server/models/`, and service logic under `server/services/` (Git/indexer helpers, repository registry, repo2md tree-sitter chunking, and the initializer/state utilities). `git_rag_api.py` remains as a thin compatibility shim that re-exports the new app. The MCP worker lives in `server/git_rag_mcp.py`, and configuration defaults stay in `server/config.yaml`. Operational helpers live in `script/` (`index_repo.sh`, `search_repo.sh`, `rebuild_collections.py`). Pytest suites reside in `tests/`. Persistent data is isolated in `rag-db/` (Qdrant) and `webui_data/` (Open WebUI). Docker orchestration is split: `docker-compose.embedding.yml` runs Qdrant + embedding backends, while `docker-compose.rag.yml` runs the API/MCP/WebUI stack. Shared env files live beside these compose definitions.

## Build, Test, and Development Commands
Install dependencies once:
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r server/requirements.txt
```
Export values from `.env.example` (at least `QDRANT_URL`, `EMB_BASE_URL`, `EMB_MODEL`, `OPENAI_API_KEY`), start the API with `uvicorn server.main:app --reload --host 0.0.0.0 --port 8000` (or import `server.app:create_app()` directly), and run the MCP worker via `python server/git_rag_mcp.py` when developing off-container. For the canonical, reproducible flow: bring infrastructure up with `docker compose -f docker-compose.embedding.yml up -d --build`, then start the rag/MCP stack with `docker compose -f docker-compose.rag.yml up -d --build`. Use `docker compose -f docker-compose.rag.yml run --rm rag-server pytest tests/...` for tests and `docker compose -f docker-compose.rag.yml run --rm rag-server python server/test_git_rag_api.py` for end-to-end smoke checks. Reserve host-only runs for quick iteration; when skipping Qdrant locally, set `SKIP_COLLECTION_INIT=1`.

## Coding Style & Naming Conventions
Adhere to PEP 8: four-space indentation, `snake_case` identifiers, and `CapWords` classes. Type hints, dataclasses, and purposeful docstrings (as seen in `server/app.py` and the router modules) are expected. Keep responsibilities local—extend Git/embedding helpers within `server/services/git_aware_code_indexer.py`, keep API schemas inside `server/models/`, and read configuration through the shared `Config` class. Use the configured `logging` logger for observability instead of stray prints.

## Testing Guidelines
`python server/test_git_rag_api.py` provisions a temporary repo, drives `/repos/{id}/index` flows (full, commit, working tree), and asserts search hits; run it whenever Git plumbing, streaming responses, or payload formats change. Prefer executing it inside the rag compose stack via `docker compose -f docker-compose.rag.yml run --rm rag-server python server/test_git_rag_api.py`. `python -m pytest tests/test_repository_registry.py` (or its dockerized equivalent) covers the SQLModel registry and `/registry` router—run it after modifying the metadata pipeline. New tests should follow the `test_*` pattern and assert concrete outcomes such as HTTP codes, processed file counts, or commit hashes.

## Commit & Pull Request Guidelines
Write short imperative subjects with optional prefixes (`feat:`, `fix:`, `chore:`) as shown in the current history. Include the behavioral change, affected surface area, and any migrations in the body. PRs should link the driving issue, summarize the change, list validation commands (`python server/test_git_rag_api.py`, `docker-compose up …`, helper scripts), and attach screenshots or response snippets when outputs change. Call out new environment variables, config keys, or bind mounts explicitly.

## Security & Configuration Tips
Never commit secrets or populated `.env` files—load credentials via your shell or a git-ignored override. Lock down `rag-db/` and other bind mounts, especially when Docker runs with `network_mode: host`. When editing `docker-compose.yml` or `config.yaml`, mirror new knobs in `.env.example` and describe them in your PR so operators can apply the same settings in deployment.
