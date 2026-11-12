import json
import time

import pytest
from fastapi.testclient import TestClient

from app import auth, db, llm
from app.mcp_client import parse_body, result_text


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db.reset_for_tests(tmp_path / "t.db")
    from app import main
    main.seed()
    c = TestClient(main.app)
    u = auth.upsert_user({"oid": "o1", "preferred_username": "a@x.com", "name": "Alice"})
    db.save_token(u["id"], auth.LOGIN_KEY, {"access_token": "tok", "refresh_token": "r", "expires_in": 3600})
    c.cookies.set(auth.SESSION_COOKIE, auth.sign({"uid": u["id"]}))
    c.user = u
    return c


def test_parse_sse_and_json():
    assert parse_body('{"jsonrpc":"2.0","id":1,"result":{"a":1}}')["result"]["a"] == 1
    sse = 'event: message\ndata: {"jsonrpc":"2.0","method":"note"}\n\ndata: {"jsonrpc":"2.0","id":2,"result":{"ok":true}}\n\n'
    assert parse_body(sse, "text/event-stream")["result"]["ok"] is True
    assert result_text({"content": [{"type": "text", "text": "hi"}]}) == "hi"


def test_unauthenticated(tmp_path):
    db.reset_for_tests(tmp_path / "u.db")
    from app import main
    assert TestClient(main.app).get("/api/me").status_code == 401


def test_first_user_admin_and_me(client):
    r = client.get("/api/me").json()
    assert r["email"] == "a@x.com" and r["is_admin"] is True
    second = auth.upsert_user({"oid": "o2", "preferred_username": "b@x.com"})
    assert second["is_admin"] == 0


def test_tokens_encrypted_at_rest(client):
    raw = db.one("SELECT data FROM tokens WHERE user_id=?", (client.user["id"],))["data"]
    assert "tok" not in raw and db.load_token(client.user["id"], auth.LOGIN_KEY)["access_token"] == "tok"


def test_integration_crud_hides_secret(client):
    r = client.post("/api/integrations", json={"name": "X", "url": "https://mcp", "client_secret": "s3cret",
                                                "auth_type": "oauth_manual", "client_id": "c"}).json()
    assert r["has_secret"] and "client_secret" not in r and r["connected"] is False
    assert "s3cret" not in json.dumps(client.get("/api/integrations").json())
    # Update with secret=None keeps the stored secret
    client.put(f"/api/integrations/{r['id']}", json={"name": "Y", "url": "https://mcp", "client_id": "c"})
    assert db.dec(db.one("SELECT client_secret FROM integrations WHERE id=?", (r["id"],))["client_secret"]) == "s3cret"


def test_connect_redirect_has_pkce(client):
    iid = client.post("/api/integrations", json={"name": "X", "url": "https://mcp", "auth_url": "https://idp/auth",
                                                  "token_url": "https://idp/token", "client_id": "c", "scope": "s"}).json()["id"]
    r = client.get(f"/api/integrations/{iid}/connect", follow_redirects=False)
    assert r.status_code == 307 and "code_challenge_method=S256" in r.headers["location"]
    assert "resource=" not in r.headers["location"]


def test_preselect_requires_own_connection(client):
    iid = client.post("/api/integrations", json={"name": "X", "url": "https://mcp", "client_id": "c"}).json()["id"]
    body = {"name": "A", "actions": {iid: ["t"]}, "preselect": [iid]}
    assert client.post("/api/agents", json=body).status_code == 400
    db.save_token(client.user["id"], auth.integration_key(iid), {"access_token": "x", "expires_in": 3600})
    a = client.post("/api/agents", json=body).json()
    assert a["preselect"] == [iid]


def test_agent_visibility(client):
    a = client.post("/api/agents", json={"name": "Private"}).json()
    other = auth.upsert_user({"oid": "o3", "preferred_username": "c@x.com"})
    client.cookies.set(auth.SESSION_COOKIE, auth.sign({"uid": other["id"]}))
    assert client.get(f"/api/agents/{a['id']}").status_code == 404


def test_tool_names_and_filter():
    integ = {"id": "i1", "name": "Snowflake Research", "tools": json.dumps([{"name": "research_agent"}, {"name": "x"}])}
    fns, index = llm.build_tools([integ], {"i1": ["research_agent"]})
    assert [f["function"]["name"] for f in fns] == ["snowflake_research__research_agent"]
    assert index["snowflake_research__research_agent"][1] == "research_agent"


def test_chat_stream_with_tool(client, monkeypatch):
    iid = client.post("/api/integrations", json={"name": "Snow", "url": "https://mcp", "client_id": "c"}).json()["id"]
    db.run("UPDATE integrations SET tools=? WHERE id=?", (json.dumps([{"name": "who", "inputSchema": {"type": "object"}}]), iid))
    db.save_token(client.user["id"], auth.integration_key(iid), {"access_token": "u", "expires_in": 3600})
    rounds = iter([
        [{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "snow__who", "arguments": "{}"}}]}}]}],
        [{"choices": [{"delta": {"content": "You are "}}]}, {"choices": [{"delta": {"content": "Alice"}}]}],
    ])

    async def fake_stream(token, model, messages, tools):
        assert token == "tok"
        for ch in next(rounds):
            yield ch

    async def fake_call(self, name, args):
        assert self.headers["Authorization"] == "Bearer u"
        return {"content": [{"type": "text", "text": "ALICE / LDC_MCP_USER"}]}

    monkeypatch.setattr(llm, "stream_completion", fake_stream)
    monkeypatch.setattr("app.mcp_client.MCPClient.call_tool", fake_call)
    cid = client.post("/api/chats", json={}).json()["id"]
    r = client.post(f"/api/chats/{cid}/messages", json={"content": "who am i", "integrations": [iid]})
    events = [json.loads(l[5:]) for l in r.text.splitlines() if l.startswith("data:")]
    types = [e["type"] for e in events]
    assert "tool_start" in types and "tool_end" in types and types[-1] == "done"
    chat = client.get(f"/api/chats/{cid}").json()
    assert chat["title"] == "who am i"
    assert chat["messages"][-1]["content"] == "You are Alice"
    assert chat["messages"][-1]["tool_calls"][0]["acting_as"] == "a@x.com"


def test_connect_required_event(client, monkeypatch):
    iid = client.post("/api/integrations", json={"name": "Snow", "url": "https://mcp", "client_id": "c"}).json()["id"]
    db.run("UPDATE integrations SET tools=? WHERE id=?", (json.dumps([{"name": "who"}]), iid))

    async def fake_stream(token, model, messages, tools):
        yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "snow__who", "arguments": "{}"}}]}}]}

    monkeypatch.setattr(llm, "stream_completion", fake_stream)
    cid = client.post("/api/chats", json={}).json()["id"]
    r = client.post(f"/api/chats/{cid}/messages", json={"content": "q", "integrations": [iid]})
    assert any(json.loads(l[5:])["type"] == "connect_required" for l in r.text.splitlines() if l.startswith("data:"))


def test_expired_token_refresh(client, monkeypatch):
    db.save_token(client.user["id"], auth.LOGIN_KEY, {"access_token": "old", "refresh_token": "r1", "expires_in": 0})

    async def fake_req(url, data):
        assert data["grant_type"] == "refresh_token" and data["refresh_token"] == "r1"
        return {"access_token": "new", "expires_in": 3600}

    monkeypatch.setattr(auth, "token_request", fake_req)
    import asyncio
    assert asyncio.run(auth.login_token(client.user["id"])) == "new"
    assert db.load_token(client.user["id"], auth.LOGIN_KEY)["refresh_token"] == "r1"
    assert db.load_token(client.user["id"], auth.LOGIN_KEY)["_expires_at"] > time.time()
