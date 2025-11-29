# Registry UI – DB Reset Feature Plan

Objective: allow a user to delete both local datastores (registry SQLite
and Qdrant storage) from the registry UI, using `HOST_REPO_PATH`-anchored
paths and keeping defaults safe for local dev.

## Scope
- Add a UI control in the registry UI to trigger a backend reset action.
- Backend route to delete registry DB file and wipe Qdrant storage with
  clear safeguards and optional dry-run confirmation.
- Ensure paths respect `HOST_REPO_PATH` for host-mounted storage.

## Design / Tasks
1) Backend API
   - Add `DELETE /registry/datastores` (or similar) in the registry
     router with idempotent behavior. Require confirmation token in the
     body (e.g., `{"confirm":"delete"}`) to avoid accidental clicks.
   - Resolve registry DB path from config (`Config.registry_db_path` or
     equivalent) so host mounts work; if file missing, treat as success.
   - For Qdrant: drop only collections tied to registry entries. If
     using host storage (`HOST_REPO_PATH/rag-db`), remove contents on
     the host; otherwise, call Qdrant API for targeted collection drops
     or surface a warning that in-container storage cannot be wiped
     from the host. Include config check (endpoint + storage path env).
     Keep SKIP guard (e.g., `ALLOW_DATA_RESET=1`).
   - Log actions and return a result summary (what was removed, skipped,
     or failed).

2) UI
   - Add a “Delete local data” section with a short warning and a button
     that sends `DELETE /registry/datastores` with the confirmation
     payload. Disable while in-flight; render success/errors inline.
   - Display which paths/endpoints will be affected using meta data
     already fetched (`HOST_REPO_PATH`-relative paths if available).
   - Keep styling minimal (existing palette); no automatic reload.

3) Safety & Config
   - Add env guard `ALLOW_DATA_RESET` (default false) so production or
     shared deployments cannot trigger the wipe. UI should hide/disable
     the button when the flag is off.
   - Respect `HOST_REPO_PATH`; do not hardcode paths. Handle missing
     dirs gracefully.

4) Validation
   - Unit: test the new route with temp dirs/files, verifying summary
     messages and guards (`ALLOW_DATA_RESET` off → 403/disabled).
   - Integration/manual: start stack with host-mounted `registry.db` and
     `rag-db`, trigger delete via UI, verify files removed and Qdrant
     collections cleared or warnings returned.

## Decisions
- Qdrant wipe is limited to collections tied to registry entries (no
  blanket drop of all collections).
- No export/backup prompt required; this flow targets RAG/MCP developer
  resets.
