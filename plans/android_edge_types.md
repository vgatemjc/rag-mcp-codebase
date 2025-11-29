# Android Structural Edge Types

Context: follows `plans/plan_structural_edges.md` minimal schema (`type`, `target`, optional `meta`) and keeps targets repo-relative or stack-normalized ids so responses and MCP tools can expose edges consistently without extra Qdrant filter fields.

## Edge Types and Example Payloads

- `NAV_DESTINATION`  
  - Meaning: Navigation graph node points to a destination fragment/activity.  
  - Target format: navigation destination id (lowercase, stripped of `@+id/`).  
  - Example payload: `{"type": "NAV_DESTINATION", "target": "home_fragment"}`  
  - Extraction: XML navgraph parser walks `<fragment/>`/`<activity/>` nodes, grabs `android:id` or `app:id`, emits one edge per destination.

- `NAV_ACTION`  
  - Meaning: Navigation action from a source destination to another.  
  - Target format: destination id referenced by the action.  
  - Example payload: `{"type": "NAV_ACTION", "target": "detail_fragment", "meta": {"source": "home_fragment", "id": "action_home_to_detail"}}`  
  - Extraction: For each `<action>` inside a nav node, read `app:destination` (or `android:destination`), set `meta.source` to the containing node id, include `meta.id` if present.

- `BINDS_LAYOUT`  
  - Meaning: Activity/Fragment/Composable binds or inflates a layout XML.  
  - Target format: layout path/id like `layout/main_activity.xml` (repo-relative under `res/layout`).  
  - Example payload: `{"type": "BINDS_LAYOUT", "target": "layout/main_activity.xml"}`  
  - Extraction: Kotlin/Java scan for `setContentView(R.layout.*)` or `inflate(R.layout.*)`, XML manifest theme/layout hints, or Compose `setContent` wrappers that load `R.layout`. Normalize to `layout/<name>.xml`.

- `NAVIGATES_TO` (optional alias when graphless navigation is inferred)  
  - Meaning: Imperative navigation call between screens without a navgraph (e.g., `startActivity`, `findNavController().navigate`).  
  - Target format: destination component name or id; prefer screen_name if known.  
  - Example payload: `{"type": "NAVIGATES_TO", "target": "detailactivity", "meta": {"source": "homeactivity"}}`  
  - Extraction: Lightweight call-site heuristic in Kotlin/Java; when navgraph context is missing, emit this edge with best-effort source/destination names.

- `USES_VIEWMODEL`  
  - Meaning: Screen binds to a ViewModel instance.  
  - Target format: fully qualified ViewModel class or short name.  
  - Example payload: `{"type": "USES_VIEWMODEL", "target": "com.example.ui.HomeViewModel"}`  
  - Extraction: Detect `by viewModels<>()`, `ViewModelProvider(...)`, or data-binding `<variable type="...ViewModel">` in layout XML; emit edge from screen chunk to ViewModel class name.

- `CALLS_API` (forward-looking; aligns with structural edges plan)  
  - Meaning: Screen or use-case calls a network API wrapper/client.  
  - Target format: client class or endpoint id (e.g., `ApiClient.getUser`, `/users/{id}`).  
  - Example payload: `{"type": "CALLS_API", "target": "UserService.getUser", "meta": {"http_method": "GET", "path": "/users/{id}"}}`  
  - Extraction: Kotlin/Java parse Retrofit interface refs, OkHttp calls, or typed client invocations; capture HTTP method/path when available.

## Implementation Design Notes

- Centralize edge constants and normalization under `server/services/edges/edge_types.py` and builders (per `plan_structural_edges.md`), and update the Android plugin to emit through shared helpers.  
- Keep edge payloads attached to chunks in `payload["edges"]` to avoid new Qdrant filter fields; targets stay lowercase and repo-relative where applicable.  
- Normalize ids: strip `@+id/`, lowercase `screen_name`, and keep layouts as `layout/<file>.xml`.  
- Tests: add fixture repos with navgraph + layout-binding cases to assert each edge type is emitted and surfaced in search/MCP responses; include a stub second stack for cross-stack compatibility.
