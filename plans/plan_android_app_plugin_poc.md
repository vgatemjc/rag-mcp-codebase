# Android App Analyzer Plugin – POC Plan

Status: POC implemented with Android stack routing, metadata extraction,
and tests; work tracked here is considered complete. Remaining edge
enhancements will be handled in a dedicated structural-edges plan.
Items below marked ✅ (done) or ⏳ (not done).

Objective: validate the multi-stack RAG design by delivering a working
Android App plugin that enriches indexing/search with stack-aware meta
and structural context.

## Scope & Goals
- Parse Kotlin/Java + XML (manifest, layouts, navigation graphs).
- Emit stack-aware metadata on chunks and edge stubs for UI/logic
  navigation.
- Wire filters so search/MCP can scope by stack/screen/component.
- Keep persistence simple: reuse existing Qdrant payloads; defer a
  dedicated graph store.

## Repo Touchpoints (existing components)
- `server/services/git_aware_code_indexer.py`: Chunker, payload builder,
  indexer (upsert to Qdrant), **payload plugin hook** and `base_payload`
  merge point.
- `server/services/initializers.py`: collection/model selection per repo.
- `server/services/repository_registry.py` + routers: carry defaults
  (stack type, collection, embedding model).
- `server/git_rag_mcp.py` + `/search`: expose filters/tools.
- `server/static/registry_ui/*`: surface stack defaults/options.

## Work Plan
1) **Stack detection & config** ✅
   - Add `stack_type` default to registry model + UI meta (e.g.,
     `stack_type="android_app"`). ✅
   - Pass `base_payload={"stack_type": ...}` into `Indexer` and keep
     stack-specific fields isolated in a `PayloadPlugin` implementation
     (no case statements in `_build_payload`). ✅ (hook + env stack_type)
   - Implement `AndroidPayloadPlugin.build_payload(...)` to add optional
     `screen_name`, `android_role`, `component`, `layout_file`, etc. ✅
     (basic heuristics)
   - Extend `index_router` and MCP tool args to accept optional
     `stack_type`/filters and route plugin selection based on registry
     defaults. ✅

2) **Chunking architecture (common + plugin hooks)** ✅
   - Keep core chunking flow in `Chunker.chunks(...)` and
     `Chunker.for_language` for language detection and generic slicing.
   - Introduce a `ChunkPlugin` protocol with hooks like
     `supports(path) -> bool`, `preprocess(src, path) -> str`,
     `postprocess(chunks) -> List[Chunk]`, and optional
     `extra_chunks(src, path, repo) -> List[Chunk]`.
   - Register plugins per stack and have `Chunker.chunks` call them when
     `stack_type` is present (no switch/case; iterate plugins that
     `supports` the path). ✅
   - Android plugin responsibilities:
     - XML-aware preprocessing for manifest/layout/nav graph (preserve
       ids/names).
     - Postprocess Kotlin/Java chunks to tag block ids with component
       info (if detected via annotations or file path).
     - Emit synthetic chunks for NavGraph/layout summaries if helpful.
   - Ensure plugins cannot break common pipeline: fall back gracefully
     on exceptions and preserve base chunks.

3) **Chunking enhancements (Android plugin)** ✅ (first draft)
   - Ensure `Chunker.for_language` routes `.kt`, `.java`, `.xml` to
     tree-sitter; plugin can override handling for XML types. ✅ (plugin
     wired)
   - Add lightweight XML chunker variant that preserves element
     boundaries and ids (e.g., `android:id`, `name`, `action`). ⏳
     (synthetic XML summary chunks with ids/actions; full boundary-aware
     chunking still pending)
   - Use plugin hooks to attach `stack_type` context to chunks and to
     inject layout/navgraph synthetic chunks. ✅ (synthetic XML summary
     chunk)

4) **Metadata extraction (POC depth)** ✅ (heuristics)
   - Manifest: component type (`activity`, `service`, `receiver`),
     component name, intent-filters (actions/categories).
   - Layout XML: `layout_file`, `view_ids`, `viewmodel_class` (if
     data-binding), `fragment_tag`. ✅
   - NavGraph: `nav_graph_id`, destinations, actions. ✅ (heuristic
     extraction)
   - Kotlin/Java: class name, file path; optional `@Composable` flag
     (detect via annotation) but keep as stretch. ⏳ (class-name suffix
     heuristic only)
   - Store these as payload fields on relevant chunks. ✅ (payload plugin
     tags)

5) **Structural edges (minimal viable)** ⏳ (navgraph edges shipped)
   - Represent edges as payload lists on involved chunks (e.g.,
     `edges: [{type:"BINDS_LAYOUT", target:"layout/main_activity.xml"}]`)
     to avoid new storage.
   - Edge sources:
     - Manifest component → layout (by `android:theme`/`layout` hints if
       present).
     - Activity/Fragment → layout (by setContentView / inflate call).
     - NavGraph → destination fragments/activities. ✅ (edges emitted)
   - Keep schema small: `type`, `target`, `meta` (dict).

6) **Search & MCP integration** ✅
   - Allow `/search` and MCP `semantic_code_search` to accept
     `stack_type` and simple meta filters (e.g., `screen_name`,
     `component`).
   - In results, surface edge payloads so clients can hop to related
     code/layouts.
   - When filtering navgraphs, use the actual nav graph id from
     `android:id` (e.g., `main_navigation`), not the filename unless
     they match; filters are normalized to lowercase.

7) **Filter discipline (avoid Qdrant filter bloat)** ✅
   - Keep filterable fields minimal and consistent: `stack_type`,
     `component_type`, `screen_name`, and a short `tags` list of
     normalized strings.
   - Store richer stack-specific details under a non-filtered map
     (e.g., `stack_meta`) and expose for display/expansion only.
   - If keyword matching is needed, add a single `stack_text` field and
     use `MatchText`; avoid many bespoke filter fields.
   - Document allowed filters per stack and enforce them in router/MCP
     arg validation so plugins cannot proliferate payload fields.

8) **Validation** ⏳ (unit coverage added; fixture/integration pending)
   - Add fixture repo with minimal Android-like structure (Manifest +
     1-2 activities/fragments, layout, nav graph) inside tests fixtures
     (no build tools needed). ⏳
   - Unit tests:
     - Payload contains `stack_type` and extracted manifest/layout/meta. ✅
     - Edge payloads exist for activity→layout, navgraph→destination.
       ✅ (navgraph only; activity/layout pending)
   - Integration-style: index fixture repo and ensure search filtered by
     `stack_type` returns expected chunks. ⏳

9) **Non-goals (POC)** ✅ (defined)
   - Full Gradle/project model, resource merging, DI graph resolution.
   - AIDL/system service analysis.
   - Dedicated graph store beyond payload embedding.

## Open Questions
- Where to centralize edge schema constants (`edges.py` module?) for
  future stacks.
