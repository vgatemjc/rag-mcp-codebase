from __future__ import annotations

import logging
import threading
from typing import Dict, Set, Tuple

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from server.config import Config
from .git_aware_code_indexer import Embeddings, VectorStore

logger = logging.getLogger(__name__)


class Initializer:
    """Manages external client initialization and caching."""

    def __init__(self, config: Config):
        self.config = config
        self._embedding_cache: Dict[str, Embeddings] = {}
        self._vector_store_cache: Dict[str, VectorStore] = {}
        self._collection_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._collection_ready: Set[str] = set()
        self._qdrant_admin: QdrantClient | None = None

    def _qdrant(self) -> QdrantClient:
        if self._qdrant_admin is None:
            self._qdrant_admin = QdrantClient(
                url=self.config.QDRANT_URL,
                api_key=self.config.QDRANT_API_KEY,
            )
        return self._qdrant_admin

    def get_embeddings_client(self, model_name: str) -> Embeddings:
        with self._cache_lock:
            client = self._embedding_cache.get(model_name)
            if client is None:
                client = Embeddings(
                    base_url=self.config.EMB_BASE_URL,
                    model=model_name,
                    api_key=self.config.OPENAI_API_KEY,
                )
                self._embedding_cache[model_name] = client
            return client

    def ensure_collection(self, collection_name: str, embedding_model: str) -> None:
        with self._collection_lock:
            if collection_name in self._collection_ready:
                return

            admin = self._qdrant()
            try:
                admin.get_collection(collection_name=collection_name)
                self._collection_ready.add(collection_name)
                return
            except Exception:
                pass

            if not self.config.DIM:
                logger.info("DIM not set; computing dynamically from sample embedding.")
                sample_vector = self.get_embeddings_client(embedding_model).embed(["dimension probe"])[0]
                dynamic_dim = len(sample_vector)
            else:
                dynamic_dim = self.config.DIM

            admin.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=dynamic_dim, distance=Distance.COSINE),
            )
            self._collection_ready.add(collection_name)
            logger.info("Created collection '%s' with dim=%s", collection_name, dynamic_dim)

    def get_vector_store(self, collection_name: str, embedding_model: str) -> VectorStore:
        self.ensure_collection(collection_name, embedding_model)
        with self._cache_lock:
            store = self._vector_store_cache.get(collection_name)
            if store is None:
                store = VectorStore(
                    collection=collection_name,
                    url=self.config.QDRANT_URL,
                    api_key=self.config.QDRANT_API_KEY,
                    dim=self.config.DIM,
                )
                self._vector_store_cache[collection_name] = store
            return store

    def resolve_clients(self, collection_name: str, embedding_model: str) -> Tuple[Embeddings, VectorStore]:
        emb_client = self.get_embeddings_client(embedding_model)
        store_client = self.get_vector_store(collection_name, embedding_model)
        return emb_client, store_client

    def ensure_default_collection(self) -> None:
        self.ensure_collection(self.config.COLLECTION, self.config.EMB_MODEL)
