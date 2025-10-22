#!/usr/bin/env bash
set -e
# 첫 번째 인자 ($1)를 REPO_PATH로 사용하고, 인자가 없으면 기본값 설정
REPO_PATH=${1:-/workspace/myrepo}
# API 환경 변수(API)를 사용하고, 설정되지 않았으면 기본값 설정
API=${API:-http://localhost:8000}

echo "=================================================="
echo "API Endpoint: $API"
echo "Repository Path: $REPO_PATH"
echo "=================================================="

# 주: 일반적으로 검색 전에 레포지토리를 인덱싱하는 단계가 필요합니다. 
# 기존 스크립트는 이 부분을 명확하게 처리하지 않았으므로, 
# 사용자 요청에 따라 인덱싱 단계를 생략하고 바로 검색을 실행합니다.

echo "Starting search query: 'find unused functions' (k=10)"

# 사용자가 요청한 curl 테스트 코드를 API 변수와 함께 반영
curl -X POST "$API/search" \
     -H "Content-Type: application/json" \
     -d '{
  "query": "find unused functions",
  "k": 10
}'

echo ""
echo "Search completed."
