from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request

from server.config import Config
from server.models.search import SearchRequest
from server.services.git_aware_code_indexer import Retriever
from server.services.repository_registry import RepositoryRegistry
from server.services.state_manager import get_repo_path

router = APIRouter(tags=["search"])


def _config(request: Request) -> Config:
    return request.app.state.config


def _registry(request: Request) -> RepositoryRegistry:
    return request.app.state.registry


@router.post("/search", response_model=List[Dict[str, Any]])
def search(request: Request, req: SearchRequest):
    config = _config(request)
    initializer = request.app.state.initializer
    repo_path = None
    stack_type = req.stack_type or getattr(config, "STACK_TYPE", None)

    try:
        if req.repo_id:
            defaults = {
                "name": req.repo_id,
                "collection_name": config.COLLECTION,
                "embedding_model": config.EMB_MODEL,
                "stack_type": getattr(config, "STACK_TYPE", None),
            }
            repo_entry = _registry(request).ensure_repository(req.repo_id, defaults)
            if repo_entry.archived:
                raise HTTPException(status_code=400, detail=f"Repository '{req.repo_id}' is archived")
            stack_type = req.stack_type or repo_entry.stack_type or getattr(config, "STACK_TYPE", None)
            emb_client, store_client = initializer.resolve_clients(
                repo_entry.collection_name,
                repo_entry.embedding_model,
            )
            repo_path = get_repo_path(config.REPOS_DIR, req.repo_id)
        else:
            emb_client = initializer.get_embeddings_client(config.EMB_MODEL)
            store_client = initializer.get_vector_store(config.COLLECTION, config.EMB_MODEL)

        retriever = Retriever(store_client, emb_client, str(repo_path) if repo_path else None)
        results = retriever.search(
            req.query,
            req.k,
            config.BRANCH,
            repo=req.repo_id,
            stack_type=stack_type,
            component_type=req.component_type,
            screen_name=req.screen_name,
            tags=req.tags,
        )
        return results
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
