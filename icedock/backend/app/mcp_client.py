"""Minimal MCP client over Streamable HTTP (JSON or SSE responses)."""
import json

import httpx

PROTOCOL = "2025-06-18"


class MCPError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def parse_body(raw: str, content_type: str = ""):
    raw = raw.strip()
    if not raw:
        return {}
    if "json" in content_type or raw.startswith("{"):
        return json.loads(raw)
    events = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            d = line[5:].strip()
            if d and d != "[DONE]":
                try:
                    events.append(json.loads(d))
                except ValueError:
                    pass
    responses = [e for e in events if "result" in e or "error" in e]
    return (responses or events or [{}])[-1]


class MCPClient:
    def __init__(self, url, token=None, headers=None, timeout=300):
        self.url = url
        self.headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                        **(headers or {})}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.timeout = timeout
        self._id = 0
        self.session_id = None

    async def rpc(self, method, params=None, notify=False):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._id += 1
            body["id"] = self._id
        h = dict(self.headers)
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(self.url, json=body, headers=h)
        if r.headers.get("mcp-session-id"):
            self.session_id = r.headers["mcp-session-id"]
        if r.status_code >= 400:
            raise MCPError(f"HTTP {r.status_code}: {r.text[:400]}", r.status_code)
        if notify:
            return None
        msg = parse_body(r.text, r.headers.get("content-type", ""))
        if "error" in msg:
            raise MCPError(f"{msg['error'].get('code')}: {msg['error'].get('message')}")
        return msg.get("result", {})

    async def initialize(self):
        res = await self.rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                            "clientInfo": {"name": "icedock", "version": "0.1"}})
        try:
            await self.rpc("notifications/initialized", notify=True)
        except MCPError:
            pass
        return res

    async def list_tools(self):
        await self.initialize()
        return (await self.rpc("tools/list")).get("tools", [])

    async def call_tool(self, name, arguments):
        await self.initialize()
        return await self.rpc("tools/call", {"name": name, "arguments": arguments or {}})


def result_text(result: dict) -> str:
    parts = []
    for c in result.get("content", []) or []:
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
        else:
            parts.append(json.dumps(c)[:2000])
    if not parts and "structuredContent" in result:
        parts.append(json.dumps(result["structuredContent"]))
    return "\n".join(parts)
