# Guided registry interface - branched implementation plan

## Sequence (high-level)
- Wire backend surfaces (`/registry/ui`, `/registry/ui/meta`, `/registry/preview`) and static mount in `create_app()`.
- Ship minimal UI bundle under `server/static/registry_ui/` that exercises preview→create flows.
- Cover new endpoints with targeted pytest coverage; add docs updates last.

## Detailed steps
- Router/UI mount
  - Add `server/routers/registry_ui.py` with `serve_registry_ui()` and `get_registry_ui_meta()`.
  - Mount static assets in `server/app.py` with a short comment explaining registry UI assets; include the new router.
  - Ensure `server/routers/registry_router.py` exports `preview_registry_entry()` that normalizes payload without persisting (optionally share normalization helper).
- UI bundle
  - Create `server/static/registry_ui/index.html`, `app.js`, `styles.css` (and optional `embed-options.json` seed list).
  - `app.js` fetches `/registry/ui/meta`, renders defaults defensively, posts to `/registry/preview`, then `/registry` on confirmation, and shows curl snippets.
  - Keep styling minimal/readable (ASCII-only), no external deps.
- Tests
  - Add `tests/test_registry_ui.py` (or extend existing registry tests) to cover `/registry/ui`, `/registry/ui/meta` defaults/tolerance when Qdrant is down, and `/registry/preview` dry-run behavior.
  - Consider end-to-end preview→create flow inside `server/test_git_rag_api.py`.
- Documentation
  - Update `README.md` registry section with new routes, static asset location, and docker-compose run example hitting the UI and preview→create flow.

## Open questions / decisions
- Where to place `normalize_repository_payload()` helper (router-level vs `RepositoryRegistry`).
- How much meta data to surface from Qdrant (fail-open with empty list vs propagate error).
