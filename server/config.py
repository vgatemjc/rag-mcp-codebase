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
    EMB_MODEL: str = field(default_factory=lambda: os.getenv("EMB_MODEL", "BAAI/bge-small-en-v1.5"))
    OPENAI_API_KEY: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    REPOS_DIR: Path = field(default_factory=lambda: Path(os.getenv("REPOS_DIR", "/workspace/myrepo")))
    STATE_FILE: Path = field(default_factory=lambda: Path(os.getenv("STATE_FILE", "index_state.json")))
    DIM: Optional[int] = field(default_factory=lambda: int(os.getenv("DIM", "0")) or None)
    BRANCH: str = field(default_factory=lambda: os.getenv("GIT_BRANCH", "main"))
    SKIP_COLLECTION_INIT: bool = field(default_factory=lambda: False)

    def __post_init__(self) -> None:
        self.SKIP_COLLECTION_INIT = os.getenv("SKIP_COLLECTION_INIT", "0").lower() in {"1", "true", "yes"}
        model_slug = re.sub(r"[^a-z0-9]+", "", self.EMB_MODEL.lower())
        self.COLLECTION = f"git_rag-{self.ENV}-{model_slug}"
