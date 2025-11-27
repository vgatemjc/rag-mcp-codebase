from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(prefix="/dev-ui", tags=["dev-ui"])

STATIC_DIR = Path(__file__).resolve().parent.parent / "static" / "dev_ui"
INDEX_FILE = STATIC_DIR / "index.html"


@router.get("", include_in_schema=False)
def serve_dev_ui():
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=500, detail="Dev UI assets are missing.")
    return FileResponse(INDEX_FILE, media_type="text/html", headers={"Cache-Control": "no-cache"})
