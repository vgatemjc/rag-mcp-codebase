# RAG + MCP Codebase

This repository bundles a lightweight Retrieval-Augmented Generation stack: a FastAPI service for indexing/searching code, a custom MCP agent that wires chunking and Git-aware diffing into Model Context Protocol tooling, and helper scripts plus docker-compose resources to spin up Qdrant, the embedding server, and Open WebUI for experimentation.

## Quick Start
- **Env vars:** copy `.env.example`. For docker-compose workflows, source a provider-specific file (e.g., `.env.embedding.tei`) so your shell exports `QDRANT_ENDPOINT`, `EMB_ENDPOINT`, `EMB_MODEL`, `HOST_REPO_PATH`, `RAG_SERVER_ENDPOINT`, and `OLLAMA_ENDPOINT`; the rag compose stack maps those into the container-facing names (`QDRANT_URL`, `EMB_BASE_URL`, `EMB_MODEL`, `OLLAMA_URL`). For host-only development, export `QDRANT_URL`, `EMB_BASE_URL`, `EMB_MODEL`, and `OPENAI_API_KEY`.
- **Local API (non-docker dev):** `uvicorn server.main:app --reload --host 0.0.0.0 --port 8000` (FastAPI lives behind `create_app()` in `server/app.py`). `server/git_rag_api.py` re-exports the same app for compatibility.
- **MCP worker:** `python server/git_rag_mcp.py` with the same environment variables for Qdrant/TEI.
- **Dockerized workflow:** infrastructure and app live in separate compose stacks:
  - `docker compose -f docker-compose.embedding.yml up -d --build` (brings up Qdrant plus the embedding backend—TEI, vLLM, or Ollama based on env/profiles).
  - `docker compose -f docker-compose.rag.yml up -d --build` (runs the FastAPI server, MCP worker, and optional web UI).
  - Tear both stacks down before large refactors: `docker compose -f ... down`.
- **Manual flows (inside docker or host):** use `bash script/index_repo.sh /path/to/repo` and `bash script/search_repo.sh /path/to/repo`.
- **Tests:** prefer containerized runs, e.g.  
  `docker compose -f docker-compose.rag.yml run --rm rag-server sh -c "cd /workspace/myrepo && pytest tests/test_repository_registry.py"`  
  (the workdir switch ensures `server.*` imports resolve via `PYTHONPATH=/workspace/myrepo`). For host-only unit tests without Qdrant, set `SKIP_COLLECTION_INIT=1`.

## Environment Configuration
- `.env.example` contains two blocks: container defaults (`QDRANT_URL`, `EMB_BASE_URL`, `EMB_MODEL`, `OLLAMA_URL`, etc.) plus host-side exports consumed by docker compose (`QDRANT_ENDPOINT`, `EMB_ENDPOINT`, `HOST_REPO_PATH`, `RAG_SERVER_ENDPOINT`, `OLLAMA_ENDPOINT`). Source it or copy into a provider-specific override before launching containers.
- Create lightweight provider files such as `.env.embedding.tei`, `.env.embedding.vllm`, etc., with the host-side values for that stack and run `source .env.embedding.<provider>` prior to `docker compose` commands. Example (TEI):
  ```bash
  # ~/.env.embedding.tei
  export QDRANT_ENDPOINT=http://localhost:6333
  export EMB_ENDPOINT=http://localhost:8080/v1
  export EMB_MODEL=text-embedding-3-large
  export HOST_REPO_PATH=/absolute/path/to/repo
  export RAG_SERVER_ENDPOINT=http://localhost:8000
  export OLLAMA_ENDPOINT=http://localhost:11434
  ```
- The rag compose file automatically rewires these host exports into the container variables FastAPI expects, so you only maintain the provider-specific endpoints in one place.
- Health check vs. embeddings note: the rag compose stack polls `${EMB_ENDPOINT}/health`. For vLLM, set `EMB_ENDPOINT` to the root (e.g., `http://localhost:8003`) because `/health` is served there even though embeddings are under `/v1/embeddings`. TEI keeps `/v1` in the endpoint (e.g., `http://localhost:8080/v1`) and serves `/v1/health`.
- Set `EXPOSE_MCP_UI=0` to hide the MCP/dev UI routes in hardened environments; `MCP_MODULE` controls which MCP module to introspect (defaults to `server.git_rag_mcp`).

## Docker-Based Development Workflow
1. Tear down both compose stacks before any significant refactor:  
   `docker compose -f docker-compose.embedding.yml down && docker compose -f docker-compose.rag.yml down`
2. Apply code changes.
3. Rebuild and launch infra + embedding stack:  
   `docker compose -f docker-compose.embedding.yml up -d --build`
4. Rebuild and launch the rag/mcp stack:  
   `docker compose -f docker-compose.rag.yml up -d --build`
5. Run tests inside the rag container (see commands above).
6. Iterate by repeating from step 1, ensuring debugging always uses the compose environment rather than host-only processes.

## Repository Registry
- The FastAPI service exposes `/registry` endpoints backed by `server/services/repository_registry.py` (SQLite + SQLModel). Use them to register repositories, archive/delete entries, or ingest GitHub webhooks before indexing runs.
- API routers now live in `server/routers/` (`registry_router.py`, `index_router.py`, `status_router.py`, `search_router.py`) and are wired inside `server/app.py`.
- A minimal UI lives at `/registry/ui`, served from `server/static/registry_ui/` (mount path `/static`). The UI pulls `/registry/ui/meta` for defaults/options, hits `/registry/preview` for dry-run normalization, then POSTs to `/registry` to create entries.
- `/registry/ui/meta` returns config defaults (`QDRANT_URL`, `EMB_BASE_URL`, `EMB_MODEL`, `COLLECTION`, `REPOS_DIR`), current registry entries, embedding options (from `server/static/registry_ui/embed-options.json` when present), and Qdrant collections (fails open with an empty list).
- Quick preview→create flow (inside the rag container):  
  `curl -X POST -H "Content-Type: application/json" http://localhost:8000/registry/preview -d '{"repo_id":"demo"}'`  
  then `curl -X POST -H "Content-Type: application/json" http://localhost:8000/registry -d '{"repo_id":"demo"}'`
- Each indexing/search call resolves its repo metadata through the registry and initializes embedding/Qdrant clients lazily via `server/services/initializers.py`, ensuring per-repository collections stay isolated.
- After touching the registry or router flows, run tests via docker compose (`docker compose -f docker-compose.rag.yml run --rm rag-server pytest tests/test_repository_registry.py tests/test_registry_ui.py`) plus the end-to-end indexing script (`docker compose -f docker-compose.rag.yml run --rm rag-server python server/test_git_rag_api.py`). For bare-host smoke tests, ensure the embedding/Qdrant compose stack is already running, or set `SKIP_COLLECTION_INIT=1` only when intentionally skipping those dependencies.

## Developer UI and MCP tools
- A developer-focused UI lives at `/dev-ui` (served from `server/static/dev_ui/`). It lists registry entries, supports deleting a registry row, triggers full or incremental indexing, polls `/repos/{id}/index/status`, runs `/search`, and invokes MCP tools via `/mcp/tools`.
- Index status metadata is persisted on each run (status, mode, started/finished timestamps, last indexed commit/error) and exposed through `/repos/{repo_id}/index/status`.
- MCP endpoints: `GET /mcp/tools` lists available tools from `server/git_rag_mcp.py`, and `POST /mcp/tools/{name}` invokes a tool with a JSON `args` map. Disable both with `EXPOSE_MCP_UI=0` when not needed.
- The UI reuses the `/static` mount already present in `server/app.py`; no extra bundling is required. Reload the registry list after adding or archiving repos to keep the dropdowns in sync.

## Contributor Guide

Implementation standards, testing expectations, and pull-request conventions are documented in [AGENTS.md](AGENTS.md). Read it before opening changes—the file summarizes project structure, coding style, and CI-ready test commands so contributions align with the existing workflow.
- **Embedding providers:** choose which embedding backend to run by selecting profiles when launching `docker-compose.embedding.yml`. Examples:
  - `docker compose -f docker-compose.embedding.yml --profile tei up -d --build`
  - `docker compose -f docker-compose.embedding.yml --profile vllm-nvidia up -d --build`
  - `docker compose -f docker-compose.embedding.yml --profile vllm-amd up -d --build`
  - `docker compose -f docker-compose.embedding.yml --profile ollama up -d --build`
  Each profile brings up Qdrant plus one embedding container. Source the matching `.env.embedding.*` file before starting the rag compose stack so `QDRANT_ENDPOINT`, `EMB_ENDPOINT`, and `EMB_MODEL` align (e.g., TEI → `http://embedding-tei:8080/v1`, vLLM → `http://embedding-vllm-nvidia:8003` or `http://embedding-vllm-amd:8003`, Ollama → `http://embedding-ollama:11434/v1`).
