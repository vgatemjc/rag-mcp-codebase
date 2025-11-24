# RAG + MCP Codebase

This repository bundles a lightweight Retrieval-Augmented Generation stack: a FastAPI service for indexing/searching code, a custom MCP agent that wires chunking and Git-aware diffing into Model Context Protocol tooling, and helper scripts plus docker-compose resources to spin up Qdrant, the embedding server, and Open WebUI for experimentation.

## Quick Start
- **Env vars:** copy `.env.example` and export at least `QDRANT_URL`, `EMB_BASE_URL`, `EMB_MODEL`, and `OPENAI_API_KEY`.
- **Local API (non-docker dev):** `uvicorn server.main:app --reload --host 0.0.0.0 --port 8000` (FastAPI lives behind `create_app()` in `server/app.py`). `server/git_rag_api.py` re-exports the same app for compatibility.
- **MCP worker:** `python server/git_rag_mcp.py` with the same environment variables for Qdrant/TEI.
- **Dockerized workflow:** infrastructure and app live in separate compose stacks:
  - `docker compose -f docker-compose.embedding.yml up -d --build` (brings up Qdrant plus the embedding backend—TEI, vLLM, or Ollama based on env/profiles).
  - `docker compose -f docker-compose.rag.yml up -d --build` (runs the FastAPI server, MCP worker, and optional web UI).
  - Tear both stacks down before large refactors: `docker compose -f ... down`.
- **Manual flows (inside docker or host):** use `bash script/index_repo.sh /path/to/repo` and `bash script/search_repo.sh /path/to/repo`.
- **Tests:** prefer containerized runs, e.g. `docker compose -f docker-compose.rag.yml run --rm rag-server pytest tests/test_repository_registry.py`. For host-only unit tests without Qdrant, set `SKIP_COLLECTION_INIT=1`.

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
- Each indexing/search call resolves its repo metadata through the registry and initializes embedding/Qdrant clients lazily via `server/services/initializers.py`, ensuring per-repository collections stay isolated.
- After touching the registry or router flows, run tests via docker compose (`docker compose -f docker-compose.rag.yml run --rm rag-server pytest tests/test_repository_registry.py`) plus the end-to-end indexing script (`docker compose -f docker-compose.rag.yml run --rm rag-server python server/test_git_rag_api.py`). For bare-host smoke tests, ensure the embedding/Qdrant compose stack is already running, or set `SKIP_COLLECTION_INIT=1` only when intentionally skipping those dependencies.

## Contributor Guide

Implementation standards, testing expectations, and pull-request conventions are documented in [AGENTS.md](AGENTS.md). Read it before opening changes—the file summarizes project structure, coding style, and CI-ready test commands so contributions align with the existing workflow.
- **Embedding providers:** choose which embedding backend to run by selecting profiles when launching `docker-compose.embedding.yml`. Examples:
  - `docker compose -f docker-compose.embedding.yml --profile tei up -d --build`
  - `docker compose -f docker-compose.embedding.yml --profile vllm-nvidia up -d --build`
  - `docker compose -f docker-compose.embedding.yml --profile vllm-amd up -d --build`
  - `docker compose -f docker-compose.embedding.yml --profile ollama up -d --build`
  Each profile brings up Qdrant plus one embedding container. Match `.env.embedding.*` files to profile selection so `EMB_BASE_URL`/`EMB_MODEL` align (e.g., TEI → `http://embedding-tei:8080/v1`, vLLM → `http://embedding-vllm-nvidia:8003/v1` or `http://embedding-vllm-amd:8003/v1`, Ollama → `http://embedding-ollama:11434/v1`).
