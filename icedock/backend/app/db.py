"""SQLite storage. Secrets (tokens, client secrets) are Fernet-encrypted at rest."""
import base64
import hashlib
import json
import sqlite3
import threading
import time
import uuid

from cryptography.fernet import Fernet

from . import config

_lock = threading.Lock()
_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(config.SESSION_SECRET.encode()).digest()))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, oid TEXT UNIQUE, email TEXT, name TEXT,
  is_admin INTEGER DEFAULT 0, created_at REAL);
CREATE TABLE IF NOT EXISTS tokens (
  user_id TEXT, key TEXT, data TEXT, expires_at REAL, updated_at REAL,
  PRIMARY KEY (user_id, key));
CREATE TABLE IF NOT EXISTS integrations (
  id TEXT PRIMARY KEY, name TEXT, description TEXT, icon TEXT, url TEXT,
  auth_type TEXT, auth_url TEXT, token_url TEXT, client_id TEXT, client_secret TEXT,
  scope TEXT, send_resource INTEGER, headers TEXT, shared INTEGER, created_by TEXT,
  tools TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY, name TEXT, emoji TEXT, description TEXT, instructions TEXT,
  model TEXT, starters TEXT, actions TEXT, preselected TEXT, visibility TEXT,
  created_by TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY, user_id TEXT, title TEXT, agent_id TEXT, model TEXT,
  pinned INTEGER DEFAULT 0, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, chat_id TEXT, role TEXT, content TEXT, tool_calls TEXT,
  created_at REAL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, user_id TEXT, event TEXT, detail TEXT);
"""


def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


_conn = None


def conn():
    global _conn
    if _conn is None:
        _conn = connect()
        _conn.executescript(SCHEMA)
    return _conn


def reset_for_tests(path):
    global _conn
    config.DB_PATH = path
    _conn = None


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def run(sql, args=()):
    with _lock:
        c = conn()
        c.execute(sql, args)
        c.commit()


def new_id():
    return uuid.uuid4().hex[:16]


def now():
    return time.time()


def enc(s):
    return _fernet.encrypt(s.encode()).decode() if s else ""


def dec(s):
    return _fernet.decrypt(s.encode()).decode() if s else ""


def jload(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def audit(user_id, event, **detail):
    run("INSERT INTO audit (ts, user_id, event, detail) VALUES (?,?,?,?)",
        (now(), user_id, event, json.dumps(detail)[:4000]))


def get_setting(key, default=None):
    r = one("SELECT value FROM settings WHERE key=?", (key,))
    return jload(r["value"], default) if r else default


def set_setting(key, value):
    run("INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)))


# ---- tokens ----
def save_token(user_id, key, tok):
    expires = now() + int(tok.get("expires_in", 3600))
    run("INSERT INTO tokens (user_id, key, data, expires_at, updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(user_id, key) DO UPDATE SET data=excluded.data, expires_at=excluded.expires_at, "
        "updated_at=excluded.updated_at",
        (user_id, key, enc(json.dumps(tok)), expires, now()))


def load_token(user_id, key):
    r = one("SELECT data, expires_at FROM tokens WHERE user_id=? AND key=?", (user_id, key))
    if not r:
        return None
    tok = json.loads(dec(r["data"]))
    tok["_expires_at"] = r["expires_at"]
    return tok


def delete_token(user_id, key):
    run("DELETE FROM tokens WHERE user_id=? AND key=?", (user_id, key))
