from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from server.config import Config
from server.services.initializers import Initializer
from server.services.repository_registry import RepositoryRegistry

router = APIRouter(prefix="/registry/ui", tags=["registry-ui"])

STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "registry_ui"
INDEX_FILE = STATIC_DIR / "index.html"
EMBED_OPTIONS_FILE = STATIC_DIR / "embed-options.json"


def _config(request: Request) -> Config:
    return request.app.state.config


def _registry(request: Request) -> RepositoryRegistry:
    return request.app.state.registry


def _initializer(request: Request) -> Initializer:
    return request.app.state.initializer


def _load_embedding_options() -> List[str]:
    if not EMBED_OPTIONS_FILE.exists():
        return []
    try:
        with EMBED_OPTIONS_FILE.open(encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return []
    if isinstance(payload, list):
        return [str(item) for item in payload if item]
    if isinstance(payload, dict):
        models = payload.get("models")
        if isinstance(models, list):
            return [str(item) for item in models if item]
    return []


def _fetch_collections(initializer: Initializer) -> List[str]:
    try:
        response = initializer._qdrant().get_collections()  # type: ignore[attr-defined]
        return [collection.name for collection in response.collections]
    except Exception:
        return []


@router.get("", include_in_schema=False)
def serve_registry_ui():
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=500, detail="Registry UI assets are missing.")
    return FileResponse(INDEX_FILE, media_type="text/html", headers={"Cache-Control": "no-cache"})


@router.get("/meta")
def get_registry_ui_meta(request: Request) -> Dict[str, Any]:
    cfg = _config(request)
    registry = _registry(request)
    defaults = {
        "qdrant_url": cfg.QDRANT_URL,
        "embedding_base_url": cfg.EMB_BASE_URL,
        "embedding_model": cfg.EMB_MODEL,
        "repos_dir": str(cfg.REPOS_DIR),
        "collection": cfg.COLLECTION,
        "stack_type": cfg.STACK_TYPE,
    }
    entries = [
        {
            "repo_id": repo.repo_id,
            "name": repo.name,
            "collection_name": repo.collection_name,
            "embedding_model": repo.embedding_model,
            "archived": repo.archived,
            "stack_type": repo.stack_type,
        }
        for repo in registry.list_repositories(include_archived=True)
    ]
    return {
        "config": defaults,
        "registry": entries,
        "embedding_options": _load_embedding_options(),
        "qdrant_collections": _fetch_collections(_initializer(request)),
    }
