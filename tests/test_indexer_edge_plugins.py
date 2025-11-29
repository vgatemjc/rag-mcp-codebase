from server.services.git_aware_code_indexer import Chunk, Indexer, Range
from server.services.edges import EdgeType, build_edge


def _chunk():
    return Chunk(
        logical_id="demo:src/Demo.kt#class:Demo",
        symbol="class:Demo",
        path="src/Demo.kt",
        language="kotlin",
        range=Range(1, 1, 0, 10),
        content="fun demo() {}",
        content_hash="hash",
        sig_hash="sig",
    )


class DummyPayloadPlugin:
    def build_payload(self, chunk, branch, commit_sha):
        return {"component_type": "dummy", "edges": [build_edge(EdgeType.NAV_DESTINATION, "home")]}


class DummyEdgePlugin:
    def build_edges(self, chunk):
        return [
            build_edge(EdgeType.NAV_DESTINATION, "home"),
            build_edge(EdgeType.NAV_ACTION, "detail"),
        ]


def test_payload_merges_edge_plugins():
    idx = Indexer.__new__(Indexer)
    idx.repo_name = "demo"
    idx.base_payload = {}
    idx.payload_plugins = [DummyPayloadPlugin()]
    idx.edge_plugins = [DummyEdgePlugin()]

    payload = Indexer._build_payload(idx, _chunk(), "main", "abc123")

    assert payload["component_type"] == "dummy"
    assert any(edge["type"] == EdgeType.NAV_DESTINATION for edge in payload["edges"])
    assert any(edge["type"] == EdgeType.NAV_ACTION for edge in payload["edges"])
    assert sum(1 for edge in payload["edges"] if edge["type"] == EdgeType.NAV_DESTINATION) == 1
