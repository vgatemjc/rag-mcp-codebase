from fastapi import FastAPI
from models import IndexRequest, SearchRequest, SearchResponse, Snippet
from settings import settings
from indexer import Indexer
from vecdb import VecDB
import httpx
import numpy as np
import sys, logging

# 강제로 stdout 플러시
print(">>> TEST PRINT <<<", flush=True)

# 로거 재구성
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger(__name__)
logger.info(">>> TEST LOGGER <<<")
logger = logging.getLogger(__name__)

app = FastAPI(title="RAG Server")
indexer = Indexer()
vecdb = indexer.db

async def embed(texts):
    async with httpx.AsyncClient(timeout=30) as cli:
        r = await cli.post(f"{settings.tei_url}/embed", json={"inputs": texts})
        r.raise_for_status()
        return np.array(r.json(), dtype=np.float32)

@app.post("/index")
def index(req: IndexRequest):
    repo = req.repo_path.rstrip("/")
    name = repo.split("/")[-1]
    logger.info(f"repo {repo}  : name {name}")
    res = indexer.index_repo(repo, name)
    return {"repo": name, **res}

@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    qv = (await embed([req.query]))[0]
    hits = vecdb.search(settings.collection_code, qv, req.k, {"repo": req.repo} if req.repo else None)
    out = []
    for h in hits:
        p = h.payload
        out.append(Snippet(
            file=p["file"], start=p["start"], end=p["end"], lang=p["lang"],
            text="",
            score=float(h.score),
        ))
    return SearchResponse(hits=out)
