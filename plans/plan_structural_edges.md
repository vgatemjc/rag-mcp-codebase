# Structural Edges – Cross-Stack Plan

Objective: centralize structural edge extraction and payload shaping so
multiple stacks (android_app, web_frontend, etc.) can emit consistent
edge data during indexing and expose it in search/MCP responses.
Reference: see `plans/android_edge_types.md` for Android-specific edge
types, targets, and sample payloads to implement.
Progress: implementation in-flight — shared edge helpers added, Android navgraph/viewmodel edges wired; extended heuristics for BINDS_LAYOUT/NAVIGATES_TO/CALLS_API with tests added; last dockerized test run was blocked by Docker socket permissions after regex fix (rerun needed).

## New Package Needed
- Create `server/services/edges/` with:
  - `__init__.py` exporting shared types/helpers.
  - `edge_types.py` defining constants/enums (e.g., `BINDS_LAYOUT`,
    `NAV_DESTINATION`, `CALLS_API`), normalized target formats, and
    minimal schemas (`EdgePayload` dataclass/TypedDict).
  - `builder.py` with helpers to merge/dedup edge payloads, normalize
    targets, and validate shape before persistence.
  - `plugins.py` defining a `StructuralEdgePlugin` protocol and stack-
    specific implementations (Android, future stacks) that operate on
    parsed files/chunks and return edge payloads.

## Structural Changes
- Extend the indexing pipeline to accept edge plugins per stack: wire
  into `Chunker` or `Indexer` so plugins can inspect paths/chunks and
  emit edges without disrupting base chunking.
- Update the Android plugin to emit edges via the shared helpers and
  target formats (manifest→component, component→layout/nav, Compose
  navigation as available).
- Add router/MCP response shaping to expose edge payloads consistently
  and ensure filters remain minimal (no extra Qdrant filter fields).
- Add fixture repos and tests that assert edge extraction for Android
  and a second stack (stub) to validate cross-stack compatibility.

## Detailed Action & Testing Plan
1. Edge Package Setup
1.1 Create `server/services/edges/` with `__init__.py`, `edge_types.py`, `builder.py`, `plugins.py`.
1.2 Codify edge enums/constants (per `plans/android_edge_types.md`: `BINDS_LAYOUT`, `NAV_DESTINATION`, `NAV_ACTION`, `NAVIGATES_TO`, `USES_VIEWMODEL`, `CALLS_API`, etc.) and payload schema (type/target/meta).
1.3 Implement helpers for target normalization (ids, repo-relative paths), deduping, and validation.
1.4 Add lightweight docstrings/type hints; keep ASCII only.

2. Android Integration
2.1 Refactor `server/services/android_plugins.py` to emit edges through the shared builder (navgraph edges first, then layout binding) using the payload shapes in `plans/android_edge_types.md`.
2.2 Add Compose/navigation heuristics for `BINDS_LAYOUT`/`NAVIGATES_TO` when navgraph absent; include `USES_VIEWMODEL` from data-binding/ViewModel detection.
2.3 Normalize ids to lowercase, strip `@+id/`, and use `layout/<file>.xml` targets.
2.4 Ensure `payload["edges"]` is populated without expanding Qdrant filter fields; include `NAV_ACTION` meta (`source`, `id`) as documented.
2.5 Wire optional `CALLS_API` edge emission (Retrofit/OkHttp heuristics) but keep filters unchanged.

3. Pipeline Wiring
3.1 Extend `Chunker`/`Indexer` to accept stack-specific edge plugins; pass stack_type through existing metadata plumbing.
3.2 Ensure edges are attached to chunk payloads during indexing and survive commit/working-tree modes.
3.3 Keep router/MCP responses surfacing `edges` verbatim; avoid new filter keys beyond existing `stack_type`/`component_type`/`screen_name`/`tags`.

4. Fixtures & Tests
4.1 Add Android fixture repo with manifest, layouts, navgraph, and Kotlin/Java binding call sites (layout + nav edges).
4.2 Add Android fixture coverage for `NAV_DESTINATION`, `NAV_ACTION` (with meta), `BINDS_LAYOUT`, `NAVIGATES_TO`, `USES_VIEWMODEL`, and (if implemented) `CALLS_API` per `plans/android_edge_types.md`.
4.3 Add second-stack stub fixture (e.g., simple web_frontend) to assert cross-stack plugin compatibility and no edge leakage.
4.4 Tests: `python -m pytest tests/test_android_plugins.py` additions for edge payloads; new tests for edge builder normalization/deduping; integration test in `server/test_git_rag_api.py` or new `tests/test_edges_in_index.py` to verify edges surface via indexing + search/MCP responses; include explicit edge payload shape assertions matching `plans/android_edge_types.md`.
4.5 Dockerized workflow (per `plans/docker-testing-workflow.md`): run suites via `docker compose -f docker-compose.rag.yml run --rm rag-server pytest …` and the E2E smoke `docker compose -f docker-compose.rag.yml run --rm rag-server python server/test_git_rag_api.py`; keep embedding stack untouched, rely on rag stack for Qdrant, ensure `PYTHONPATH=/workspace/myrepo` and health checks satisfied; only skip Qdrant via `SKIP_COLLECTION_INIT=1` when explicitly noted.

5. Validation & Docs
5.1 Update `.env.example`/docs only if new env keys arise (avoid adding filter fields).
5.2 Add short README note in `server/services/edges/` describing schema and plugin expectations.
5.3 Capture response examples for navgraph and layout-binding edges for PR notes.

## Open Discussion
- Should edge targets be fully qualified URIs (e.g., `android://` or
  repo-relative paths) vs. short ids? How to map across stacks?
- Where should edge traversal live (API layer vs. client)? Do we need
  helper routes to fetch related nodes by edge?
- How to handle versioning/compatibility if edge schemas evolve (e.g.,
  optional metadata blobs per edge type)?
