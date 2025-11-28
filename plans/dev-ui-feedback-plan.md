# Dev UI feedback response plan

## Goals
- Address developer feedback on indexing progress visibility, MCP tool response formatting, and tool invocation argument handling in the Dev UI and backend.

## test guideline
refer plans/docker-testing-workflow.md and follow refactor workflow section step by step

## Plan
1) Full-index progress surfacing
   - Backend: add progress events or status fields for long-running full index operations (e.g., processed files/bytes, phase) returned via the index status endpoint or streaming progress API.
   - UI: display progress in the index controls/status table, updating via polling; show clear in-progress states and completion/error badges.
2) MCP tool response formatting
   - Standardize API responses to include structured fields (stdout, stderr, parsed JSON payload when available, duration, exit status) and content type hints.
   - UI: pretty-print JSON output, preserve plain text with monospace formatting, and add copy/download affordances; show errors inline with clear labeling.
3) Tool argument validation issues
   - Fix `repo_tree_md` invocation: adjust route or request payload to match expected params (likely `repo_id` instead of `repo`) and update UI accordingly.
   - Fix `list_mcp_tools` invocation: remove unsupported `repo` argument and ensure UI/request uses only supported params; add defensive validation.
4) Testing and verification
   - Add/extend FastAPI tests for MCP list/invoke happy/invalid argument paths and index status progress fields.
   - Manual smoke: run indexing from Dev UI to confirm progress updates; invoke MCP tools to verify formatted responses and corrected params.

5) Registry deletion UX
   - Add Dev UI affordance to delete a registry entry with confirmation and clear status messaging.
   - Wire to `/registry/{repo_id}` DELETE and refresh registry list/selection after removal.
   - Update docs to mention delete control in the Dev UI.

## Outputs
- Updated backend endpoints for progress and MCP tool argument handling.
- Dev UI improvements for progress display and formatted MCP responses.
- Tests and a brief doc/update note summarizing the fixes.

## Status update
- Implemented progress tracking fields on index status and wired Dev UI polling/stream display.
- MCP tool responses now return structured metadata with parsed JSON and standardized text handling; UI formats outputs.
- Dev UI filters tool arguments (`repo` vs `repo_id`) and avoids sending unsupported params; backend tolerates the alias.
- Added test coverage for new MCP response shape, invalid arg handling, and index status progress fields.
