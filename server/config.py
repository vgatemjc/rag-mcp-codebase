from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    """Shared configuration loaded from environment variables."""

    ENV: str = os.getenv("APP_ENV", "dev")
    QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    QDRANT_API_KEY: str = os.getenv("QDRANT_API_KEY", "")
    EMB_BASE_URL: str = os.getenv("EMB_BASE_URL", "http://localhost:8080/v1")
    EMB_MODEL: str = os.getenv("EMB_MODEL", "text-embedding-3-large")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    REPOS_DIR: Path = Path(os.getenv("REPOS_DIR", "/workspace/myrepo"))
    STATE_FILE: Path = Path(os.getenv("STATE_FILE", "index_state.json"))
    DIM: Optional[int] = int(os.getenv("DIM", "0")) or None
    BRANCH: str = os.getenv("GIT_BRANCH", "main")
    SKIP_COLLECTION_INIT: bool = field(default=False)

    def __post_init__(self) -> None:
        self.SKIP_COLLECTION_INIT = os.getenv("SKIP_COLLECTION_INIT", "0").lower() in {"1", "true", "yes"}
        model_slug = re.sub(r"[^a-z0-9]+", "", self.EMB_MODEL.lower())
        self.COLLECTION = f"git_rag-{self.ENV}-{model_slug}"
