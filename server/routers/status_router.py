from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from server.config import Config
from server.models.index import IndexStatus
from server.models.status import StatusResponse
from server.services.git_aware_code_indexer import GitCLI
from server.services.repository_registry import RepositoryRegistry
from server.services.state_manager import get_repo_path

router = APIRouter(prefix="/repos", tags=["status"])


def _config(request: Request) -> Config:
    return request.app.state.config


def _registry(request: Request) -> RepositoryRegistry:
    return request.app.state.registry


@router.get("/{repo_id}/status", response_model=StatusResponse)
def get_local_status(request: Request, repo_id: str):
    config = _config(request)
    registry = _registry(request)
    defaults = {
        "name": repo_id,
        "collection_name": config.COLLECTION,
        "embedding_model": config.EMB_MODEL,
    }
    repo = registry.ensure_repository(repo_id, defaults)
    if repo.archived:
        raise HTTPException(status_code=400, detail=f"Repository '{repo_id}' is archived")

    try:
        repo_path = get_repo_path(config.REPOS_DIR, repo_id)
        git = GitCLI(str(repo_path))
        status_out = git._run("status", "--porcelain", "--untracked-files=no") or ""
        modified, added, deleted, renamed = [], [], [], []
        status_letters = ("M", "A", "D", "R")

        for line in status_out.splitlines():
            if len(line) < 3:
                continue
            x_status = line[0]
            y_status = line[1]
            file_path = line[3:].strip()

            status = ""
            if x_status in status_letters:
                status = x_status
            elif y_status in status_letters:
                status = y_status

            if not status:
                continue

            if status == "M":
                modified.append(file_path)
            elif status == "A":
                added.append(file_path)
            elif status == "D":
                deleted.append(file_path)
            elif status == "R":
                renamed.append(file_path)

        return StatusResponse(modified=modified, added=added, deleted=deleted, renamed=renamed)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{repo_id}/index/status", response_model=IndexStatus)
def get_index_status(request: Request, repo_id: str):
    config = _config(request)
    registry = _registry(request)
    defaults = {
        "name": repo_id,
        "collection_name": config.COLLECTION,
        "embedding_model": config.EMB_MODEL,
    }
    repo = registry.ensure_repository(repo_id, defaults)

    return IndexStatus(
        repo_id=repo.repo_id,
        last_indexed_commit=repo.last_indexed_commit,
        last_indexed_at=repo.last_indexed_at,
        last_index_mode=repo.last_index_mode,
        last_index_status=repo.last_index_status,
        last_index_error=repo.last_index_error,
        last_index_started_at=repo.last_index_started_at,
        last_index_finished_at=repo.last_index_finished_at,
        last_index_total_files=repo.last_index_total_files,
        last_index_processed_files=repo.last_index_processed_files,
        last_index_current_file=repo.last_index_current_file,
    )
