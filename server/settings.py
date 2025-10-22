from pydantic import BaseModel
import os
class Settings(BaseModel):
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    tei_url: str = os.getenv("TEI_URL", "http://localhost:8081")
    collection_code: str = os.getenv("COLLECTION_CODE", "code_chunks")
    collection_funcs: str = os.getenv("COLLECTION_FUNCS", "functions")
    chunk_tokens: int = int(os.getenv("CHUNK_TOKENS", "512"))
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "64"))
    repo_root: str = os.getenv("REPO_ROOT", "/workspace")
    
settings = Settings()