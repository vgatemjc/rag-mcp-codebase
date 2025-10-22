from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
import os

url = os.getenv("QDRANT_URL", "http://localhost:6333")
code = os.getenv("COLLECTION_CODE", "code_chunks")
func = os.getenv("COLLECTION_FUNCS", "functions")

cli = QdrantClient(url=url)

for name in (code, func):
    try:
        cli.delete_collection(name)
    except Exception:
        pass
print("Collections cleared. Re-index repository.")
