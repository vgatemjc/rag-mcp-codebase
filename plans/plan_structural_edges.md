# Structural Edges – Cross-Stack Plan

Objective: centralize structural edge extraction and payload shaping so
multiple stacks (android_app, web_frontend, etc.) can emit consistent
edge data during indexing and expose it in search/MCP responses.

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

## Open Discussion
- Should edge targets be fully qualified URIs (e.g., `android://` or
  repo-relative paths) vs. short ids? How to map across stacks?
- Where should edge traversal live (API layer vs. client)? Do we need
  helper routes to fetch related nodes by edge?
- How to handle versioning/compatibility if edge schemas evolve (e.g.,
  optional metadata blobs per edge type)?
