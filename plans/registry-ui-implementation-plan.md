# Guided registry interface - implementation plan

## API and app wiring
- Add `server/routers/registry_ui.py` with:
  - `GET /registry/ui` serving the UI shell from `server/static/registry_ui/index.html` with cache headers.
  - `GET /registry/ui/meta` returning config defaults (`QDRANT_URL`, `EMB_BASE_URL`, `EMB_MODEL`, `REPOS_DIR`, computed `COLLECTION`), existing registry entries (id/name/collection/model), embedding options (seed list), and available Qdrant collections (empty list on failure).
- Update `server/app.py` to mount static assets for the UI (e.g., `app.mount("/static", StaticFiles(directory="server/static"), name="static")`) and include the new router. Add a short comment noting the static mount supports the registry UI bundle.

## Registry preview endpoint
- Extend `server/routers/registry_router.py` with `POST /registry/preview` that reuses `RepositoryIn`, normalizes payload as create would, echoes the target POST path, and does not persist. Add a brief comment that this is a dry-run for the UI curl preview.
- (Optional) Factor a `normalize_repository_payload()` helper (router-level or in `RepositoryRegistry`) to keep preview/create logic aligned; document intent with a short comment.

## UI assets and metadata
- Add `server/static/registry_ui/` containing:
  - `index.html`: single-page form loading `/registry/ui/meta`, showing defaults, and wiring preview→create actions with curl snippet placeholders.
  - `app.js`: fetch meta, handle form submit (preview then create), render responses defensively when meta fields are missing.
  - `styles.css`: minimal styling for readability (ASCII-only).
  - (Optional) `embed-options.json`: seed list of embedding models; have `/registry/ui/meta` read it if present.

## Tests
- Add `tests/test_registry_ui.py` (or extend `tests/test_repository_registry.py`) to cover:
  - `GET /registry/ui` returns 200 and references the static bundle.
  - `GET /registry/ui/meta` returns config defaults and tolerates missing Qdrant (empty collections).
  - `POST /registry/preview` normalizes payload, returns target path, and does not create a DB row (confirm via follow-up GET).
- Optionally extend `server/test_git_rag_api.py` with a preview→create flow before indexing for end-to-end coverage.

## Documentation
- Update `README.md` registry section with new routes (`/registry/ui`, `/registry/ui/meta`, `/registry/preview`), describe static asset location, and add a docker compose run example hitting the UI and preview→create flow.

## Functions to add/update (with intent comments)
- New: `serve_registry_ui()`, `get_registry_ui_meta()` in `server/routers/registry_ui.py` (serve UI shell, expose config/registry defaults).
- New: `preview_registry_entry()` in `server/routers/registry_router.py` (dry-run normalization).
- Updated: `create_app()` in `server/app.py` (mount static assets, include UI router).
- Optional helper: `normalize_repository_payload()` to centralize defaulting for preview/create.
