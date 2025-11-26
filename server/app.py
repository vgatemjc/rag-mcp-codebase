from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from server.config import Config
from server.routers.index_router import router as index_router
from server.routers.registry_router import router as registry_router
from server.routers.registry_ui import router as registry_ui_router
from server.routers.search_router import router as search_router
from server.routers.status_router import router as status_router
from server.services.initializers import Initializer
from server.services.repository_registry import RepositoryRegistry
from server.services.sandbox_manager import SandboxManager


logger = logging.getLogger(__name__)


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or Config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if cfg.SKIP_COLLECTION_INIT:
            logger.info("Skipping default collection initialization (SKIP_COLLECTION_INIT set).")
            yield
            return
        app.state.initializer.ensure_default_collection()
        yield

    app = FastAPI(title="Git RAG API", lifespan=lifespan)

    app.state.config = cfg
    app.state.registry = RepositoryRegistry()
    app.state.initializer = Initializer(cfg)
    app.state.sandbox_manager = SandboxManager(cfg.REPOS_DIR, cfg.BRANCH)

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount(
        "/static",
        StaticFiles(directory=static_dir),
        name="static",
    )  # Registry UI bundle and other static assets.

    app.include_router(registry_ui_router)
    app.include_router(registry_router)
    app.include_router(index_router)
    app.include_router(status_router)
    app.include_router(search_router)

    return app
