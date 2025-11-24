# Docker-based test quickstart

Run the unit tests inside the `rag-server` container to match the production environment. Ensure your repo is mounted so the container can see `tests/`.

Prerequisites:
- Export the variables from `.env.example` (at least `QDRANT_ENDPOINT`, `EMB_ENDPOINT`, `EMB_MODEL`, `HOST_REPO_PATH=$(pwd)`).
- Bring up the embedding stack (Qdrant + embedding backend):
  ```bash
  docker compose -f docker-compose.embedding.yml up -d --build
  ```

Execute tests from the repo root using the rag compose file (mounts the current repo into `/workspace/myrepo`):
```bash
docker compose -f docker-compose.rag.yml run --rm rag-server pytest tests/test_repository_registry.py
```
Swap the test path to run other suites, for example:
```bash
docker compose -f docker-compose.rag.yml run --rm rag-server pytest tests
```

If you see “file or directory not found” for tests, the repo likely was not mounted. Re-run with an explicit absolute path:
```bash
export HOST_REPO_PATH=$(pwd)  # absolute path to this repo
docker compose -f docker-compose.rag.yml run --rm -e HOST_REPO_PATH -w /workspace/myrepo rag-server pytest tests/test_repository_registry.py
```

When finished, stop the containers if you do not need them:
```bash
docker compose -f docker-compose.embedding.yml down
docker compose -f docker-compose.rag.yml down
```
