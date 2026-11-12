"""Chat orchestration: Cortex chat completions (OpenAI-compatible) as the signed-in user, MCP tools per user."""
import json
import re

import httpx

from . import auth, config, db
from .mcp_client import MCPClient, MCPError, result_text

MAX_TOOL_ROUNDS = 6
MAX_TOOL_CHARS = 20000


class ConnectRequired(Exception):
    def __init__(self, integ):
        super().__init__(integ["name"])
        self.integ = integ


def tool_fn_name(integ, tool_name):
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", integ["name"]).strip("_").lower()[:20] or "mcp"
    return f"{slug}__{tool_name}"[:64]


def build_tools(integrations, allowed=None):
    """integrations: list of rows. allowed: {integration_id: [tool names]} or None for all tools."""
    fns, index = [], {}
    for integ in integrations:
        for t in db.jload(integ["tools"], []):
            if allowed is not None and t["name"] not in allowed.get(integ["id"], []):
                continue
            fn = tool_fn_name(integ, t["name"])
            index[fn] = (integ, t["name"])
            fns.append({"type": "function", "function": {
                "name": fn,
                "description": (t.get("description") or t.get("title") or t["name"])[:1000],
                "parameters": t.get("inputSchema") or {"type": "object", "properties": {}},
            }})
    return fns, index


async def run_tool(user, integ, tool_name, args, preselected_user_id=None):
    """Runs a tool with the caller's own connection, or the agent owner's pre-selected connection."""
    acting_uid = preselected_user_id or user["id"]
    token = await auth.integration_token(acting_uid, integ)
    if token is None:
        if preselected_user_id:
            return "The agent owner's pre-selected connection is no longer valid.", acting_uid
        raise ConnectRequired(integ)
    headers = db.jload(integ["headers"], {})
    client = MCPClient(integ["url"], token=token, headers=headers)
    try:
        res = await client.call_tool(tool_name, args)
        text = result_text(res)
        if res.get("isError"):
            text = "Tool error: " + text
    except MCPError as e:
        text = f"Tool call failed: {e}"
    db.audit(user["id"], "tool.call", integration=integ["name"], tool=tool_name,
             acting_user=acting_uid, preselected=bool(preselected_user_id))
    return text, acting_uid


async def stream_completion(token, model, messages, tools):
    body = {"model": model, "messages": messages, "stream": True}
    if tools:
        body["tools"] = tools
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "Accept": "text/event-stream", "X-Snowflake-Authorization-Token-Type": "OAUTH",
               "X-Snowflake-Role": config.SF_ROLE}
    url = f"{config.SNOWFLAKE_ACCOUNT_URL}/api/v2/cortex/v1/chat/completions"
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20)) as c:
        async with c.stream("POST", url, json=body, headers=headers) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"Cortex HTTP {r.status_code}: {(await r.aread()).decode()[:500]}")
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                d = line[5:].strip()
                if not d or d == "[DONE]":
                    continue
                try:
                    yield json.loads(d)
                except ValueError:
                    continue


async def chat_turn(user, model, system_prompt, history, integrations, allowed=None, preselected=None):
    """Async generator of UI events. history: OpenAI-format messages (without system)."""
    token = await auth.login_token(user["id"])
    if not token:
        yield {"type": "error", "message": "Your Snowflake session expired. Please sign in again."}
        return
    tools, index = build_tools(integrations, allowed)
    messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + history
    preselected = preselected or {}
    for _ in range(MAX_TOOL_ROUNDS + 1):
        text, calls = "", {}
        try:
            async for chunk in stream_completion(token, model, messages, tools):
                for ch in chunk.get("choices", []):
                    delta = ch.get("delta") or ch.get("message") or {}
                    if delta.get("content"):
                        text += delta["content"]
                        yield {"type": "token", "text": delta["content"]}
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(tc.get("index", len(calls)), {"id": "", "name": "", "args": ""})
                        slot["id"] = tc.get("id") or slot["id"]
                        fn = tc.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        slot["args"] += fn.get("arguments") or ""
        except Exception as e:  # noqa: BLE001 - surface any provider error to the UI
            yield {"type": "error", "message": str(e)}
            return
        if not calls:
            yield {"type": "assistant_done", "content": text}
            return
        ordered = [calls[k] for k in sorted(calls)]
        messages.append({"role": "assistant", "content": text or None, "tool_calls": [
            {"id": c["id"] or f"call_{i}", "type": "function",
             "function": {"name": c["name"], "arguments": c["args"] or "{}"}} for i, c in enumerate(ordered)]})
        yield {"type": "assistant_partial", "content": text, "tool_calls": messages[-1]["tool_calls"]}
        for i, c in enumerate(ordered):
            call_id = c["id"] or f"call_{i}"
            integ, tname = index.get(c["name"], (None, None))
            try:
                args = json.loads(c["args"] or "{}")
            except ValueError:
                args = {}
            yield {"type": "tool_start", "id": call_id, "integration": integ["name"] if integ else "?",
                   "tool": tname or c["name"], "args": args}
            if not integ:
                out, acting = f"Unknown tool {c['name']}", user["id"]
            else:
                try:
                    out, acting = await run_tool(user, integ, tname, args, preselected.get(integ["id"]))
                except ConnectRequired as cr:
                    yield {"type": "connect_required", "integration_id": cr.integ["id"],
                           "integration": cr.integ["name"]}
                    return
            acting_user = db.one("SELECT email FROM users WHERE id=?", (acting,)) or {}
            yield {"type": "tool_end", "id": call_id, "output": out[:4000],
                   "acting_as": acting_user.get("email", "")}
            messages.append({"role": "tool", "tool_call_id": call_id, "content": out[:MAX_TOOL_CHARS]})
    yield {"type": "error", "message": "Stopped after too many tool rounds."}
