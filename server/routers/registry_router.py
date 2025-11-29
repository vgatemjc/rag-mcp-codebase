from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, status

from server.config import Config
from server.models.datastore_reset import DatastoreResetRequest, DatastoreResetResponse
from server.models.repository import (
    RegistryWebhook,
    RepositoryIn,
    RepositoryOut,
    RepositoryUpdate,
)
from server.models.sandbox import SandboxCreate, SandboxOut, SandboxUpdate
from server.services.datastore_reset import DatastoreResetService
from server.services.initializers import Initializer
from server.services.repository_registry import RepositoryRegistry
from server.services.sandbox_manager import SandboxManager

router = APIRouter(prefix="/registry", tags=["registry"])


def _registry(request: Request) -> RepositoryRegistry:
    return request.app.state.registry


def _sandboxes(request: Request) -> SandboxManager:
    return request.app.state.sandbox_manager


def _config(request: Request) -> Config:
    return request.app.state.config


def _initializer(request: Request) -> Initializer:
    return request.app.state.initializer


def normalize_repository_payload(config: Config, payload: RepositoryIn) -> dict:
    """Align repository defaults for preview/create flows."""
    data = payload.model_dump()
    data["name"] = data.get("name") or payload.repo_id
    data["collection_name"] = data.get("collection_name") or config.COLLECTION
    data["embedding_model"] = data.get("embedding_model") or config.EMB_MODEL
    data["stack_type"] = data.get("stack_type") or config.STACK_TYPE
    return data


@router.get("", response_model=List[RepositoryOut])
def list_registry_entries(request: Request, include_archived: bool = False):
    entries = _registry(request).list_repositories(include_archived=include_archived)
    return [RepositoryOut.model_validate(entry) for entry in entries]


@router.get("/{repo_id}", response_model=RepositoryOut)
def get_registry_entry(request: Request, repo_id: str):
    repo = _registry(request).get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_id}' not found")
    return RepositoryOut.model_validate(repo)


@router.post("", response_model=RepositoryOut)
def create_registry_entry(request: Request, payload: RepositoryIn):
    normalized_payload = normalize_repository_payload(_config(request), payload)
    repo = _registry(request).upsert_repository(normalized_payload)
    return RepositoryOut.model_validate(repo)


@router.delete("/datastores", response_model=DatastoreResetResponse)
def reset_datastores(request: Request, payload: DatastoreResetRequest):
    config = _config(request)
    if not config.ALLOW_DATA_RESET:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Data reset is disabled. Set ALLOW_DATA_RESET=1 to enable.",
        )
    if payload.confirm.lower() != "delete":
        raise HTTPException(status_code=400, detail="Confirmation token mismatch. Type 'delete' to proceed.")
    service = DatastoreResetService(config, _registry(request), _initializer(request))
    return service.reset()


@router.put("/{repo_id}", response_model=RepositoryOut)
def update_registry_entry(request: Request, repo_id: str, payload: RepositoryUpdate):
    try:
        repo = _registry(request).update_repository(repo_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return RepositoryOut.model_validate(repo)


@router.delete("/{repo_id}", status_code=204)
def delete_registry_entry(request: Request, repo_id: str):
    _registry(request).delete_repository(repo_id)
    return


@router.post("/preview")
def preview_registry_entry(request: Request, payload: RepositoryIn):
    """Dry-run normalization for UI curl preview; does not persist."""
    normalized_payload = normalize_repository_payload(_config(request), payload)
    return {"target": "/registry", "payload": normalized_payload}


@router.post("/webhook", response_model=Optional[RepositoryOut])
def registry_webhook(request: Request, event: RegistryWebhook):
    payload = event.model_dump(exclude={"action"})
    try:
        repo = _registry(request).handle_webhook(event.action, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if repo is None:
        return None
    return RepositoryOut.model_validate(repo)


@router.get("/{repo_id}/sandboxes", response_model=List[SandboxOut])
def list_sandboxes(request: Request, repo_id: str):
    repo = _registry(request).get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_id}' not found")
    sandboxes = _registry(request).list_sandboxes(repo_id)
    return [SandboxOut.model_validate(sandbox) for sandbox in sandboxes]


@router.post("/{repo_id}/sandboxes", response_model=SandboxOut)
def create_sandbox(request: Request, repo_id: str, payload: SandboxCreate):
    registry = _registry(request)
    repo = registry.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_id}' not found")
    if repo.archived:
        raise HTTPException(status_code=400, detail=f"Repository '{repo_id}' is archived")

    sandbox_manager = _sandboxes(request)
    try:
        path, parent_commit = sandbox_manager.ensure_worktree(repo_id, payload.user_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    sandbox = registry.create_sandbox(
        {
            "repo_id": repo_id,
            "user_id": payload.user_id,
            "created_by": payload.created_by or payload.user_id,
            "path": str(path),
            "status": payload.status or "ready",
            "auto_sync": payload.auto_sync,
            "parent_commit": parent_commit,
            "upstream_url": repo.url,
        }
    )
    sandbox_manager.record_creation(sandbox)
    return SandboxOut.model_validate(sandbox)


@router.patch("/{repo_id}/sandboxes/{sandbox_id}", response_model=SandboxOut)
def update_sandbox(request: Request, repo_id: str, sandbox_id: int, payload: SandboxUpdate):
    registry = _registry(request)
    repo = registry.get_repository(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository '{repo_id}' not found")
    try:
        sandbox = registry.update_sandbox(
            sandbox_id,
            payload.model_dump(exclude_unset=True),
            repo_id=repo_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return SandboxOut.model_validate(sandbox)
