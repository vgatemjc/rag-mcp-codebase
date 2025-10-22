from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from typing import List, Dict
import numpy as np
import logging

logger = logging.getLogger(__name__)

class VecDB:
    def __init__(self, url: str):
        self.cli = QdrantClient(url=url)

    def ensure_collection(self, name: str, dim: int):
        if name not in [c.name for c in self.cli.get_collections().collections]:
            self.cli.recreate_collection(
                collection_name=name,
                vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE)
            )


    def upsert(self, name: str, ids: List[str], vectors: np.ndarray, payloads: List[Dict]):
       # --- 수정: vectors가 None인지 확인하여 AttributeError 방지 ---
        if vectors is None:
            logger.error(f"Cannot upsert to {name}: Vector input is None.")
            return
        
        # 데이터가 비어있는지 확인
        if vectors.size == 0 or len(ids) == 0:
            logger.warning(f"Skipping upsert for collection {name}: No vectors or IDs provided.")
            return

        # Pydantic 호환성을 위해 NumPy 배열을 Python 리스트로 변환
        vectors_list = vectors.tolist()
        
        self.cli.upsert(collection_name=name, 
            points=qm.Batch(
                ids=ids, 
                vectors=vectors_list, # 수정된 리스트 사용
                payloads=payloads
            )
        )

    def search(self, name: str, vector: np.ndarray, k: int = 10, filters: Dict = None):
        f = None
        if filters:
            f = qm.Filter(must=[qm.FieldCondition(key=key, match=qm.MatchValue(value=value)) for key, value in filters.items()])
        
        res = self.cli.search(collection_name=name, query_vector=vector.tolist(), limit=k, query_filter=f)
        return res
    