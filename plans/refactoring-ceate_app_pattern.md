📘 Create App 패턴 기반 리팩토링 Task Spec (for Codex / MCP)
🎯 Goal

server/git_rag_api.py에 과도하게 집중된 API/Router/Service/State/Indexing 로직을 create_app 패턴 기반의 모듈 구조로 재구성한다.
리팩토링 후 구조는 다음을 충족해야 한다:
*FastAPI 인스턴스는 create_app() 함수 내에서만 생성
*모듈 로딩 시 외부 API 호출(Qdrant, Embeddings 등) 발생 금지
*Router, Model, Service가 분리된 구조 유지
*pytest에서 import 시 side-effect 없이 로드 가능
*기존 기능(API + Indexing + Registry + Search) 모두 유지

📁 Target Directory Structure
*아래 구조로 파일을 재배치한다:
server/
│
├── app.py                     ← create_app() 정의
├── main.py                    ← uvicorn entrypoint
├── config.py                  ← Config 클래스
│
├── routers/
│   ├── registry_router.py
│   ├── index_router.py
│   ├── search_router.py
│   └── status_router.py
│
├── models/
│   ├── repository.py          ← RepositoryIn, RepositoryOut, RepositoryUpdate, RegistryWebhook
│   ├── index.py
│   ├── search.py
│   └── status.py
│
├── services/
│   ├── repository_registry.py ← 기존 코드 분리
│   ├── git_aware_code_indexer.py
│   ├── repo2md_ts.py
│   ├── state_manager.py       ← load_state(), save_state 등
│   └── initializers.py        ← ensure_collection / resolve_clients
│
└── git_rag_api.py             ← 삭제 또는 deprecated stub

🧱 Refactoring Requirements
1. create_app() 정의 (app.py)
*FastAPI 객체는 함수 내부에서 생성해야 한다.
*반환값은 FastAPI 인스턴스.
*startup 이벤트에서만 Qdrant / Embedding 초기화를 수행해야 한다.
*앱 상태(app.state) 구조:
   app.state.config
   app.state.registry
   app.state.initializer

2. 전역 초기화 코드 제거
git_rag_api.py에 있던 다음 코드는 모두 create_app으로 이동해야 한다:
*QdrantClient 생성
*Registry 생성
*VectorStore 캐시 초기화
*Embedding Client 캐시 초기화
*ensure_collection() 실행
*이것들은 모듈 레벨에서 실행되면 pytest import 시 강제 실행되는 side-effect이므로 금지.

3. Router 분리
git_rag_api.py 에 존재하는 다음 endpoint 그룹을 파일 분리:
*📌 registry_router.py
*리스트 조회
*레포 생성
*레포 업데이트
*삭제
*webhook

📌 index_router.py
*full index
*update index
*generate progress SSE

📌 search_router.py
*/search endpoint

📌 status_router.py
*/repos/{repo_id}/status

4. Model 분리 (models/*)
RepositoryOut, RepositoryIn, RepositoryUpdate 등 모든 Pydantic 모델은 router보다 위쪽 모듈로 이동해야 한다.
모든 모델은 아래 규칙을 따른다:
*from_attributes = True 설정
*timestamp 필드는 datetime aware로 유지
*DB 모델과 Response 모델은 분리

5. Service 계층 도입 (services/*)
다음 기능은 모두 Service 계층으로 분리해야 한다:
*repository_registry.py
  ensure_repository
  get_repository
  8update_repository
  delete_repository
  list_repositories

*git_aware_code_indexer.py
  GitAware, Chunker, Indexer 등 기존 로직 유지

*state_manager.py
  load_state()
  save_state()

*initializers.py
  ensure_collection()
  resolve_clients()
  qdrant_admin / vector_store cache 관리

6. main.py 생성
실행 엔트리포인트:
from server.app import create_app
app = create_app()

7. git_rag_api.py 정리
deprecated stub 파일로 남겨두거나 삭제한다.
파일이 존재해야 backward compatibility 유지 시 import error 방지 가능.

🚫 Forbidden

아래 사항은 절대로 발생하면 안 됨:
*create_app() 함수 밖에서 FastAPI app 생성
*모듈 import 시 외부 API 연결(Qdrant, Embedding API) 실행
*Router가 create_app보다 먼저 app을 참조
*Qdrant Client / Embeddings Client / Indexer가 전역에서 생성

✔ Acceptance Criteria (AC)
*pytest 실행 시 단 하나의 외부 API 호출도 발생하지 않아야 한다.
*import server.app 시 아무 부작용이 없어야 한다.
*app = create_app() 수행 시 정상적으로 router가 등록되어야 한다.
*기존 모든 API endpoint가 정상 동작해야 한다.
*create_app 패턴을 통해 서로 다른 설정(config)을 주입할 수 있어야 한다.

🎯 Bonus (Optional)
dependency injection container (app.state.container) 구현
EmbeddingClient / VectorStore를 DI 기반으로 자동 생성
create_app(testing=True) 모드 지원

📌 Output Expected
리팩토링 완료 후 구성된 프로젝트 전체 파일 세트.
각 파일은 독립적으로 테스트 가능하며, uvicorn server.main:app 실행 시 정상 작동해야 한다.

---

## Progress Log
- [x] Introduced `server/app.py` with `create_app()` plus `server/main.py`/`server/git_rag_api.py` entrypoints.
- [x] Split routers (`server/routers/*`), models (`server/models/*`), and shared services/config helpers per this spec.
- [x] Updated README/AGENTS to document the new layout and commands.
- [ ] Dependency installation + `python -m pytest tests/test_repository_registry.py` (blocked: even after creating `.venv` the sandbox cannot reach PyPI: `.venv/bin/pip install -r server/requirements.txt` fails with `Failed to establish a new connection` for `fastapi==0.115.0`).
