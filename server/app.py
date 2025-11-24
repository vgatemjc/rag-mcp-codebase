from __future__ import annotations

import logging

from fastapi import FastAPI

from server.config import Config
from server.routers.index_router import router as index_router
from server.routers.registry_router import router as registry_router
from server.routers.search_router import router as search_router
from server.routers.status_router import router as status_router
from server.services.initializers import Initializer
from server.services.repository_registry import RepositoryRegistry


logger = logging.getLogger(__name__)


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or Config()
    app = FastAPI(title="Git RAG API")

    app.state.config = cfg
    app.state.registry = RepositoryRegistry()
    app.state.initializer = Initializer(cfg)

    @app.on_event("startup")
    async def startup_event():
        if app.state.config.SKIP_COLLECTION_INIT:
            logger.info("Skipping default collection initialization (SKIP_COLLECTION_INIT set).")
            return
        app.state.initializer.ensure_default_collection()

    app.include_router(registry_router)
    app.include_router(index_router)
    app.include_router(status_router)
    app.include_router(search_router)

    return app
