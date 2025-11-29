## Docker-Based Development & Test Workflow Plan

### 1. Compose Separation ✅
- Maintain two compose files:
  - `docker-compose.embedding.yml` → Embedding provider only (TEI, vLLM, Ollama). Each provider gets its own service block and env vars (`EMB_BASE_URL`, `EMB_MODEL`, auth tokens).
  - `docker-compose.rag.yml` → Qdrant, FastAPI (`server.main:app`), MCP worker, web UI.
- Shared `.env` supplies Qdrant/embedding URLs; rag compose now launches Qdrant, embedding compose only hosts embedding.
- **Agent rule:** Do not touch the embedding compose stack during routine test runs beyond the chosen embedding profile. Operate on `docker-compose.rag.yml` for app/Qdrant lifecycle unless explicitly told otherwise.

### 2. Refactor Workflow (pre / during / post)
- **Pre-change cleanup**
  - Leave the embedding stack running. Down only the rag stack (now includes Qdrant) if needed:  
    `docker compose -f docker-compose.rag.yml down`
  - Re-export `.env` (or the profile-specific env file) so `QDRANT_ENDPOINT`, `EMB_ENDPOINT`, `HOST_REPO_PATH`, etc., are fresh in the shell before building images.
- **During iteration**
  - Apply the code/config changes you’re testing.
  - Rebuild and start the rag/MCP stack only:  
    `docker compose -f docker-compose.rag.yml up -d --build`
  - Tail logs (`docker compose -f docker-compose.rag.yml logs -f rag-server`) when validating API changes.
- **Post-run / repeat**
  - Run dockerized unit tests (see §3) plus any end-to-end checks needed for the change.
  - When the next iteration begins, repeat the rag-stack teardown step if necessary; leave embedding services untouched unless instructed otherwise.

### 3. Unit Test Strategy (containerized)
- **Image + entrypoint**
  - Reuse the `rag-server` image for tests (no separate tests Dockerfile). Every run mounts `./server` plus `${HOST_REPO_PATH}` exactly like the API container so Git fixtures stay available.
  - Ensure `PYTHONPATH=/workspace/myrepo` is set for the rag-server service so `server.*` imports resolve when running tests inside the container.
- **Unit tests**
  - `docker compose -f docker-compose.rag.yml run --rm rag-server pytest tests/test_repository_registry.py`
  - Swap the final argument for other suites (`tests/` folder or individual files) and pass `PYTEST_ADDOPTS` for verbosity/fail-fast where needed.
  - When running from an agent and tests are not baked into the image, mount them explicitly:  
    `docker compose -f docker-compose.rag.yml run --rm -v $PWD/tests:/app/tests -v $PWD/pytest.ini:/app/pytest.ini rag-server pytest tests/...`
- **End-to-end smoke test**
  - `docker compose -f docker-compose.rag.yml run --rm rag-server python server/test_git_rag_api.py`
- **Environment requirements**
  - Run these commands only after the embedding stack from `docker-compose.embedding.yml` is healthy so the containers hit real dependencies; Qdrant now comes up with the rag stack.
  - Health checks inside `docker-compose.rag.yml` hit `${EMB_ENDPOINT}/health`. For vLLM, set `EMB_ENDPOINT` to the root (e.g., `http://localhost:8003`) because `/health` is served there even though embeddings live under `/v1/embeddings`. TEI keeps `/v1` in the endpoint (e.g., `http://localhost:8080/v1`), which also serves `/v1/health`.
  - Leave `SKIP_COLLECTION_INIT` unset (defaults to `0`) to exercise collection initialization; only override when intentionally skipping Qdrant, and document those exceptions in the PR/tests.

### 4. Embedding Provider Config Options
- **Profile selection**
  - Launch only one embedding provider profile at a time:  
    `docker compose -f docker-compose.embedding.yml --profile <tei|vllm-nvidia|vllm-amd|ollama> up -d --build`
  - Profiles include only the selected embedding container; Qdrant comes from the rag stack. Stop profiles with the same flag on `down`.
- **Environment bridging**
  - Infra stack exports provider-specific variables (e.g., `TEI_MODEL_ID`, `VLLM_MODEL_ID`) but the rag stack only reads generic values: `QDRANT_ENDPOINT`, `EMB_ENDPOINT`, `EMB_MODEL`, and optionally `OLLAMA_ENDPOINT`.
  - Maintain lightweight `.env.embedding.<provider>` files with the correct URLs/models; source one before bringing the stacks up, then export the rag env to point at the running service, e.g.:
    ```bash
    # TEI example
    export QDRANT_ENDPOINT=http://localhost:6333
    export EMB_ENDPOINT=http://localhost:8080/v1
    export EMB_MODEL=text-embedding-3-large
    export HOST_REPO_PATH=/abs/path/to/repo
    ```
- **Provider-specific notes**
  - **TEI** (default): set `TEI_MODEL_ID` / `TEI_DTYPE`; service listens on `8080` behind `/v1`. Ideal for HF-hosted embedding models.
  - **vLLM (nvidia)**: `VLLM_MODEL_ID` (e.g., `nomic-ai/nomic-embed-code`), `VLLM_PORT` defaults to `8003`. Requires NVIDIA GPUs and `--gpus all`.
  - **vLLM (amd)**: uses ROCm image, exposes port `8003`. Ensure `/dev/kfd` and `/dev/dri` devices are accessible on the host.
  - **Ollama**: runs on `11434`; set `EMB_MODEL` to the Ollama model tag (e.g., `nomic-embed-text`). Provide `OLLAMA_ENDPOINT` to rag/webui stacks so chat UI can hit the same daemon.
- **WebUI alignment**
  - When the web UI is enabled, ensure `WEBUI_EMBED_ENGINE` / `WEBUI_RAG_ENGINE` match the chosen provider (e.g., `vllm` when using either vLLM profile) and that `RAG_SERVER_ENDPOINT` points to the rag-server port (default `http://localhost:8000`).

### 5. Debugging Expectations
- All manual testing (curl, uvicorn logs, etc.) happens with the docker-compose services running; avoid host-only runs unless documenting a special case.
- When bugfixing: replicate issue inside containers, modify code locally, rebuild rag compose image, rerun containerized tests.

### 6. Next Steps
- Update `README.md` with:
  - How to bring up each compose stack.
  - Embedding provider selection instructions.
  - Mandate to run tests via `docker compose … run rag-server pytest …`.
- Add sample `.env.embedding.tei`, `.env.embedding.vllm`, `.env.embedding.ollama` for operator reference.
