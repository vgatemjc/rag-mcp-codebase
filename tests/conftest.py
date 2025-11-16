# tests/conftest.py 파일 내용
import sys
from pathlib import Path

# 현재 파일(__file__)의 상위 디렉토리(tests/)의 상위 디렉토리(루트)에 있는 'server' 디렉토리를 경로에 추가
# 프로젝트 구조가 루트/server/code.py 와 루트/tests/test.py 일 때
sys.path.append(str(Path(__file__).parent.parent / "server"))
