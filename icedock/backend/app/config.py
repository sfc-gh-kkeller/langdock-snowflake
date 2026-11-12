import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def env(name, default=None):
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"missing env var {name} (see icedock/.env.example)")
    return v


TENANT = env("ENTRA_TENANT_ID", "test-tenant")
CLIENT_ID = env("ENTRA_CLIENT_ID", "test-client")
CLIENT_SECRET = env("ENTRA_CLIENT_SECRET", "test-secret")
SNOWFLAKE_APP_ID = env("SNOWFLAKE_APP_ID", "test-app")
SNOWFLAKE_ACCOUNT_URL = env("SNOWFLAKE_ACCOUNT_URL", "https://example.snowflakecomputing.com").rstrip("/")
SF_ROLE = env("SF_ROLE", "LDC_MCP_USER")
MCP_URL = os.environ.get("MCP_URL", "")
BASE_URL = env("APP_BASE_URL", "http://localhost:8000").rstrip("/")
SESSION_SECRET = env("SESSION_SECRET", "dev-only-secret-change-me")
DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "data" / "icedock.db"))
WEB_DIST = ROOT / "web" / "dist"

AUTHORITY = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0"
SF_SCOPE = f"api://{SNOWFLAKE_APP_ID}/session:role:{SF_ROLE}"
LOGIN_SCOPE = f"openid profile email offline_access {SF_SCOPE}"

DEFAULT_MODELS = [
    "claude-sonnet-4-5",
    "claude-4-sonnet",
    "openai-gpt-4.1",
    "llama3.3-70b",
    "mistral-large2",
]
