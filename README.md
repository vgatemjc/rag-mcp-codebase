# RAG + MCP Codebase

This repository bundles a lightweight Retrieval-Augmented Generation stack: a FastAPI service for indexing/searching code, a custom MCP agent that wires chunking and Git-aware diffing into Model Context Protocol tooling, and helper scripts plus docker-compose resources to spin up Qdrant, the embedding server, and Open WebUI for experimentation.

## Quick Start
- **Env vars:** copy `.env.example` and export at least `QDRANT_URL`, `EMB_BASE_URL`, `EMB_MODEL`, and `OPENAI_API_KEY`
- **Install deps:** `python -m venv .venv && source .venv/bin/activate && pip install -r server/requirements.txt`
- **Local API:** from `server/`, run `uvicorn git_rag_api:app --host 0.0.0.0 --port 8000`
- **MCP worker:** `python git_rag_mcp.py` with the same environment variables for Qdrant/TEI
- **Containers:** `docker-compose up qdrant embedding rag-server mcp-server webui`
- **Manual flows:** use `bash script/index_repo.sh /path/to/repo` and `bash script/search_repo.sh /path/to/repo`

## Repository Registry
- The FastAPI service now exposes `/registry` endpoints backed by `server/repository_registry.py` (SQLite + SQLModel). Use them to register repositories, archive/delete entries, or ingest GitHub webhooks before indexing runs.
- Each indexing/search call resolves its repo metadata through the registry, ensuring Qdrant collections and embedding models stay per-repository. Run `python -m pytest server/tests/test_repository_registry.py` after touching the registry or router.

## Contributor Guide

Implementation standards, testing expectations, and pull-request conventions are documented in [AGENTS.md](AGENTS.md). Read it before opening changes—the file summarizes project structure, coding style, and CI-ready test commands so contributions align with the existing workflow.
