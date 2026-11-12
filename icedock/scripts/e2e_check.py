"""Headless end-to-end check against real Entra + Snowflake, using the tokens stored by a browser sign-in.

Run after signing in once at http://localhost:8000 and connecting "Snowflake Research":
    pixi run e2e-check
"""
import asyncio
import sys

sys.path.insert(0, ".")
from app import auth, db, llm  # noqa: E402
from app.mcp_client import MCPClient, result_text  # noqa: E402


async def main():
    user = db.one("SELECT * FROM users ORDER BY created_at LIMIT 1")
    if not user:
        sys.exit("No user yet: sign in at http://localhost:8000 first")
    integ = db.one("SELECT * FROM integrations WHERE name='Snowflake Research'")
    print(f"user: {user['email']}")

    # 1. Force refresh of both tokens (proves the refresh-token path against Entra)
    db.run("UPDATE tokens SET expires_at=0 WHERE user_id=?", (user["id"],))
    login = await auth.login_token(user["id"])
    mcp_tok = await auth.integration_token(user["id"], integ)
    assert login and mcp_tok, "refresh failed: sign in / connect again"
    c = auth.jwt_claims(mcp_tok)
    print(f"1. refreshed tokens OK  upn={c.get('preferred_username')} scp={c.get('scp')}")

    # 2. MCP tools/list and a direct agent call as the user
    client = MCPClient(integ["url"], token=mcp_tok, headers=db.jload(integ["headers"], {}))
    tools = [t["name"] for t in await client.list_tools()]
    print(f"2. MCP tools: {tools}")
    res = await client.call_tool("research_agent", {"text": "List every fund name you can see with AUM. "
                                                           "Then state CURRENT_USER() and CURRENT_ROLE()."})
    text = result_text(res)
    print("   agent:", text[-300:].replace("\n", " "))
    assert "Alpha" in text and "Secret Beta" not in text, "row access policy not applied as expected"

    # 3. Full chat turn: Cortex LLM as the user -> tool call -> answer
    events = [e async for e in llm.chat_turn(user, db.get_setting("default_model"), llm_system(),
                                             [{"role": "user", "content": "Which funds and AUM can I see?"}],
                                             [integ], {integ["id"]: ["research_agent"]})]
    kinds = [e["type"] for e in events]
    final = next((e["content"] for e in events if e["type"] == "assistant_done"), "")
    errors = [e["message"] for e in events if e["type"] == "error"]
    assert not errors, errors
    assert "tool_end" in kinds, kinds
    print(f"3. chat turn events={sorted(set(kinds))}\n   answer: {final[:300]!r}")
    print("E2E OK")


def llm_system():
    return "Use the research_agent tool for fund questions. Answer briefly."


asyncio.run(main())
