"""Act as Langdock: call the Snowflake MCP server with the signed-in user's Entra token."""
import json, sys, urllib.request

import os

# MCP_URL e.g. https://<org>-<account>.snowflakecomputing.com/api/v2/databases/MCP_DEMO/schemas/MCP/mcp-servers/RESEARCH
URL = os.environ["MCP_URL"]
TOKEN = os.environ["MCP_TOKEN"]          # the user's Entra access token
ROLE = os.environ.get("SF_ROLE")          # optional: sends X-Snowflake-Role


def rpc(i, method, params=None):
    body = {"jsonrpc": "2.0", "id": i, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **({"X-Snowflake-Role": ROLE} if ROLE else {}),
    })
    try:
        raw = urllib.request.urlopen(req, timeout=300).read().decode()
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:500]}
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    events = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")]
    events = [json.loads(e) for e in events if e and e != "[DONE]"]
    return events[-1] if events else raw


def text_of(r):
    try:
        return "\n".join(c.get("text", "") for c in r["result"]["content"])
    except Exception:
        return json.dumps(r)[:1500]


print("== initialize ==", json.dumps(rpc(1, "initialize", {
    "protocolVersion": "2025-11-25", "capabilities": {},
    "clientInfo": {"name": "langdock-sim", "version": "0"}}))[:300])
print("== tools/list ==", [t["name"] for t in rpc(2, "tools/list").get("result", {}).get("tools", [])])

step = sys.argv[1] if len(sys.argv) > 1 else "all"
if step in ("all", "search"):
    r = rpc(3, "tools/call", {"name": "research_search",
                              "arguments": {"query": "analyst note fund outlook", "columns": ["doc", "fund_id"], "limit": 5}})
    print("== direct Cortex Search ==\n", json.dumps(r)[:1500])
if step in ("all", "agent"):
    r = rpc(4, "tools/call", {"name": "research_agent", "arguments": {
        "text": "Use the funds tool: list all fund names with their AUM. Also, what is the current user and role? "}})
    print("== agent (Analyst) ==\n", text_of(r)[-1500:])
