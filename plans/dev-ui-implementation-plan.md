# Developer UI for RAG + MCP - implementation plan

## Scope and routing
- Add dedicated Dev UI served at `/dev-ui` from `server/static/dev_ui/` (HTML/JS/CSS). Mount via `StaticFiles` in `create_app()` with a short comment noting this supports the dev playground.
- Keep existing registry UI untouched; dev UI is separate and developer-focused.
- Ensure `git_rag_mcp.py` and `git_rag_api.py` continue to work without change.

## API surface
- Reuse registry/index/search routers; add a thin MCP router:
  - `GET /mcp/tools`: list available tools (name, description, input schema if available).
  - `POST /mcp/tools/{name}`: invoke tool with args; return stdout/stderr, duration, and any structured payload.
- Add optional index status endpoint: `GET /indexes/{repo_id}/status` (last indexed commit, mode full/commit/working, started/finished timestamps, status/error). Persist minimal status alongside registry data (SQLModel column additions with safe defaults).
- Keep responses free of secrets; if configurable, add `expose_mcp_ui` flag to `Config`, default on for dev.

## UI bundle (`server/static/dev_ui/`)
- Page sections: registry table (id/name/path/collection/model/last indexed/status), index controls (full/update/working tree), search playground (repo selector, query, top_k), MCP tools (list + invoke form).
- Include shared request/response viewer with pretty-printed JSON, copy/download for MCP output, and inline error display.
- UX details: disable buttons while requests run, show status badges, poll status endpoint while indexing, persist last-used repo in `localStorage`.
- Keep JS/CSS self-contained (no bundler); plain fetch helpers with centralized error handler; no streaming required initially.

## Data/model updates
- Extend registry/status model to store `last_indexed_commit`, `last_indexed_at`, `last_mode`, `last_status`/`last_error`.
- On index start/finish, update status fields through service layer to keep API/UI aligned.
- Backfill defaults in migration-safe way (nullable columns or defaults) to avoid breaking existing DBs.

## Tests
- FastAPI router tests: MCP list/invoke happy/err paths, index status endpoint, registry data includes new status fields.
- Optional: extend `server/test_git_rag_api.py` with a UI-like flow (list repos → index → search) to ensure responses carry new metadata.
- Defer Playwright/UI automation for now; manual smoke checklist lives in docs.

## Docs and ops
- Add short doc (`docs/dev-ui.md` or README section) describing routes, expected env vars, and how to open `/dev-ui`.
- Mirror any new config flag in `.env.example` and `server/config.yaml`.
- Note docker-compose validation flow: bring up embedding stack, start rag stack, run registry/RAG tests, then manual UI smoke at `http://localhost:8000/dev-ui`.
