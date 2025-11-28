from server.services.git_aware_code_indexer import Chunk, Range, Retriever, Indexer, sha256
from qdrant_client.http.models import MatchAny


class DummyPayloadPlugin:
    def build_payload(self, chunk: Chunk, branch: str, commit_sha: str):
        return {"component_type": "activity"}


def test_build_payload_merges_base_and_plugins():
    content = "class MainActivity {}"
    chunk = Chunk(
        logical_id="demo:Main.kt#class:MainActivity",
        symbol="class:MainActivity",
        path="Main.kt",
        language="kotlin",
        range=Range(1, 1, 0, len(content.encode())),
        content=content,
        content_hash=sha256(content.encode()),
        sig_hash=sha256(b"class:MainActivity"),
    )

    idx = Indexer.__new__(Indexer)
    idx.repo_name = "demo"
    idx.base_payload = {"stack_type": "android_app", "base_only": "yes"}
    idx.payload_plugins = [DummyPayloadPlugin()]

    payload = Indexer._build_payload(idx, chunk, "main", "abc123")

    assert payload["stack_type"] == "android_app"
    assert payload["component_type"] == "activity"
    assert payload["base_only"] == "yes"
    assert payload["is_latest"] is True
    assert payload["point_id"]


class DummyStore:
    def __init__(self):
        self.last_filter = None

    def search(self, query_vector, k=5, filt=None):
        self.last_filter = filt
        return []


class DummyEmbeddings:
    def embed(self, texts):
        return [[0.0] * 1 for _ in texts]


def test_retriever_applies_stack_filters():
    store = DummyStore()
    emb = DummyEmbeddings()
    retriever = Retriever(store, emb, None)

    retriever.search(
        "find activity",
        repo="demo",
        stack_type="android_app",
        component_type="activity",
        screen_name="home",
        tags=["layout", "navgraph", "layout"],
    )

    filt = store.last_filter
    assert filt is not None
    keys = {cond.key for cond in filt.must}
    assert "stack_type" in keys
    assert "component_type" in keys
    assert "screen_name" in keys
    assert any(cond.key == "tags" and isinstance(cond.match, MatchAny) for cond in filt.must)
