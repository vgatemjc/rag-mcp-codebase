## Docker-Based Development & Test Workflow Plan

### 1. Compose Separation
- Maintain two compose files:
  - `docker-compose.embedding.yml` → Qdrant + embedding provider (TEI, vLLM, Ollama). Each provider gets its own service block and env vars (`EMB_BASE_URL`, `EMB_MODEL`, auth tokens).
  - `docker-compose.rag.yml` → FastAPI (`server.main:app`), MCP worker, web UI.
- Shared `.env` supplies Qdrant/embedding URLs; rag compose only consumes the URLs, never launches infra services directly.

### 2. Refactor Workflow (pre / during / post)
1. `docker compose -f docker-compose.embedding.yml down && docker compose -f docker-compose.rag.yml down`
2. Apply code changes.
3. `docker compose -f docker-compose.embedding.yml up -d --build` (select embedding provider via env or profiles).
4. `docker compose -f docker-compose.rag.yml up -d --build`
5. Run dockerized unit tests (see §3).
6. When iterating again, repeat step 1 to ensure clean state.

### 3. Unit Test Strategy (containerized)
- Provide `tests/Dockerfile` or reuse rag service image with `pytest` entrypoint.
- Command: `docker compose -f docker-compose.rag.yml run --rm rag-server pytest tests/test_repository_registry.py` (plus other suites).
- For end-to-end indexing: `docker compose -f docker-compose.rag.yml run --rm rag-server python server/test_git_rag_api.py`
- Ensure SKIP_COLLECTION_INIT defaults to `0` inside containers so tests hit real Qdrant/embedding services spun up in the embedding compose stack.

### 4. Embedding Provider Config Options
- Document env templates for:
  - **TEI**: `EMB_BASE_URL=http://embedding-tei:8080/v1`, `EMB_MODEL=text-embedding-3-large`.
  - **vLLM**: `EMB_BASE_URL=http://embedding-vllm:8000/v1`, auth headers if required.
  - **Ollama**: `EMB_BASE_URL=http://embedding-ollama:11434/v1`, `EMB_MODEL=nomic-embed-text`.
- Use compose profiles or `EMB_PROVIDER` env to choose which embedding container to start; rag compose just reads the resulting URL/model.

### 5. Debugging Expectations
- All manual testing (curl, uvicorn logs, etc.) happens with the docker-compose services running; avoid host-only runs unless documenting a special case.
- When bugfixing: replicate issue inside containers, modify code locally, rebuild rag compose image, rerun containerized tests.

### 6. Next Steps
- Update `README.md` with:
  - How to bring up each compose stack.
  - Embedding provider selection instructions.
  - Mandate to run tests via `docker compose … run rag-server pytest …`.
- Add sample `.env.embedding.tei`, `.env.embedding.vllm`, `.env.embedding.ollama` for operator reference.
