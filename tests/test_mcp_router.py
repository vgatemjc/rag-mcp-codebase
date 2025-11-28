from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from server.app import create_app


class FakeMCPService:
    def list_tools(self):
        return [
            {
                "name": "demo",
                "description": "Demo tool",
                "parameters": [{"name": "text", "required": False, "default": "hi", "annotation": "str"}],
            }
        ]

    async def invoke_tool(self, name, args):
        return {
            "tool": name,
            "started_at": datetime.utcnow(),
            "finished_at": datetime.utcnow() + timedelta(milliseconds=1),
            "duration_ms": 1,
            "output_text": f"ran {name}",
            "raw_result": {"echo": args},
            "parsed_json": {"echo": args},
            "content_type": "json",
            "stdout": f"ran {name}",
            "stderr": None,
            "success": True,
        }


def test_mcp_router_list_and_invoke(monkeypatch, tmp_path):
    monkeypatch.setenv("EXPOSE_MCP_UI", "1")
    monkeypatch.setenv("SKIP_COLLECTION_INIT", "1")
    monkeypatch.setenv("REGISTRY_DB_DIR", str(tmp_path))
    app = create_app()
    app.state.mcp_service = FakeMCPService()
    client = TestClient(app)

    resp = client.get("/mcp/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert tools[0]["name"] == "demo"

    resp = client.post("/mcp/tools/demo", json={"args": {"text": "hello"}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tool"] == "demo"
    assert body["output_text"].startswith("ran")
    assert body["raw_result"]["echo"]["text"] == "hello"
    assert body["parsed_json"]["echo"]["text"] == "hello"
    assert body["content_type"] == "json"


def test_mcp_router_rejects_bad_args(monkeypatch, tmp_path):
    class RaisingMCPService(FakeMCPService):
        async def invoke_tool(self, name, args):
            raise ValueError("Invalid arguments for tool 'demo': unexpected keyword")

    monkeypatch.setenv("EXPOSE_MCP_UI", "1")
    monkeypatch.setenv("SKIP_COLLECTION_INIT", "1")
    monkeypatch.setenv("REGISTRY_DB_DIR", str(tmp_path))
    app = create_app()
    app.state.mcp_service = RaisingMCPService()
    client = TestClient(app)

    resp = client.post("/mcp/tools/demo", json={"args": {"text": "hello"}})
    assert resp.status_code == 400
    assert "Invalid arguments" in resp.json()["detail"]
