# Repository Guidelines

## Project Structure & Module Organization
`server/` contains the production code: `git_rag_api.py` (FastAPI), `git_rag_mcp.py` (MCP bridge), `git_aware_code_indexer.py` and `repo2md_ts.py` for chunking/Git logic, plus `config.yaml`. Operational helpers live in `script/` (`index_repo.sh`, `search_repo.sh`, `rebuild_collections.py`). Persistent data is isolated in `rag-db/` (Qdrant) and `webui_data/` (Open WebUI). Service wiring resides in `docker-compose.yml`, while `.env.example` lists the environment variables shared across components.

## Build, Test, and Development Commands
Install dependencies once:
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r server/requirements.txt
```
Export values from `.env.example` (at least `QDRANT_URL`, `EMB_BASE_URL`, `EMB_MODEL`, `OPENAI_API_KEY`), start the API with `uvicorn git_rag_api:app --reload --host 0.0.0.0 --port 8000`, and run the MCP worker via `python git_rag_mcp.py`. Validate the stack with `docker-compose up qdrant embedding rag-server mcp-server webui`. Use `bash script/index_repo.sh /workspace/myrepo` to index mounted repos, `bash script/search_repo.sh /workspace/myrepo` to smoke-test search, and `python script/rebuild_collections.py --config server/config.yaml` when collection schemas change.

## Coding Style & Naming Conventions
Adhere to PEP 8: four-space indentation, `snake_case` identifiers, and `CapWords` classes. Type hints, dataclasses, and purposeful docstrings (as seen in `git_rag_api.py`) are expected. Keep responsibilities local—extend Git/embedding helpers within `git_aware_code_indexer.py`, keep API schemas beside their endpoints, and read configuration through the shared `Config` class. Use the configured `logging` logger for observability instead of stray prints.

## Testing Guidelines
`python server/test_git_rag_api.py` provisions a temporary repo, drives `/repos/{id}/index` flows (full, commit, working tree), and asserts search hits; run it whenever Git plumbing, streaming responses, or payload formats change. New tests should follow the `test_*` pattern and assert concrete outcomes such as HTTP codes, processed file counts, or commit hashes.

## Commit & Pull Request Guidelines
Write short imperative subjects with optional prefixes (`feat:`, `fix:`, `chore:`) as shown in the current history. Include the behavioral change, affected surface area, and any migrations in the body. PRs should link the driving issue, summarize the change, list validation commands (`python server/test_git_rag_api.py`, `docker-compose up …`, helper scripts), and attach screenshots or response snippets when outputs change. Call out new environment variables, config keys, or bind mounts explicitly.

## Security & Configuration Tips
Never commit secrets or populated `.env` files—load credentials via your shell or a git-ignored override. Lock down `rag-db/` and other bind mounts, especially when Docker runs with `network_mode: host`. When editing `docker-compose.yml` or `config.yaml`, mirror new knobs in `.env.example` and describe them in your PR so operators can apply the same settings in deployment.
