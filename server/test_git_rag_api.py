import requests
import subprocess
import os
import json
import time
from pathlib import Path

# --- 설정 ---
API_BASE_URL = "http://localhost:8000"
REPO_ID = "test_repo"
REPOS_DIR = Path("/workspace/myrepo")
REPO_PATH = REPOS_DIR / REPO_ID
STATE_FILE = Path("index_state.json")
BRANCH = "head"

# --- 유틸리티 함수 ---

def run_git(*args):
    """Git 명령어를 실행하고 출력을 반환합니다."""
    return subprocess.run(
        ["git", *args],
        cwd=REPO_PATH,
        capture_output=True,
        text=True,
        check=True
    ).stdout.strip()

def api_call(method, endpoint, json_data=None):
    """API 호출을 처리하고 응답을 반환합니다."""
    url = f"{API_BASE_URL}{endpoint}"
    print(f"\n[API 호출] {method} {url}")
    try:
        if method == "POST":
            response = requests.post(url, json=json_data, timeout=10)
        elif method == "GET":
            response = requests.get(url, timeout=10)
        else:
            raise ValueError("지원되지 않는 메소드")
            
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"API 호출 실패: HTTP Error {e.response.status_code}")
        print(f"응답 상세: {e.response.text}")
        raise
    except Exception as e:
        print(f"API 호출 중 예외 발생: {e}")
        raise

def setup_repo():
    """테스트 저장소를 초기화하고 첫 커밋을 생성합니다."""
    print("--- 1. 환경 및 저장소 준비 ---")
    # [변경 코멘트: Dubious Ownership 오류 해결]
    # Git의 'safe.directory' 오류를 해결하기 위해 현재 저장소 경로를 전역 설정에 추가합니다.
    # 이를 통해 소유권 불일치 문제를 우회하고 테스트를 진행할 수 있습니다.
    # REPO_PATH는 Path 객체이므로 str()로 변환해야 합니다.
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", str(REPO_PATH)], check=True)
    
    if REPO_PATH.exists():
        subprocess.run(["rm", "-rf", str(REPO_PATH)], check=True)
        
    REPO_PATH.mkdir(parents=True, exist_ok=True)    

    run_git("init", "-b", BRANCH)

    # [추가 코멘트: Git 환경 설정 추가] 커밋을 위해 사용자 정보를 설정합니다.
    # CI/CD 환경이나 격리된 환경에서 자주 필요합니다.
    run_git("config", "user.email", "test@example.com")
    run_git("config", "user.name", "Test User")

    # file_a.py 초기 버전
    (REPO_PATH / "file_a.py").write_text(
        "def initialize_context():\n"
        "    return 'context initialized'"
    )
    
    run_git("add", ".")
    run_git("commit", "-m", "Initial commit: initialize_context")
    global INITIAL_COMMIT
    INITIAL_COMMIT = run_git("rev-parse", "HEAD")
    print(f"초기 커밋 SHA: {INITIAL_COMMIT}")

def test_full_index():
    """전체 인덱싱 및 초기 검색을 테스트합니다."""
    print("\n--- 2. Full Index (전체 인덱싱) 테스트 ---")
    
    # 2A. 초기 전체 인덱싱
    result = api_call("POST", f"/repos/{REPO_ID}/index/full")
    assert result['status'] == 'success', "Full index 실패"
    assert result['last_commit'] == INITIAL_COMMIT, "Last commit 불일치"
    
    # 상태 파일 확인
    state = json.loads(STATE_FILE.read_text())
    assert state.get(REPO_ID) == INITIAL_COMMIT, "State 파일 업데이트 실패"
    print("Full Index 및 상태 업데이트 성공.")

    # 2B. 초기 검색
    search_query = "initialize context function"
    search_result = api_call("POST", "/search", {"query": search_query, "repo_id": REPO_ID, "k": 1})
    assert len(search_result) > 0, f"'{search_query}' 검색 결과 없음"
    assert "file_a.py" in search_result[0]['payload']['path'], "검색 결과 파일 불일치"
    print("초기 검색 성공.")

def test_commit_update_index():
    """새로운 커밋 기반의 증분 인덱싱을 테스트합니다."""
    print("\n--- 3. Commit Changes (커밋 변경) 테스트 ---")
    
    # 3A. 변경 커밋 생성
    
    # file_a.py 수정
    (REPO_PATH / "file_a.py").write_text(
        "def initialize_context():\n"
        "    return 'new context initialized'\n" # 내용 변경
        "\n"
        "def setup_db():\n" # 함수 추가
        "    pass"
    )
    # file_b.py 추가
    (REPO_PATH / "file_b.py").write_text("class Controller: pass")
    
    run_git("add", ".")
    run_git("commit", "-m", "Update A and Add B")
    global NEW_COMMIT
    NEW_COMMIT = run_git("rev-parse", "HEAD")
    print(f"새 커밋 SHA: {NEW_COMMIT}")
    assert NEW_COMMIT != INITIAL_COMMIT, "새 커밋 SHA가 이전과 동일함"

    # 3B. 증분 인덱싱 (커밋)
    result = api_call("POST", f"/repos/{REPO_ID}/index/update")
    assert result['status'] == 'success', "Commit update index 실패"
    assert result['last_commit'] == NEW_COMMIT, "Last commit 불일치"
    print("Commit Update Index 성공.")

    # 3C. 검증: 새로 추가된 함수 검색
    search_query = "Controller class definition"
    search_result = api_call("POST", "/search", {"query": search_query, "repo_id": REPO_ID, "k": 1})
    assert len(search_result) > 0, f"'{search_query}' 검색 결과 없음"
    assert "file_b.py" in search_result[0]['payload']['path'], f"'{search_result}' : file_b.py 검색 실패"
    print("새 파일/함수 검색 성공.")
    
    # 3D. 검증: No changes between commits
    # 같은 커밋으로 다시 실행 시 noop이 나와야 함 (수정된 인덱서 로직에 의해)
    result = api_call("POST", f"/repos/{REPO_ID}/index/update")
    assert result['status'] == 'noop', "No-change update index (commit) 실패"
    print("Commit Noop 테스트 성공.")

def test_local_update_index():
    """로컬 (Working Tree) 변경 기반의 증분 인덱싱을 테스트합니다."""
    print("\n--- 4. Local Changes (로컬 변경) 테스트 ---")

    # 4A. 로컬 파일 변경 (커밋하지 않음)
    (REPO_PATH / "file_b.py").write_text("class Controller: def run(): pass") # 내용 수정
    
    # 4B. 로컬 상태 확인
    status_result = api_call("GET", f"/repos/{REPO_ID}/status")
    assert "file_b.py" in status_result['modified'], f"로컬 상태(status) 확인 실패 : {status_result}"
    print("Local status 확인 성공.")
    
    # 4C. 증분 인덱싱 (로컬 모드)
    # base == head (NEW_COMMIT) 상태에서 호출
    result = api_call("POST", f"/repos/{REPO_ID}/index/update")
    assert result['status'] == 'success', "Local update index 실패"
    assert result['last_commit'] == NEW_COMMIT, "Last commit은 변경되지 않아야 함"
    print("Local Update Index 성공.")

    # 4D. 검증: 로컬 변경 내용 검색
    search_query = "Controller run method"
    search_result = api_call("POST", "/search", {"query": search_query, "repo_id": REPO_ID, "k": 1})
    assert len(search_result) > 0, f"'{search_query}' 검색 결과 없음 (로컬 변경 미반영)"
    print("로컬 변경 검색 성공.")
    
    # 4E. 검증: Noop (변경 없음)
    run_git("checkout", "--", "file_b.py") # 로컬 변경 되돌리기
    status_result = api_call("GET", f"/repos/{REPO_ID}/status")
    assert "file_b.py" not in status_result['modified'], "로컬 변경사항 되돌리기 실패"

    result = api_call("POST", f"/repos/{REPO_ID}/index/update")
    assert result['status'] == 'noop', "Local Noop 테스트 실패"
    print("Local Noop 테스트 성공.")


def main():
    try:
        setup_repo()
        test_full_index()
        test_commit_update_index()
        test_local_update_index()
        print("\n==============================")
        print("🎉 모든 테스트 시나리오 통과 🎉")
        print("==============================")
    except Exception as e:
        print("\n==============================")
        print(f"❌ 테스트 실패: {e}")
        print("==============================")

if __name__ == "__main__":
    main()