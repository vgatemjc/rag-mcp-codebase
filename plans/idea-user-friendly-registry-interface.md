# Idea: Guided registry and repository creation

This concept gives developers a friendlier path to set up registry entries and repositories for the rag/MCP server, with both a small web UI and a text-first helper.

## Web UI concept
- Lightweight FastAPI route serving a single-page form that walks through registry creation in three short steps: connection details, repository metadata, and confirmation.
- Inline validation for fields the backend already expects (e.g., `repo_url`, branch, embedding model choice) with live hints pulled from the API (available collections, existing registry names).
- Preview card showing the computed registry payload before submission and the exact POST endpoint it will hit; copy-to-clipboard for the curl equivalent.
- Success screen presents next actions: kick off indexing, open search UI, or download a `.env` snippet with the new registry ID baked in.

## Text/CLI helper concept
- An interactive TUI (e.g., Textual/Rich) that mirrors the web steps but runs in the terminal, ideal for SSH or container sessions.
- Guided prompts with defaults sourced from `Config` (Qdrant URL, embedding model, repo root) and inline validation so users never send a bad payload.
- Generates ready-to-run commands: `curl` for API creation, `python server/git_rag_mcp.py --init` for MCP setup, and a `docker compose ... run --rm rag-server` example for indexing.
- Option to write the chosen values to a small local profile file (ignored by git) so repeated runs prefill answers and reduce friction.

## UX notes
- Keep copy concise and action-oriented: “Add repository”, “Validate connection”, “Start indexing”.
- Prefer opinionated defaults over empty fields, but always show how they were derived (env, config, prior profile).
- Surface errors with exact backend messages plus a one-line fix hint to avoid bouncing between logs and UI.

## How it fits
- Hooks directly into existing registry endpoints; no new persistence needed.
- Uses the same config parsing already present in `server/config.py`, avoiding duplicate env handling.
- Shipping either interface still works in Docker: mount the static assets for the web UI or run the TUI inside `rag-server` as a one-off task.
