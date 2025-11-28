# Multi-Stack Code RAG Architecture (Aligned to This Repo)

## 1. Overview

This document summarizes a generalized RAG architecture and maps it to
the current RAG + MCP codebase so we can support not only **Android App**
code, but also:

-   Android Framework / SDK\
-   Linux Drivers\
-   Micom / Firmware\
-   C / C++ / Rust native components\
-   Any software/hardware stack with partial or non-traceable
    dependencies

The core idea:\
**"Android is not special. All systems have non-code dependencies.\
Therefore: one RAG Core + stack‑specific analyzers."**

------------------------------------------------------------------------

### How the current repo already supports this

-   FastAPI app (`server/app.py`) exposes registry, indexing, status, and
    search routers; `git_rag_api.py` re-exports the same app.
-   Registry-backed routing (`server/routers/`) resolves repo metadata
    and sandbox state before indexing/searching.
-   Tree-sitter chunking and Git-aware incremental indexing live in
    `server/services/git_aware_code_indexer.py` (chunks, embeddings
    client, Qdrant store, diff-based `index_commit`).
-   Per-repo client bootstrap is centralized in
    `server/services/initializers.py` (ensures collections, returns TEI
    embeddings + Qdrant store).
-   MCP worker (`server/git_rag_mcp.py`) surfaces the same retrieval
    capabilities as MCP tools.
-   Sandbox worktrees (`server/services/sandbox_manager.py`) allow
    user-isolated branches, which is key when mixing stacks or hardware
    configs.

Use these existing hooks instead of inventing new plumbing—multi-stack
analyzers should plug into the chunker, metadata payload, and registry
flows.

------------------------------------------------------------------------

## 2. Motivation

Different stacks exhibit different patterns: - Android relies on
Manifest, Layouts, NavGraph, Intent, lifecycle, DI, reflection. - Linux
drivers depend on Device Tree, Kconfig, sysfs, userspace daemons. -
Micom firmware depends on interrupts, protocols, task scheduler,
calibration tables.

In all cases: - **Code-only dependency tracing is incomplete.** -
**Behavior is determined by external events, configurations, and system
wiring.**

Therefore, the RAG platform must support: - Code relationships **and** -
Non-code relationships (config, events, protocols, hardware bindings)

------------------------------------------------------------------------

## 3. Architecture Overview

### Three-LLayer Design

                ┌───────────────────────────┐
                │         User Query        │
                └───────────────┬───────────┘
                                ▼
                        (1) Embedding
                                ▼
                   (2) Meta Filtering Layer
                                ▼
                  (3) Code Index (Vector Search)
                                ▼
             (4) Structural Graph Expansion Layer
                                ▼
                       (5) LLM Reasoning

------------------------------------------------------------------------

## 4. Core Components (Stack-Agnostic)

### 4.1 Code Index (Existing)

-   Chunk source code by AST (tree-sitter)
-   Vector embedding (query + doc)
-   Used for semantic code search

In this repo: `Chunker` (tree-sitter + fallback) → `Embeddings` client
(TEI/vLLM/Ollama) → `VectorStore` (Qdrant) managed by `Indexer`.

### 4.2 Meta Index (Unified Schema)

Common fields across all stacks:

  Field              Description
  ------------------ ---------------------------------------------------
  `stack_type`       android_app, framework, linux_driver, micom, etc.
  `language`         cpp, c, rust, kotlin, java, xml, etc.
  `module`, `path`   location in repo
  `kind`             class, method, function, struct, layout, config
  `symbol_name`      function/class/entry name

Stack-specific metadata added by plugin: - Android: `android_role`,
`screen_name` - Linux: `subsystem`, `driver_name` - Micom: `task`,
`core`, `state_machine`

Meta is **not embedded**, only used for filtering / boosting.

In this repo: payload is built in `Indexer._build_payload`; extend that
to inject stack-specific meta and ensure `index_router` passes through
the requested `stack_type`/collection. Add registry defaults so UI +
MCP tools advertise the stack type.

### 4.3 Structural Graph Index

All stacks share fundamental edge types:

  -----------------------------------------------------------------------
  Edge Type                        Description
  -------------------------------- --------------------------------------
  `CALLS`                          caller → callee

  `INCLUDES` / `IMPORTS`           file/module reference

  `READS` / `WRITES`               variable/register access

  `IMPLEMENTS` / `OVERRIDES`       inheritance

  `CONFIG_DEPENDS_ON`              Manifest, Device Tree, Kconfig, YAML,
                                   Gradle, etc.
  -----------------------------------------------------------------------

Stack-specific edges: - Android: `BINDS_LAYOUT`, `NAVIGATES_TO`,
`USES_VIEWMODEL` - Linux: `HANDLES_IRQ`, `MAPS_REGISTER`,
`EXPOSES_SYSFS` - Micom: `IRQ_FLOW`, `STATE_TRANSITION`, `MESSAGE_FLOW`

------------------------------------------------------------------------

## 5. Analyzer Plugin Architecture

Each stack uses a plugin that defines: - How to chunk files\
- How to extract metadata\
- How to detect relationships (edges)

### Example Plugin Types

#### Android App Analyzer

-   Parse: Kotlin/Java + XML
-   Meta: `android_role`, `screen_name`, `nav_graph_id`
-   Edges: layout binding, nav flow, manifest components

#### Android Framework Analyzer

-   AIDL / Binder / SystemService relationships

#### Linux Driver Analyzer

-   Device Tree, Kconfig, IRQ, register map
-   Subsystem classification (USB, NET, I2C...)

#### Micom/Firmware Analyzer

-   ISR → task transitions\
-   Communication protocol handlers\
-   State machine transitions

All plugins output: - Chunks\
- Meta records\
- Graph edges

Integration points in this repo:

-   **Chunking:** extend `Chunker.for_language` to recognize stack
    extensions (e.g., `.aidl`, `Kconfig`, DTS) and implement
    specialized chunkers if needed.
-   **Meta:** update `Indexer._build_payload` to attach plugin meta and
    augment `repository_registry` to store default `stack_type`,
    `collection`, and embedding model per repo.
-   **Graph:** introduce a new service (e.g., `structural_graph.py`) to
    persist edges to Qdrant payloads or a sidecar store; expose via
    `search_router` expansion.
-   **UI/MCP:** surface new filter options in `/registry/ui/meta` and
    MCP tools so clients can request stack-aware retrieval.

------------------------------------------------------------------------

## 6. Retrieval Pipeline (Generalized)

1.  **Query → embedding**\
2.  **Meta filter** (by stack, subsystem, role, screen)\
3.  **Vector search on code index**\
4.  **Graph expansion**
    -   bring callers, callees, config links, ISR links, nav links,
        layout links\
5.  **LLM reasoning**
    -   root-cause analysis\
    -   refactoring plan\
    -   flow explanation\
    -   code generation\
    -   cross-stack dependency reasoning

In this repo: `/search` → `Retriever.search` (vector search + optional
filters) today. Next steps: add graph expansion layer plus MCP tool to
request structural context.

------------------------------------------------------------------------

## 7. Benefits

### 7.1 Unified Architecture

One system for: - Android apps\
- Framework / HAL\
- Linux kernel driver\
- Micom firmware

### 7.2 Traceability for non-traceable domains

Handles: - Lifecycle callbacks\
- Manifest-based components\
- Device Tree → driver mapping\
- Interrupt → task transitions\
- Communication message flows

### 7.3 Multi-stack Vibe Coding

Developers can ask: - "이 함수가 호출되는 전체 흐름 보여줘" - "이
디바이스 트리 노드와 연결된 드라이버는?" - "이 ISR과 이어지는 Micom task
흐름은?" - "이 화면의 네비게이션 전체 구조?" - "이 SDK 기능을 기존 앱에
파생 적용하려면?"

------------------------------------------------------------------------

## 8. Final Insight

> Android만 특이한 것이 아니라,\
> 모든 시스템은 "코드 밖/옆"의 설정·이벤트·프로토콜에 의해 동작한다.\
> 그러므로 **공통 RAG Core 위에 스택별 Analyzer를 얹는 구조가
> 정답이다.**

이 방식이면: - 여러 플랫폼의 코드를 **한 시스템에서** 분석할 수 있고\
- 버그 분석 / 리팩토링 / 파생 개발 / 유지보수 모두 지원 가능하다.

### Action items for this codebase

-   Add stack-type defaults to the registry payload/UI.
-   Extend chunker + payload builder with stack-aware metadata.
-   Prototype one plugin (e.g., Linux driver: DTS/Kconfig) to validate
    graph edges and retrieval filters.
-   Expose graph-augmented search via API + MCP tools, keeping the
    `create_app` router wiring intact.
