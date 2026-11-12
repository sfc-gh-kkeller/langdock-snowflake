"""OAuth 2.0 Authorization Code + PKCE helpers (Entra SSO login and per-user integration connections)."""
import base64
import hashlib
import json
import secrets
import time
import urllib.parse

import httpx
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import config, db

_signer = URLSafeTimedSerializer(config.SESSION_SECRET, salt="ldc")
SESSION_COOKIE = "ldc_session"
FLOW_COOKIE = "ldc_flow"


def pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def sign(data):
    return _signer.dumps(data)


def unsign(value, max_age):
    try:
        return _signer.loads(value, max_age=max_age)
    except BadSignature:
        return None


def authorize_url(auth_url, client_id, redirect_uri, scope, challenge, state, extra=None):
    params = {"client_id": client_id, "response_type": "code", "redirect_uri": redirect_uri,
              "scope": scope, "state": state, "code_challenge": challenge,
              "code_challenge_method": "S256", **(extra or {})}
    return auth_url + ("&" if "?" in auth_url else "?") + urllib.parse.urlencode(params)


async def token_request(token_url, data):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(token_url, data=data, headers={"Accept": "application/json"})
    try:
        body = r.json()
    except ValueError:
        body = {"error": "invalid_response", "error_description": r.text[:300]}
    if r.status_code >= 400 or "access_token" not in body:
        raise HTTPException(400, f"token endpoint error: {body.get('error')}: {body.get('error_description', '')[:300]}")
    return body


def jwt_claims(tok):
    """Decode a JWT payload without verifying. Only used on tokens received directly
    from the token endpoint over TLS (OIDC Core 3.1.3.7), and for display."""
    try:
        p = tok.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p))
    except Exception:
        return {}


# ---- session ----
def current_user(request: Request):
    raw = request.cookies.get(SESSION_COOKIE)
    data = unsign(raw, 60 * 60 * 12) if raw else None
    if not data:
        raise HTTPException(401, "not signed in")
    user = db.one("SELECT * FROM users WHERE id=?", (data["uid"],))
    if not user:
        raise HTTPException(401, "unknown user")
    return user


def upsert_user(claims):
    oid = claims.get("oid") or claims.get("sub")
    email = claims.get("preferred_username") or claims.get("email") or ""
    name = claims.get("name") or email
    u = db.one("SELECT * FROM users WHERE oid=?", (oid,))
    if u:
        db.run("UPDATE users SET email=?, name=? WHERE id=?", (email, name, u["id"]))
        return db.one("SELECT * FROM users WHERE id=?", (u["id"],))
    first = db.one("SELECT COUNT(*) AS n FROM users")["n"] == 0
    uid = db.new_id()
    db.run("INSERT INTO users (id, oid, email, name, is_admin, created_at) VALUES (?,?,?,?,?,?)",
           (uid, oid, email, name, 1 if first else 0, db.now()))
    return db.one("SELECT * FROM users WHERE id=?", (uid,))


# ---- token access with refresh ----
LOGIN_KEY = "login"


def integration_key(integration_id):
    return f"int:{integration_id}"


async def fresh_token(user_id, key, token_url, client_id, client_secret, scope):
    tok = db.load_token(user_id, key)
    if not tok:
        return None
    if tok["_expires_at"] - 120 > time.time():
        return tok["access_token"]
    if not tok.get("refresh_token"):
        return None
    data = {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": tok["refresh_token"]}
    if client_secret:
        data["client_secret"] = client_secret
    if scope:
        data["scope"] = scope
    try:
        new = await token_request(token_url, data)
    except HTTPException:
        db.delete_token(user_id, key)
        return None
    new.setdefault("refresh_token", tok["refresh_token"])
    db.save_token(user_id, key, new)
    db.audit(user_id, "token.refresh", key=key)
    return new["access_token"]


async def login_token(user_id):
    return await fresh_token(user_id, LOGIN_KEY, f"{config.AUTHORITY}/token", config.CLIENT_ID,
                             config.CLIENT_SECRET, config.LOGIN_SCOPE)


async def integration_token(user_id, integ):
    if integ["auth_type"] == "none":
        return ""
    if integ["auth_type"] == "bearer":
        return db.dec(integ["client_secret"])
    return await fresh_token(user_id, integration_key(integ["id"]), integ["token_url"], integ["client_id"],
                             db.dec(integ["client_secret"]), integ["scope"])
