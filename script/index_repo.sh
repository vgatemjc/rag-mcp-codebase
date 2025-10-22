#!/usr/bin/env bash
set -e
REPO_PATH=${1:-/workspace/myrepo}
API=${API:-http://localhost:8000}

echo "Indexing $REPO_PATH"
curl -s -X POST "$API/index" -H 'Content-Type: application/json' -d "{\"repo_path\": \"$REPO_PATH\"}"
