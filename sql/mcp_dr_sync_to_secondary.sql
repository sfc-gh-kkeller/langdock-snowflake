-- =====================================================================
-- Keep Snowflake-managed MCP servers in sync on the secondary (DR) account
--
-- Why: MCP server objects are NOT replicated by failover groups
--      ("If you use replication, you must recreate MCP server objects on the
--       secondary account. OAuth security integrations are replicated.")
--      https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp
--
-- Design:
--   * MCP servers live in a small LOCAL database (MCP_LOCAL), not in a
--     replicated database. Replicated databases are read-only on the secondary,
--     so objects cannot be created there. Same database/schema name on both
--     accounts keeps the MCP URL path identical.
--   * The tools (Cortex Agent, Cortex Search, semantic views) live in the
--     replicated databases and are referenced by fully qualified name.
--   * A task on the PRIMARY reads each MCP server spec (DESCRIBE MCP SERVER)
--     and recreates it on the SECONDARY through the SQL API, via an
--     External Access Integration. Auth: PAT of a dedicated service user
--     on the secondary, stored in a Snowflake SECRET.
--
-- Tested (primary AWS EU, secondary second account): CREATE + GRANT both
-- HTTP 200, spec identical on both sides, owner MCP_DEPLOYER on the secondary.
--   * CREATE MCP SERVER does not check that the referenced agent / search
--     service exist. The procedure therefore pre-checks each tool target on
--     the secondary (DESCRIBE via SQL API) and skips the server if one is
--     missing (they must arrive via the failover group). Give MCP_DEPLOYER
--     USAGE on the replicated agent / search service / semantic view so the
--     check can see them.
--   * Service-user PAT needs a network policy: allow the primary's
--     SELECT SYSTEM$GET_SNOWFLAKE_EGRESS_IP_RANGES() prefixes (they carry an
--     expiry date; re-check them when you rotate the PAT).
--   * Any skipped or non-200 step raises, so the task run shows FAILED in
--     TASK_HISTORY; add ERROR_INTEGRATION on the task for a notification.
--   * The PAT expires (DAYS_TO_EXPIRY); rotate it and update the SECRET
--     before then, otherwise the sync fails (and is reported as FAILED).
--
-- Status: sample. Review and test before production use.
-- =====================================================================


-- ---------------------------------------------------------------------
-- PART A  (run on BOTH accounts once): local MCP database + OAuth binding
-- ---------------------------------------------------------------------
USE ROLE ACCOUNTADMIN;
CREATE DATABASE IF NOT EXISTS MCP_LOCAL COMMENT = 'Local, not replicated: MCP servers';
CREATE SCHEMA IF NOT EXISTS MCP_LOCAL.MCP;
-- The External OAuth integration is replicated; bind it on each account:
ALTER SCHEMA MCP_LOCAL.MCP SET
  OAUTH_AUTHORIZATION_SERVER = ENTRA_MCP_V2
  OAUTH_SCOPES_SUPPORTED     = 'session:role:MCP_USER';
GRANT USAGE ON DATABASE MCP_LOCAL      TO ROLE MCP_USER;
GRANT USAGE ON SCHEMA   MCP_LOCAL.MCP  TO ROLE MCP_USER;


-- ---------------------------------------------------------------------
-- PART B  (run on the SECONDARY once): deployer service user + role
-- ---------------------------------------------------------------------
USE ROLE ACCOUNTADMIN;
CREATE ROLE IF NOT EXISTS MCP_DEPLOYER;
GRANT USAGE ON DATABASE MCP_LOCAL TO ROLE MCP_DEPLOYER;
GRANT USAGE, CREATE MCP SERVER ON SCHEMA MCP_LOCAL.MCP TO ROLE MCP_DEPLOYER;
GRANT ROLE MCP_DEPLOYER TO ROLE SYSADMIN;

CREATE USER IF NOT EXISTS SVC_MCP_DEPLOYER TYPE = SERVICE DEFAULT_ROLE = MCP_DEPLOYER
  COMMENT = 'Recreates MCP servers from the primary';
GRANT ROLE MCP_DEPLOYER TO USER SVC_MCP_DEPLOYER;

-- PATs for service users require a network policy. Allow the primary's
-- Snowflake egress (check SYSTEM$GET_SNOWFLAKE_EGRESS_IP_RANGES() / your
-- PrivateLink setup on the primary) and nothing else.
CREATE NETWORK RULE IF NOT EXISTS MCP_LOCAL.MCP.PRIMARY_EGRESS
  TYPE = IPV4 MODE = INGRESS VALUE_LIST = ('<primary_egress_cidr>');
CREATE NETWORK POLICY IF NOT EXISTS MCP_DEPLOYER_ONLY_PRIMARY
  ALLOWED_NETWORK_RULE_LIST = ('MCP_LOCAL.MCP.PRIMARY_EGRESS');
ALTER USER SVC_MCP_DEPLOYER SET NETWORK_POLICY = MCP_DEPLOYER_ONLY_PRIMARY;

ALTER USER SVC_MCP_DEPLOYER ADD PROGRAMMATIC ACCESS TOKEN MCP_SYNC
  ROLE_RESTRICTION = 'MCP_DEPLOYER' DAYS_TO_EXPIRY = 90;
-- Copy the token value once; it goes into the secret on the primary.

-- Ownership note: the recreated server is owned by MCP_DEPLOYER, which can
-- grant USAGE on it to MCP_USER itself (done by the procedure).
-- MCP_DEPLOYER needs no other privileges.


-- ---------------------------------------------------------------------
-- PART C  (run on the PRIMARY once): secret, egress, procedure, task
-- ---------------------------------------------------------------------
USE ROLE ACCOUNTADMIN;
CREATE SCHEMA IF NOT EXISTS MCP_LOCAL.OPS;

CREATE OR REPLACE SECRET MCP_LOCAL.OPS.SECONDARY_PAT
  TYPE = GENERIC_STRING
  SECRET_STRING = '<PAT from part B>';

CREATE OR REPLACE NETWORK RULE MCP_LOCAL.OPS.SECONDARY_SQL_API
  TYPE = HOST_PORT MODE = EGRESS
  VALUE_LIST = ('<org>-<secondary_account>.snowflakecomputing.com:443');

CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION MCP_SYNC_TO_SECONDARY
  ALLOWED_NETWORK_RULES = (MCP_LOCAL.OPS.SECONDARY_SQL_API)
  ALLOWED_AUTHENTICATION_SECRETS = (MCP_LOCAL.OPS.SECONDARY_PAT)
  ENABLED = TRUE;

CREATE OR REPLACE PROCEDURE MCP_LOCAL.OPS.SYNC_MCP_SERVERS_TO_SECONDARY(
    SECONDARY_HOST STRING,          -- '<org>-<secondary_account>.snowflakecomputing.com'
    SOURCE_SCHEMA  STRING           -- 'MCP_LOCAL.MCP'
)
RETURNS VARIANT
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'requests')
HANDLER = 'run'
EXTERNAL_ACCESS_INTEGRATIONS = (MCP_SYNC_TO_SECONDARY)
SECRETS = ('pat' = MCP_LOCAL.OPS.SECONDARY_PAT)
EXECUTE AS OWNER
AS
$$
import json, uuid, requests, _snowflake

def _sql_api(host, token, statement):
    r = requests.post(
        f"https://{host}/api/v2/statements",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        params={"requestId": str(uuid.uuid4())},
        json={"statement": statement, "role": "MCP_DEPLOYER", "timeout": 60},
        timeout=90,
    )
    return r.status_code, r.text[:500]

# How to check that a tool's target exists on the secondary (CREATE MCP SERVER does not check)
CHECK = {
    "CORTEX_AGENT_RUN": "DESCRIBE AGENT {}",
    "CORTEX_SEARCH_SERVICE_QUERY": "DESCRIBE CORTEX SEARCH SERVICE {}",
    "CORTEX_ANALYST_MESSAGE": "DESCRIBE SEMANTIC VIEW {}",
}

def run(session, secondary_host, source_schema):
    token = _snowflake.get_generic_secret_string("pat")
    db, sch = source_schema.split(".")
    servers = session.sql(f"SHOW MCP SERVERS IN SCHEMA {db}.{sch}").collect()
    results, failed = [], False
    for s in servers:
        name = s["name"]
        fqn = f"{db}.{sch}.{name}"
        d = session.sql(f"DESCRIBE MCP SERVER {fqn}").collect()[0].as_dict()
        spec = d.get("server_spec") or d.get("SERVER_SPEC")
        spec_obj = json.loads(spec) if isinstance(spec, str) else spec
        spec_obj.pop("version", None)            # keep only tools etc.

        # 1) Pre-check: every tool target must exist (and be visible) on the secondary
        missing = []
        for t in spec_obj.get("tools", []):
            stmt = CHECK.get(t.get("type"))
            if stmt and t.get("identifier"):
                code, _ = _sql_api(secondary_host, token, stmt.format(t["identifier"]))
                if code != 200:
                    missing.append(t["identifier"])
        if missing:
            failed = True
            results.append({"server": fqn, "status": "SKIPPED", "missing_on_secondary": missing})
            continue

        # 2) Create + grant
        spec_yaml = json.dumps(spec_obj, indent=2)  # JSON is valid YAML
        dq = "$" * 2                                 # a literal double dollar would end this procedure body
        ddl = f"CREATE OR REPLACE MCP SERVER {fqn} FROM SPECIFICATION {dq}\n{spec_yaml}\n{dq}"
        code1, body1 = _sql_api(secondary_host, token, ddl)
        code2, body2 = (_sql_api(secondary_host, token,
                                 f"GRANT USAGE ON MCP SERVER {fqn} TO ROLE MCP_USER")
                        if code1 == 200 else (None, None))
        ok = code1 == 200 and code2 == 200
        failed |= not ok
        results.append({"server": fqn, "status": "OK" if ok else "FAILED",
                        "create": code1, "grant": code2,
                        "error": None if ok else (body1 if code1 != 200 else body2)})

    # 3) Fail loudly so TASK_HISTORY shows FAILED (and an ERROR_INTEGRATION can alert)
    if failed:
        raise Exception("MCP DR sync incomplete: " + json.dumps(results))
    return results
$$;

-- Run once by hand to verify:
-- CALL MCP_LOCAL.OPS.SYNC_MCP_SERVERS_TO_SECONDARY(
--      '<org>-<secondary_account>.snowflakecomputing.com', 'MCP_LOCAL.MCP');

-- Keep the secondary in sync (daily, plus run after every MCP change):
CREATE OR REPLACE TASK MCP_LOCAL.OPS.SYNC_MCP_SERVERS_TASK
  WAREHOUSE = <ops_warehouse>
  SCHEDULE  = 'USING CRON 0 3 * * * Europe/Berlin'
AS
  CALL MCP_LOCAL.OPS.SYNC_MCP_SERVERS_TO_SECONDARY(
       '<org>-<secondary_account>.snowflakecomputing.com', 'MCP_LOCAL.MCP');
ALTER TASK MCP_LOCAL.OPS.SYNC_MCP_SERVERS_TASK RESUME;


-- ---------------------------------------------------------------------
-- PART D  Verify on the SECONDARY
-- ---------------------------------------------------------------------
-- SHOW MCP SERVERS IN SCHEMA MCP_LOCAL.MCP;
-- DESCRIBE MCP SERVER MCP_LOCAL.MCP.RESEARCH;   -- spec matches the primary
-- Langdock keeps the same URL when it uses the Client Redirect connection URL:
--   https://<org>-<connection_name>.snowflakecomputing.com/api/v2/databases/MCP_LOCAL/schemas/MCP/mcp-servers/RESEARCH


-- =====================================================================
-- OPTION B (tested): OAuth client credentials via Entra ID instead of a PAT
--   No long-lived bearer token. Snowflake fetches a ~1h Entra token itself;
--   only the Entra client secret is rotated (Entra policy, central revoke).
-- =====================================================================
-- Entra:
--   * On the Snowflake resource app: app role (type Application)
--       value = 'session:role:MCP_DEPLOYER'
--   * New app "MCP DR Sync" + client secret; assign it the app role
--   * Token claims: sub/oid = sync app's service principal object id,
--                   roles = ['session:role:MCP_DEPLOYER']
--
-- SECONDARY: accept the app token for the service user (no PAT needed)
CREATE SECURITY INTEGRATION ENTRA_MCP_SYNC_APP
  TYPE = EXTERNAL_OAUTH  ENABLED = TRUE  EXTERNAL_OAUTH_TYPE = AZURE
  EXTERNAL_OAUTH_ISSUER = 'https://login.microsoftonline.com/<tenant>/v2.0'
  EXTERNAL_OAUTH_JWS_KEYS_URL = 'https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys'
  EXTERNAL_OAUTH_AUDIENCE_LIST = ('<snowflake-resource-app-id>')
  EXTERNAL_OAUTH_TOKEN_USER_MAPPING_CLAIM = 'sub'
  EXTERNAL_OAUTH_SNOWFLAKE_USER_MAPPING_ATTRIBUTE = 'LOGIN_NAME'
  EXTERNAL_OAUTH_ALLOWED_ROLES_LIST = ('MCP_DEPLOYER')
  EXTERNAL_OAUTH_ANY_ROLE_MODE = 'DISABLE';
ALTER USER SVC_MCP_DEPLOYER SET LOGIN_NAME = '<sync-app-service-principal-object-id>';
-- (keep the user network policy limited to the primary's egress ranges)

-- PRIMARY: Snowflake obtains the token (client credentials)
CREATE SECURITY INTEGRATION ENTRA_MCP_SYNC_CC
  TYPE = API_AUTHENTICATION  AUTH_TYPE = OAUTH2
  OAUTH_CLIENT_ID = '<sync-app-client-id>'
  OAUTH_CLIENT_SECRET = '<sync-app-client-secret>'
  OAUTH_TOKEN_ENDPOINT = 'https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token'
  OAUTH_GRANT = 'CLIENT_CREDENTIALS'
  OAUTH_ALLOWED_SCOPES = ('api://<snowflake-resource-app-id>/.default')
  ENABLED = TRUE;
CREATE OR REPLACE SECRET MCP_LOCAL.OPS.SECONDARY_OAUTH
  TYPE = OAUTH2  API_AUTHENTICATION = ENTRA_MCP_SYNC_CC
  OAUTH_SCOPES = ('api://<snowflake-resource-app-id>/.default');
CREATE OR REPLACE NETWORK RULE MCP_LOCAL.OPS.SECONDARY_SQL_API
  TYPE = HOST_PORT MODE = EGRESS
  VALUE_LIST = ('<org>-<secondary_account>.snowflakecomputing.com:443', 'login.microsoftonline.com:443');
CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION MCP_SYNC_TO_SECONDARY
  ALLOWED_NETWORK_RULES = (MCP_LOCAL.OPS.SECONDARY_SQL_API)
  ALLOWED_API_AUTHENTICATION_INTEGRATIONS = (ENTRA_MCP_SYNC_CC)
  ENABLED = TRUE;
-- In the procedure (Part C), change three lines:
--   SECRETS = ('cred' = MCP_LOCAL.OPS.SECONDARY_OAUTH)
--   token = _snowflake.get_oauth_access_token("cred")
--   "X-Snowflake-Authorization-Token-Type": "OAUTH",
-- Secondary LOGIN_HISTORY then shows FIRST_AUTHENTICATION_FACTOR = OAUTH_ACCESS_TOKEN.
