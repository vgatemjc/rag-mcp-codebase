# Developer UI for RAG + MCP

## Problem / user outcome
- Developers need a browser UI to register repos, trigger indexing, and verify RAG/MCP behavior without relying on curl/CLI.
- They also need visibility into collection status, last indexed commit, and MCP tool outputs in a human-readable way.

## Proposed solution
- Extend the static UI bundle (separate page) to surface registry management, indexing controls (full/update/working tree), search playground, and MCP tool triggers.
- Show requests/responses inline so developers can understand payloads and reuse them in automation.

## User stories / flows
- As a developer, I can browse registered repos, see collection/model/last-indexed info, and launch reindexing with visible progress.
- As a developer, I can run sample RAG searches against a repo and inspect the request/response payloads.
- As a developer, I can list MCP tools and invoke one (e.g., summarize diff) with results rendered and downloadable.

## Tech notes
- Services/modules: FastAPI routers for registry/index/search, MCP worker hooks; may need a thin router to expose MCP tool list/invoke.
- UI: extend existing registry UI but keep a dedicated `/dev-ui` route; plain JS/CSS under `/static`.
- Add a lightweight status endpoint if needed for indexing progress; avoid exposing secrets in any meta/config payloads.

## Validation
- Success criteria: all flows above are usable via the UI with clear error handling and no secret leakage.
- Test plan: API coverage for new endpoints, manual UI smoke over `/dev-ui`, consider Playwright if automated UI tests are added.

## Docker-based testing (from plans/docker-testing-workflow.md)
- Tear down stale stacks first: `docker compose -f docker-compose.embedding.yml down && docker compose -f docker-compose.rag.yml down`.
- Export env per profile: `QDRANT_ENDPOINT`, `EMB_ENDPOINT`, `EMB_MODEL`, `HOST_REPO_PATH`, `OLLAMA_ENDPOINT` (and optional `DIM`), then bring up embedding:  
  `docker compose -f docker-compose.embedding.yml --profile tei up -d --build`
- Start rag stack: `docker compose -f docker-compose.rag.yml up -d --build`.
- Run registry/RAG UI tests in-container:  
  `HOST_REPO_PATH="$(pwd)" QDRANT_ENDPOINT=http://localhost:6333 EMB_ENDPOINT=http://localhost:8080/v1 EMB_MODEL=BAAI/bge-small-en-v1.5 OLLAMA_ENDPOINT=http://localhost:11434 docker compose -f docker-compose.rag.yml run --rm rag-server sh -c "cd /workspace/myrepo && pytest tests/test_registry_ui.py tests/test_repository_registry.py"`
- Optional end-to-end smoke: `docker compose -f docker-compose.rag.yml run --rm rag-server sh -c "cd /workspace/myrepo && python server/test_git_rag_api.py"`.
