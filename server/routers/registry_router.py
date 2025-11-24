from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request

from server.models.repository import (
    RegistryWebhook,
    RepositoryIn,
    RepositoryOut,
    RepositoryUpdate,
)
from server.services.repository_registry import RepositoryRegistry

router = APIRouter(prefix="/registry", tags=["registry"])


def _registry(request: Request) -> RepositoryRegistry:
    return request.app.state.registry


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
    try:
        repo = _registry(request).create_repository(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RepositoryOut.model_validate(repo)


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
