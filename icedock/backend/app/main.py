import json
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, config, db, llm
from .mcp_client import MCPClient, MCPError, result_text

app = FastAPI(title="Icedock")
api = APIRouter(prefix="/api")
User = Depends(auth.current_user)
COOKIE_OPTS = dict(httponly=True, samesite="lax", secure=config.BASE_URL.startswith("https"))


def require_admin(user=User):
    if not user["is_admin"]:
        raise HTTPException(403, "admin only")
    return user


# ---------------------------------------------------------------- seed
def seed():
    if config.MCP_URL and not db.one("SELECT id FROM integrations"):
        db.run("INSERT INTO integrations (id, name, description, icon, url, auth_type, auth_url, token_url, client_id, "
               "client_secret, scope, send_resource, headers, shared, created_by, tools, created_at) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (db.new_id(), "Snowflake Research", "Snowflake managed MCP server (Cortex Agent + Search)", "snowflake",
                config.MCP_URL, "oauth_manual", f"{config.AUTHORITY}/authorize", f"{config.AUTHORITY}/token",
                config.CLIENT_ID, db.enc(config.CLIENT_SECRET), f"{config.SF_SCOPE} offline_access", 0,
                json.dumps({"X-Snowflake-Role": config.SF_ROLE}), 1, None, "[]", db.now()))
    if db.get_setting("models") is None:
        db.set_setting("models", config.DEFAULT_MODELS)
        db.set_setting("default_model", config.DEFAULT_MODELS[0])
        db.set_setting("workspace_name", "My Workspace")


seed()


# ---------------------------------------------------------------- auth
@app.get("/auth/login")
def login(prompt: Optional[str] = None):
    verifier, challenge = auth.pkce()
    state = secrets.token_urlsafe(16)
    extra = {"prompt": prompt} if prompt in ("select_account", "login") else {}
    url = auth.authorize_url(f"{config.AUTHORITY}/authorize", config.CLIENT_ID, f"{config.BASE_URL}/auth/callback",
                             config.LOGIN_SCOPE, challenge, state, extra)
    r = RedirectResponse(url)
    r.set_cookie(auth.FLOW_COOKIE, auth.sign({"s": state, "v": verifier, "k": "login"}), max_age=600, **COOKIE_OPTS)
    return r


@app.get("/auth/callback")
async def login_callback(request: Request, code: str = "", state: str = "", error: str = "",
                         error_description: str = ""):
    flow = auth.unsign(request.cookies.get(auth.FLOW_COOKIE, ""), 600)
    if error:
        return RedirectResponse(f"/login?error={error}")
    if not flow or flow.get("k") != "login" or flow["s"] != state:
        raise HTTPException(400, "invalid state")
    tok = await auth.token_request(f"{config.AUTHORITY}/token", {
        "grant_type": "authorization_code", "client_id": config.CLIENT_ID, "client_secret": config.CLIENT_SECRET,
        "code": code, "redirect_uri": f"{config.BASE_URL}/auth/callback", "code_verifier": flow["v"],
        "scope": config.LOGIN_SCOPE})
    claims = auth.jwt_claims(tok.get("id_token", ""))
    if claims.get("tid") != config.TENANT or claims.get("aud") != config.CLIENT_ID:
        raise HTTPException(400, "id_token tenant/audience mismatch")
    user = auth.upsert_user(claims)
    db.save_token(user["id"], auth.LOGIN_KEY, {k: tok[k] for k in ("access_token", "refresh_token", "expires_in")
                                               if k in tok})
    db.audit(user["id"], "login", email=user["email"])
    r = RedirectResponse("/")
    r.delete_cookie(auth.FLOW_COOKIE)
    r.set_cookie(auth.SESSION_COOKIE, auth.sign({"uid": user["id"]}), max_age=60 * 60 * 12, **COOKIE_OPTS)
    return r


@app.post("/auth/logout")
def logout(user=User):
    db.delete_token(user["id"], auth.LOGIN_KEY)
    db.audit(user["id"], "logout")
    r = JSONResponse({"ok": True})
    r.delete_cookie(auth.SESSION_COOKIE)
    return r


@api.get("/me")
async def me(user=User):
    tok = db.load_token(user["id"], auth.LOGIN_KEY) or {}
    c = auth.jwt_claims(tok.get("access_token", ""))
    return {"id": user["id"], "email": user["email"], "name": user["name"], "is_admin": bool(user["is_admin"]),
            "snowflake": {"scp": c.get("scp"), "aud": c.get("aud"), "exp": c.get("exp"),
                          "upn": c.get("preferred_username"), "account": config.SNOWFLAKE_ACCOUNT_URL},
            "workspace": db.get_setting("workspace_name", "Workspace")}


# ---------------------------------------------------------------- settings / models
class SettingsIn(BaseModel):
    models: list[str]
    default_model: str
    workspace_name: str


@api.get("/settings")
def get_settings(user=User):
    return {"models": db.get_setting("models", []), "default_model": db.get_setting("default_model"),
            "workspace_name": db.get_setting("workspace_name")}


@api.put("/settings")
def put_settings(body: SettingsIn, user=Depends(require_admin)):
    db.set_setting("models", [m.strip() for m in body.models if m.strip()])
    db.set_setting("default_model", body.default_model)
    db.set_setting("workspace_name", body.workspace_name)
    db.audit(user["id"], "settings.update")
    return get_settings(user)


@api.get("/members")
def members(user=User):
    return db.q("SELECT id, email, name, is_admin, created_at FROM users ORDER BY created_at")


class RoleIn(BaseModel):
    is_admin: bool


@api.put("/members/{uid}")
def set_member(uid: str, body: RoleIn, user=Depends(require_admin)):
    db.run("UPDATE users SET is_admin=? WHERE id=?", (1 if body.is_admin else 0, uid))
    return {"ok": True}


@api.get("/audit")
def audit_log(user=Depends(require_admin), limit: int = 200):
    rows = db.q("SELECT a.*, u.email FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT ?",
                (min(limit, 1000),))
    for r in rows:
        r["detail"] = db.jload(r["detail"], {})
    return rows


# ---------------------------------------------------------------- integrations
class IntegrationIn(BaseModel):
    name: str
    description: str = ""
    icon: str = "plug"
    url: str
    auth_type: str = "oauth_manual"  # none | bearer | oauth_manual
    auth_url: str = ""
    token_url: str = ""
    client_id: str = ""
    client_secret: Optional[str] = None  # None = keep existing
    scope: str = ""
    send_resource: bool = False
    headers: dict = {}
    shared: bool = True


def integ_out(i, user):
    connected = True
    if i["auth_type"] == "oauth_manual":
        connected = db.load_token(user["id"], auth.integration_key(i["id"])) is not None
    return {"id": i["id"], "name": i["name"], "description": i["description"], "icon": i["icon"], "url": i["url"],
            "auth_type": i["auth_type"], "auth_url": i["auth_url"], "token_url": i["token_url"],
            "client_id": i["client_id"], "has_secret": bool(i["client_secret"]), "scope": i["scope"],
            "send_resource": bool(i["send_resource"]), "headers": db.jload(i["headers"], {}),
            "shared": bool(i["shared"]), "created_by": i["created_by"], "tools": db.jload(i["tools"], []),
            "connected": connected, "can_edit": bool(user["is_admin"]) or i["created_by"] == user["id"]}


def visible_integrations(user):
    return db.q("SELECT * FROM integrations WHERE shared=1 OR created_by=? ORDER BY created_at", (user["id"],))


def get_integ(iid, user, edit=False):
    i = db.one("SELECT * FROM integrations WHERE id=?", (iid,))
    if not i or not (i["shared"] or i["created_by"] == user["id"]):
        raise HTTPException(404, "integration not found")
    if edit and not (user["is_admin"] or i["created_by"] == user["id"]):
        raise HTTPException(403, "not allowed")
    return i


@api.get("/integrations")
def list_integrations(user=User):
    return [integ_out(i, user) for i in visible_integrations(user)]


@api.post("/integrations")
def create_integration(body: IntegrationIn, user=User):
    iid = db.new_id()
    db.run("INSERT INTO integrations (id, name, description, icon, url, auth_type, auth_url, token_url, client_id, "
           "client_secret, scope, send_resource, headers, shared, created_by, tools, created_at) "
           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
           (iid, body.name, body.description, body.icon, body.url, body.auth_type, body.auth_url, body.token_url,
            body.client_id, db.enc(body.client_secret or ""), body.scope, int(body.send_resource),
            json.dumps(body.headers), int(body.shared and bool(user["is_admin"])), user["id"], "[]", db.now()))
    db.audit(user["id"], "integration.create", name=body.name)
    return integ_out(db.one("SELECT * FROM integrations WHERE id=?", (iid,)), user)


@api.put("/integrations/{iid}")
def update_integration(iid: str, body: IntegrationIn, user=User):
    i = get_integ(iid, user, edit=True)
    secret = i["client_secret"] if body.client_secret is None else db.enc(body.client_secret)
    db.run("UPDATE integrations SET name=?, description=?, icon=?, url=?, auth_type=?, auth_url=?, token_url=?, "
           "client_id=?, client_secret=?, scope=?, send_resource=?, headers=?, shared=? WHERE id=?",
           (body.name, body.description, body.icon, body.url, body.auth_type, body.auth_url, body.token_url,
            body.client_id, secret, body.scope, int(body.send_resource), json.dumps(body.headers),
            int(body.shared if user["is_admin"] else i["shared"]), iid))
    db.audit(user["id"], "integration.update", name=body.name)
    return integ_out(db.one("SELECT * FROM integrations WHERE id=?", (iid,)), user)


@api.delete("/integrations/{iid}")
def delete_integration(iid: str, user=User):
    get_integ(iid, user, edit=True)
    db.run("DELETE FROM integrations WHERE id=?", (iid,))
    db.run("DELETE FROM tokens WHERE key=?", (auth.integration_key(iid),))
    db.audit(user["id"], "integration.delete", id=iid)
    return {"ok": True}


@api.get("/integrations/{iid}/connect")
def connect_integration(iid: str, user=User):
    i = get_integ(iid, user)
    if i["auth_type"] != "oauth_manual":
        raise HTTPException(400, "integration does not use OAuth")
    verifier, challenge = auth.pkce()
    state = secrets.token_urlsafe(16)
    extra = {"resource": i["url"]} if i["send_resource"] else {}
    url = auth.authorize_url(i["auth_url"], i["client_id"], f"{config.BASE_URL}/api/integrations/callback",
                             i["scope"], challenge, state, extra)
    r = RedirectResponse(url)
    r.set_cookie(auth.FLOW_COOKIE, auth.sign({"s": state, "v": verifier, "k": "int", "iid": iid, "uid": user["id"]}),
                 max_age=600, **COOKIE_OPTS)
    return r


async def refresh_tools(i, user):
    token = await auth.integration_token(user["id"], i)
    if token is None:
        raise HTTPException(409, "connect first")
    try:
        tools = await MCPClient(i["url"], token=token, headers=db.jload(i["headers"], {})).list_tools()
    except MCPError as e:
        raise HTTPException(502, f"MCP error: {e}")
    slim = [{"name": t["name"], "title": t.get("title", ""), "description": t.get("description", ""),
             "inputSchema": t.get("inputSchema") or {"type": "object", "properties": {}}} for t in tools]
    db.run("UPDATE integrations SET tools=? WHERE id=?", (json.dumps(slim), i["id"]))
    return slim


@api.get("/integrations/callback")
async def integration_callback(request: Request, code: str = "", state: str = "", error: str = "",
                               error_description: str = ""):
    flow = auth.unsign(request.cookies.get(auth.FLOW_COOKIE, ""), 600)
    user = auth.current_user(request)
    if error:
        return RedirectResponse(f"/oauth-done?status=error&message={error}")
    if not flow or flow.get("k") != "int" or flow["s"] != state or flow["uid"] != user["id"]:
        raise HTTPException(400, "invalid state")
    i = get_integ(flow["iid"], user)
    data = {"grant_type": "authorization_code", "client_id": i["client_id"], "code": code,
            "redirect_uri": f"{config.BASE_URL}/api/integrations/callback", "code_verifier": flow["v"],
            "scope": i["scope"]}
    if i["client_secret"]:
        data["client_secret"] = db.dec(i["client_secret"])
    if i["send_resource"]:
        data["resource"] = i["url"]
    tok = await auth.token_request(i["token_url"], data)
    db.save_token(user["id"], auth.integration_key(i["id"]),
                  {k: tok[k] for k in ("access_token", "refresh_token", "expires_in") if k in tok})
    db.audit(user["id"], "integration.connect", name=i["name"],
             upn=auth.jwt_claims(tok["access_token"]).get("preferred_username"))
    try:
        await refresh_tools(i, user)
        status = "ok"
    except HTTPException as e:
        status = f"connected, tool discovery failed: {e.detail}"
    r = RedirectResponse(f"/oauth-done?status={'ok' if status == 'ok' else 'warn'}&iid={i['id']}")
    r.delete_cookie(auth.FLOW_COOKIE)
    return r


@api.post("/integrations/{iid}/disconnect")
def disconnect_integration(iid: str, user=User):
    i = get_integ(iid, user)
    db.delete_token(user["id"], auth.integration_key(iid))
    db.audit(user["id"], "integration.disconnect", name=i["name"])
    return {"ok": True}


@api.post("/integrations/{iid}/tools/refresh")
async def refresh_integration_tools(iid: str, user=User):
    return await refresh_tools(get_integ(iid, user), user)


class ToolTestIn(BaseModel):
    tool: str
    arguments: dict = {}


@api.post("/integrations/{iid}/tools/test")
async def test_tool(iid: str, body: ToolTestIn, user=User):
    i = get_integ(iid, user)
    token = await auth.integration_token(user["id"], i)
    if token is None:
        raise HTTPException(409, "connect first")
    t0 = time.time()
    try:
        res = await MCPClient(i["url"], token=token, headers=db.jload(i["headers"], {})).call_tool(
            body.tool, body.arguments)
    except MCPError as e:
        raise HTTPException(502, str(e))
    db.audit(user["id"], "tool.test", integration=i["name"], tool=body.tool)
    return {"text": result_text(res), "is_error": bool(res.get("isError")), "ms": int((time.time() - t0) * 1000)}


# ---------------------------------------------------------------- agents
class AgentIn(BaseModel):
    name: str
    emoji: str = "🤖"
    description: str = ""
    instructions: str = ""
    model: str = ""
    starters: list[str] = []
    actions: dict = {}  # {integration_id: [tool names]}
    preselect: list[str] = []  # integration ids where the owner's connection is pre-selected
    visibility: str = "private"  # private | workspace


def agent_out(a, user):
    owner = db.one("SELECT email, name FROM users WHERE id=?", (a["created_by"],)) or {}
    return {"id": a["id"], "name": a["name"], "emoji": a["emoji"], "description": a["description"],
            "instructions": a["instructions"], "model": a["model"], "starters": db.jload(a["starters"], []),
            "actions": db.jload(a["actions"], {}), "preselect": list(db.jload(a["preselected"], {}).keys()),
            "visibility": a["visibility"], "owner": owner.get("name") or owner.get("email"),
            "can_edit": a["created_by"] == user["id"] or bool(user["is_admin"]), "updated_at": a["updated_at"]}


def get_agent(aid, user, edit=False):
    a = db.one("SELECT * FROM agents WHERE id=?", (aid,))
    if not a or not (a["visibility"] == "workspace" or a["created_by"] == user["id"]):
        raise HTTPException(404, "agent not found")
    if edit and not (a["created_by"] == user["id"] or user["is_admin"]):
        raise HTTPException(403, "not allowed")
    return a


def preselect_map(body: AgentIn, owner_id):
    out = {}
    for iid in body.preselect:
        if db.load_token(owner_id, auth.integration_key(iid)) is None:
            raise HTTPException(400, "connect the integration yourself before pre-selecting your connection")
        out[iid] = owner_id
    return out


@api.get("/agents")
def list_agents(user=User):
    rows = db.q("SELECT * FROM agents WHERE visibility='workspace' OR created_by=? ORDER BY updated_at DESC",
                (user["id"],))
    return [agent_out(a, user) for a in rows]


@api.get("/agents/{aid}")
def read_agent(aid: str, user=User):
    return agent_out(get_agent(aid, user), user)


@api.post("/agents")
def create_agent(body: AgentIn, user=User):
    aid = db.new_id()
    db.run("INSERT INTO agents (id, name, emoji, description, instructions, model, starters, actions, preselected, "
           "visibility, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
           (aid, body.name, body.emoji, body.description, body.instructions, body.model, json.dumps(body.starters),
            json.dumps(body.actions), json.dumps(preselect_map(body, user["id"])), body.visibility, user["id"],
            db.now(), db.now()))
    db.audit(user["id"], "agent.create", name=body.name, preselect=body.preselect)
    return agent_out(db.one("SELECT * FROM agents WHERE id=?", (aid,)), user)


@api.put("/agents/{aid}")
def update_agent(aid: str, body: AgentIn, user=User):
    a = get_agent(aid, user, edit=True)
    pre = db.jload(a["preselected"], {})
    new_pre = {iid: pre[iid] for iid in body.preselect if iid in pre}
    missing = AgentIn(**{**body.model_dump(), "preselect": [i for i in body.preselect if i not in pre]})
    new_pre.update(preselect_map(missing, user["id"]))
    db.run("UPDATE agents SET name=?, emoji=?, description=?, instructions=?, model=?, starters=?, actions=?, "
           "preselected=?, visibility=?, updated_at=? WHERE id=?",
           (body.name, body.emoji, body.description, body.instructions, body.model, json.dumps(body.starters),
            json.dumps(body.actions), json.dumps(new_pre), body.visibility, db.now(), aid))
    db.audit(user["id"], "agent.update", name=body.name, preselect=list(new_pre))
    return agent_out(db.one("SELECT * FROM agents WHERE id=?", (aid,)), user)


@api.delete("/agents/{aid}")
def delete_agent(aid: str, user=User):
    get_agent(aid, user, edit=True)
    db.run("DELETE FROM agents WHERE id=?", (aid,))
    return {"ok": True}


# ---------------------------------------------------------------- chats
class ChatIn(BaseModel):
    agent_id: Optional[str] = None
    model: Optional[str] = None


class ChatPatch(BaseModel):
    title: Optional[str] = None
    pinned: Optional[bool] = None
    model: Optional[str] = None


def get_chat(cid, user):
    c = db.one("SELECT * FROM chats WHERE id=? AND user_id=?", (cid, user["id"]))
    if not c:
        raise HTTPException(404, "chat not found")
    return c


@api.get("/chats")
def list_chats(user=User, q: str = ""):
    rows = db.q("SELECT c.*, a.name AS agent_name, a.emoji AS agent_emoji FROM chats c "
                "LEFT JOIN agents a ON a.id=c.agent_id WHERE c.user_id=? AND c.title LIKE ? "
                "ORDER BY c.pinned DESC, c.updated_at DESC LIMIT 300", (user["id"], f"%{q}%"))
    return rows


@api.post("/chats")
def create_chat(body: ChatIn, user=User):
    model = body.model or db.get_setting("default_model")
    if body.agent_id:
        a = get_agent(body.agent_id, user)
        model = a["model"] or model
    cid = db.new_id()
    db.run("INSERT INTO chats (id, user_id, title, agent_id, model, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
           (cid, user["id"], "New chat", body.agent_id, model, db.now(), db.now()))
    return db.one("SELECT * FROM chats WHERE id=?", (cid,))


@api.get("/chats/{cid}")
def read_chat(cid: str, user=User):
    c = get_chat(cid, user)
    msgs = db.q("SELECT * FROM messages WHERE chat_id=? ORDER BY created_at", (cid,))
    for m in msgs:
        m["tool_calls"] = db.jload(m["tool_calls"], [])
    agent = agent_out(get_agent(c["agent_id"], user), user) if c["agent_id"] else None
    return {**c, "messages": msgs, "agent": agent}


@api.patch("/chats/{cid}")
def patch_chat(cid: str, body: ChatPatch, user=User):
    get_chat(cid, user)
    if body.title is not None:
        db.run("UPDATE chats SET title=? WHERE id=?", (body.title[:120], cid))
    if body.pinned is not None:
        db.run("UPDATE chats SET pinned=? WHERE id=?", (int(body.pinned), cid))
    if body.model is not None:
        db.run("UPDATE chats SET model=? WHERE id=?", (body.model, cid))
    return db.one("SELECT * FROM chats WHERE id=?", (cid,))


@api.delete("/chats/{cid}")
def delete_chat(cid: str, user=User):
    get_chat(cid, user)
    db.run("DELETE FROM messages WHERE chat_id=?", (cid,))
    db.run("DELETE FROM chats WHERE id=?", (cid,))
    return {"ok": True}


class MessageIn(BaseModel):
    content: str
    integrations: list[str] = []  # tools enabled for a plain chat
    regenerate: bool = False


BASE_SYSTEM = ("You are a helpful assistant in the {ws} workspace. Format answers in Markdown. "
               "When a tool is available that can answer the question with company data, use it rather than guessing.")


@api.post("/chats/{cid}/messages")
async def post_message(cid: str, body: MessageIn, user=User):
    chat = get_chat(cid, user)
    if body.regenerate:
        last = db.one("SELECT id FROM messages WHERE chat_id=? AND role='assistant' ORDER BY created_at DESC LIMIT 1",
                      (cid,))
        if last:
            db.run("DELETE FROM messages WHERE id=?", (last["id"],))
    else:
        db.run("INSERT INTO messages (id, chat_id, role, content, tool_calls, created_at) VALUES (?,?,?,?,?,?)",
               (db.new_id(), cid, "user", body.content, "[]", db.now()))
        if chat["title"] == "New chat":
            db.run("UPDATE chats SET title=? WHERE id=?", (body.content.strip().splitlines()[0][:60] or "New chat", cid))

    history = [{"role": m["role"], "content": m["content"]}
               for m in db.q("SELECT role, content FROM messages WHERE chat_id=? ORDER BY created_at", (cid,))
               if m["content"]]
    ws = db.get_setting("workspace_name", "workspace")
    system = BASE_SYSTEM.format(ws=ws)
    all_integs = {i["id"]: i for i in visible_integrations(user)}
    allowed, preselected = None, {}
    if chat["agent_id"]:
        a = get_agent(chat["agent_id"], user)
        system += "\n\n" + (a["instructions"] or "")
        allowed = db.jload(a["actions"], {})
        integs = [all_integs[i] for i in allowed if i in all_integs]
        preselected = db.jload(a["preselected"], {})
    else:
        integs = [all_integs[i] for i in body.integrations if i in all_integs]
    model = chat["model"] or db.get_setting("default_model")
    db.audit(user["id"], "chat.message", chat=cid, model=model, agent=chat["agent_id"],
             tools=[i["name"] for i in integs])

    async def gen():
        trace, final = [], ""
        yield sse({"type": "start", "model": model})
        async for ev in llm.chat_turn(user, model, system, history, integs, allowed, preselected):
            if ev["type"] == "tool_start":
                trace.append({k: ev[k] for k in ("id", "integration", "tool", "args")})
            elif ev["type"] == "tool_end":
                for t in trace:
                    if t["id"] == ev["id"]:
                        t.update(output=ev["output"], acting_as=ev["acting_as"])
            elif ev["type"] == "assistant_partial" and ev["content"]:
                final += ev["content"] + "\n\n"
            elif ev["type"] == "assistant_done":
                final += ev["content"]
            elif ev["type"] in ("error", "connect_required"):
                final += ""
            yield sse(ev)
        mid = db.new_id()
        if final.strip() or trace:
            db.run("INSERT INTO messages (id, chat_id, role, content, tool_calls, created_at) VALUES (?,?,?,?,?,?)",
                   (mid, cid, "assistant", final.strip(), json.dumps(trace), db.now()))
        db.run("UPDATE chats SET updated_at=? WHERE id=?", (db.now(), cid))
        yield sse({"type": "done", "message_id": mid})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def sse(ev):
    return f"data: {json.dumps(ev)}\n\n"


app.include_router(api)


# ---------------------------------------------------------------- SPA
@app.get("/healthz")
def healthz():
    return {"ok": True}


if config.WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = config.WEB_DIST / path
        if path and f.is_file() and config.WEB_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(config.WEB_DIST / "index.html")
