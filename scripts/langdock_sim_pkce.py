"""Simulate Langdock's 'OAuth 2.0 Manual (Authorization Code + PKCE)' MCP connector.

Confidential client + PKCE, browser sign-in, code exchange, MCP call, refresh, MCP call again.
"""
import base64, hashlib, http.server, json, os, secrets, sys, urllib.parse, urllib.request, webbrowser

TENANT = os.environ["ENTRA_TENANT_ID"]
CLIENT_ID = os.environ["ENTRA_CLIENT_ID"]          # client app (redirect http://localhost:8765/callback)
CLIENT_SECRET = os.environ["ENTRA_CLIENT_SECRET"]
REDIRECT = "http://localhost:8765/callback"
ROLE = os.environ.get("SF_ROLE", "MCP_USER")
SCOPE = f"api://{os.environ['SNOWFLAKE_APP_ID']}/session:role:{ROLE} offline_access"
AUTH = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize"
TOKEN = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
MCP = os.environ["MCP_URL"]

verifier = secrets.token_urlsafe(64)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
state = secrets.token_urlsafe(16)
result = {}


class Callback(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        result.update({k: v[0] for k, v in q.items()})
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Signed in. You can close this tab and return to the terminal.")

    def log_message(self, *a):
        pass


def post_form(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    return json.loads(urllib.request.urlopen(req).read())


def claims(tok):
    p = tok.split(".")[1]; p += "=" * (-len(p) % 4)
    c = json.loads(base64.urlsafe_b64decode(p))
    return {k: c.get(k) for k in ("preferred_username", "scp", "azp", "aud", "ver")}


def mcp(tok, i, method, params=None):
    body = {"jsonrpc": "2.0", "id": i, "method": method, **({"params": params} if params else {})}
    req = urllib.request.Request(MCP, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {tok}", "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream", "X-Snowflake-Role": ROLE})
    try:
        raw = urllib.request.urlopen(req, timeout=300).read().decode()
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:300]}
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    ev = [json.loads(l[5:]) for l in raw.splitlines() if l.startswith("data:") and l[5:].strip() not in ("", "[DONE]")]
    return ev[-1] if ev else raw


url = AUTH + "?" + urllib.parse.urlencode({
    "client_id": CLIENT_ID, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPE,
    "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account"})
srv = http.server.HTTPServer(("localhost", 8765), Callback)
print("Opening browser for Entra sign-in ...", flush=True)
webbrowser.open(url)
while "code" not in result and "error" not in result:
    srv.handle_request()
if "error" in result or result.get("state") != state:
    sys.exit(f"auth failed: {result}")

tok = post_form(TOKEN, {"grant_type": "authorization_code", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                        "code": result["code"], "redirect_uri": REDIRECT, "code_verifier": verifier, "scope": SCOPE})
print("1) Auth code + PKCE token claims:", claims(tok["access_token"]), "| refresh_token:", "refresh_token" in tok)
print("   MCP initialize:", json.dumps(mcp(tok["access_token"], 1, "initialize", {
    "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "langdock-sim", "version": "0"}}))[:160])
r = mcp(tok["access_token"], 2, "tools/call", {"name": "research_agent", "arguments": {
    "text": "Use the funds tool to list all fund names. Answer in one line, then state current user and role."}})
try:
    print("   Agent:", [c["text"] for c in r["result"]["content"]][-1][-400:])
except Exception:
    print("   Agent raw:", json.dumps(r)[-600:])

tok2 = post_form(TOKEN, {"grant_type": "refresh_token", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                         "refresh_token": tok["refresh_token"], "scope": SCOPE})
print("2) Refreshed token claims:", claims(tok2["access_token"]))
print("   MCP tools/list after refresh:",
      [t["name"] for t in mcp(tok2["access_token"], 3, "tools/list").get("result", {}).get("tools", [])])
