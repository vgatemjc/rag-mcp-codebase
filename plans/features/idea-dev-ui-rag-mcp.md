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
