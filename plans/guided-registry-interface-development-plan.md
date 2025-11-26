# Guided registry interface - high-level plan

## Structure
- Add lightweight web UI module under `server/routers/registry_ui.py` serving a single-page form built with a minimal template or small static bundle; keep assets in `server/static/registry_ui/`.
- Reuse existing models/schemas for registry payloads; avoid new persistence by calling existing registry service functions.
- Keep configuration centralized: pull defaults from `Config`, allow overrides via query params/env vars for the UI.

## Commands (planned)
- Web UI route: `GET /registry/ui` serves the single-page shell; `GET /registry/ui/meta` returns defaults (Qdrant URL, embedding model, repo root), existing registry names, embedding options, and available Qdrant collections.
- Registry preview: `POST /registry/preview` (or `/registry/entries/preview` if nested) accepts the same schema as create and returns the computed payload plus the target POST path; include a `dry_run` flag to skip persistence.
- Registry create (existing): `POST /registry` with the validated payload; UI should surface the exact curl shown in preview.
- Compose-run example for indexing: `docker compose -f docker-compose.rag.yml run --rm rag-server python server/git_rag_mcp.py --index --repo-id <id> [--branch <branch>] [--path <subdir>]`.
- MCP setup helper: `python server/git_rag_mcp.py --init --repo-id <id> [--emb-base-url <url>] [--emb-model <model>] [--qdrant-url <url>]` derived from Config defaults.

## API
- Add GET endpoint to serve the registry UI page plus a supporting metadata endpoint (e.g., `/registry/ui/meta`) exposing defaults, existing registry names, embedding options, and Qdrant collections.
- Extend existing registry router with a validated preview endpoint that echoes the computed payload and target POST path without creating records.
- Ensure all routes use shared Pydantic schemas, typed responses, and logging; document new routes in README or router docstring.

## Unit testing
- Add tests for new preview/metadata endpoints validating status codes, schema adherence, and error handling when config/env values are missing or invalid.
- Validate UI-serving route returns expected template/static bundle references and cache headers.

## End-to-end testing
- Extend `server/test_git_rag_api.py` or add a focused flow that creates a registry via the new preview->create path, then triggers indexing to ensure compatibility.
- For Docker workflows, add a compose-run example (documented or in tests) that spins the UI route and exercises it with `httpx` to confirm bundle availability.

## Risk assessment
- UX/API drift: keep the UI strictly bound to existing schemas to avoid divergent payloads.
- Config coupling: fallback/default logic must mirror `Config`; add tests for missing/invalid env to prevent runtime failures in containers.
- Static asset delivery: ensure bundle paths are mounted in Docker and not blocked by CDN/network restrictions.
- Security: validate all inputs server-side, sanitize template rendering, and avoid persisting secrets in the profile file.
