import asyncio
import importlib
import json
from typing import Any, Dict, List, Optional

import pytest


class _FakeResponse:
    def __init__(self, payload: Any = None, lines: Optional[List[str]] = None, status_code: int = 200):
        self._payload = payload
        self._lines = lines or []
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"status {self.status_code}")

    def json(self):
        return self._payload

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeAsyncClient:
    """
    Mimics a subset of httpx.AsyncClient used in git_rag_mcp tools.
    """

    def __init__(self, *args, **kwargs):
        self._registry: Dict[str, _FakeResponse] = kwargs.pop("registry", {})
        self._post_streams: Dict[str, _FakeResponse] = kwargs.pop("post_streams", {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, *_, **__):
        resp = self._registry.get(url)
        if resp is None:
            resp = _FakeResponse(status_code=404)
        return resp

    async def post(self, url: str, *_, **__):
        # Streaming index responses
        resp = self._post_streams.get(url)
        if resp is None:
            resp = _FakeResponse(status_code=404)
        return resp


def _setup_module(monkeypatch, responses: Dict[str, _FakeResponse], streams: Dict[str, _FakeResponse]):
    """
    Reload git_rag_mcp with a patched httpx.AsyncClient so the tools use our fakes.
    """
    monkeypatch.setenv("RAG_URL", "http://rag.test")
    import server.git_rag_mcp as mcp_mod

    # Patch AsyncClient to inject our fake responses
    monkeypatch.setattr(
        mcp_mod.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(registry=responses, post_streams=streams),
    )
    importlib.reload(mcp_mod)
    # Re-apply patch after reload because reload restores the original symbol
    monkeypatch.setattr(
        mcp_mod.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _FakeAsyncClient(registry=responses, post_streams=streams),
    )
    return mcp_mod


def test_registry_status_happy(monkeypatch):
    registry_payload = {"repo_id": "demo", "collection_name": "col", "embedding_model": "emb"}
    status_payload = {"repo_id": "demo", "last_index_status": "completed"}
    responses = {
        "http://rag.test/registry/demo": _FakeResponse(payload=registry_payload),
        "http://rag.test/repos/demo/index/status": _FakeResponse(payload=status_payload),
    }
    streams: Dict[str, _FakeResponse] = {}
    mcp_mod = _setup_module(monkeypatch, responses, streams)

    out = asyncio.get_event_loop().run_until_complete(mcp_mod.registry_status.fn("demo"))
    data = json.loads(out.text)
    assert data["registry"]["collection_name"] == "col"
    assert data["index_status"]["last_index_status"] == "completed"


def test_index_full_streaming(monkeypatch):
    lines = [
        json.dumps({"status": "started", "total_files": 2, "processed_files": 0}),
        json.dumps({"status": "processing", "file": "a.py", "processed_files": 1, "total_files": 2}),
        json.dumps({"status": "completed", "processed_files": 2, "total_files": 2}),
    ]
    responses: Dict[str, _FakeResponse] = {}
    streams = {"http://rag.test/repos/demo/index/full": _FakeResponse(lines=lines)}
    mcp_mod = _setup_module(monkeypatch, responses, streams)

    out = asyncio.get_event_loop().run_until_complete(mcp_mod.index_full.fn("demo"))
    assert "started" in out.text
    assert "[processing] 1/2" in out.text
    assert "completed" in out.text
