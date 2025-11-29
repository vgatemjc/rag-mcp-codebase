from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load repo-level .env so default_factory lookups see those values.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env", override=False)


@dataclass
class Config:
    """Shared configuration loaded from environment variables."""

    ENV: str = field(default_factory=lambda: os.getenv("APP_ENV", "dev"))
    QDRANT_URL: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://localhost:6333"))
    QDRANT_API_KEY: str = field(default_factory=lambda: os.getenv("QDRANT_API_KEY", ""))
    EMB_BASE_URL: str = field(default_factory=lambda: os.getenv("EMB_BASE_URL", "http://localhost:8080/v1"))
    EMB_MODEL: str = field(default_factory=lambda: os.getenv("EMB_MODEL", "nomic-ai/CodeRankEmbed"))
    OPENAI_API_KEY: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    REPOS_DIR: Path = field(default_factory=lambda: Path(os.getenv("REPOS_DIR", "/workspace/myrepo")))
    STATE_FILE: Path = field(default_factory=lambda: Path(os.getenv("STATE_FILE", "index_state.json")))
    REGISTRY_DB_PATH: Optional[Path] = field(default=None)
    REGISTRY_DB_DIR: Optional[Path] = field(default=None)
    HOST_REPO_PATH: Optional[Path] = field(default=None)
    QDRANT_STORAGE_PATH: Optional[Path] = field(default=None)
    DIM: Optional[int] = field(default_factory=lambda: int(os.getenv("DIM", "0")) or None)
    BRANCH: str = field(default_factory=lambda: os.getenv("GIT_BRANCH", "main"))
    SKIP_COLLECTION_INIT: bool = field(default_factory=lambda: False)
    EXPOSE_MCP_UI: bool = field(default_factory=lambda: True)
    MCP_MODULE: str = field(default_factory=lambda: os.getenv("MCP_MODULE", "server.git_rag_mcp"))
    STACK_TYPE: Optional[str] = field(default_factory=lambda: os.getenv("STACK_TYPE"))
    ALLOW_DATA_RESET: bool = field(default=False)

    def __post_init__(self) -> None:
        self.SKIP_COLLECTION_INIT = os.getenv("SKIP_COLLECTION_INIT", "0").lower() in {"1", "true", "yes"}
        self.EXPOSE_MCP_UI = os.getenv("EXPOSE_MCP_UI", "1").lower() in {"1", "true", "yes"}
        model_slug = re.sub(r"[^a-z0-9]+", "", self.EMB_MODEL.lower())
        self.COLLECTION = f"git_rag-{self.ENV}-{model_slug}"
        self.REGISTRY_DB_DIR = self._resolve_optional_path("REGISTRY_DB_DIR") or (self.REPOS_DIR / "registry_db")
        self.REGISTRY_DB_PATH = self._resolve_registry_db_path()
        self.HOST_REPO_PATH = self._resolve_optional_path("HOST_REPO_PATH")
        self.QDRANT_STORAGE_PATH = self._resolve_qdrant_storage_path()
        self.ALLOW_DATA_RESET = os.getenv("ALLOW_DATA_RESET", "0").lower() in {"1", "true", "yes"}

    def _resolve_optional_path(self, env_key: str) -> Optional[Path]:
        raw = os.getenv(env_key)
        if not raw:
            return None
        return Path(raw).expanduser()

    def _resolve_registry_db_path(self) -> Path:
        explicit = self._resolve_optional_path("REGISTRY_DB_PATH")
        if explicit:
            return explicit
        base_dir = Path(self.REGISTRY_DB_DIR or (self.REPOS_DIR / "registry_db"))
        return (base_dir / "registry.db").expanduser()

    def _resolve_qdrant_storage_path(self) -> Optional[Path]:
        explicit = self._resolve_optional_path("QDRANT_STORAGE_PATH")
        if explicit:
            return explicit
        if self.HOST_REPO_PATH:
            return (self.HOST_REPO_PATH / "rag-db").expanduser()
        return None
