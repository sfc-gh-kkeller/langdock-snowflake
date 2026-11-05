-- Minimal passthrough demo (Entra v2 token -> Snowflake MCP -> Cortex Agent)
USE ROLE ACCOUNTADMIN;
CREATE ROLE IF NOT EXISTS MCP_USER;
GRANT ROLE MCP_USER TO USER <USER_1>;   -- Snowflake user whose LOGIN_NAME = Entra UPN
CREATE WAREHOUSE IF NOT EXISTS MCP_DEMO_WH WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 INITIALLY_SUSPENDED = TRUE;
CREATE DATABASE IF NOT EXISTS MCP_DEMO;
CREATE SCHEMA IF NOT EXISTS MCP_DEMO.DATA;
CREATE SCHEMA IF NOT EXISTS MCP_DEMO.MCP;
USE SCHEMA MCP_DEMO.DATA;

-- Entitlements: <USER_1> may see fund F1 only (add <USER_2> -> F2 for the second-user test)
CREATE OR REPLACE TABLE USER_FUND_ENTITLEMENT (login_name STRING, fund_id STRING);
INSERT INTO USER_FUND_ENTITLEMENT VALUES ('<USER_1>','F1');

CREATE OR REPLACE TABLE FUNDS (fund_id STRING, fund_name STRING, department STRING, aum_eur NUMBER);
INSERT INTO FUNDS VALUES ('F1','Fund Alpha','Equity',1000000),('F2','Fund Beta','Fixed Income',2000000);

CREATE OR REPLACE TABLE RESEARCH (doc STRING, fund_id STRING);
INSERT INTO RESEARCH VALUES
 ('Analyst note: Fund Alpha outlook positive, overweight tech.','F1'),
 ('Analyst note: Fund Beta is planning a confidential duration shift.','F2');

CREATE OR REPLACE ROW ACCESS POLICY RAP_FUND AS (f STRING) RETURNS BOOLEAN ->
  IS_ROLE_IN_SESSION('ACCOUNTADMIN') AND NOT SYS_CONTEXT('SNOWFLAKE$CURRENT','IS_AGENT_ACTIVATED')::BOOLEAN
  OR EXISTS (SELECT 1 FROM MCP_DEMO.DATA.USER_FUND_ENTITLEMENT e
             WHERE e.login_name = CURRENT_USER() AND e.fund_id = f);
ALTER TABLE FUNDS ADD ROW ACCESS POLICY RAP_FUND ON (fund_id);
-- Cortex Search rejects sources whose RAP uses context functions (non-deterministic); RESEARCH stays unprotected


CREATE OR REPLACE SEMANTIC VIEW FUNDS_SV
  TABLES (funds AS MCP_DEMO.DATA.FUNDS PRIMARY KEY (fund_id))
  DIMENSIONS (funds.fund_id AS fund_id, funds.fund_name AS fund_name, funds.department AS department)
  METRICS (funds.total_aum AS SUM(aum_eur));

CREATE OR REPLACE CORTEX SEARCH SERVICE RESEARCH_SVC
  ON doc ATTRIBUTES fund_id WAREHOUSE = MCP_DEMO_WH TARGET_LAG = '1 day'
  AS SELECT doc, fund_id FROM MCP_DEMO.DATA.RESEARCH;

CREATE OR REPLACE AGENT MCP_DEMO.DATA.RESEARCH_AGENT FROM SPECIFICATION $$
models:
  orchestration: auto
instructions:
  response: "Answer briefly. Always list every fund name you found."
tools:
  - tool_spec: {type: cortex_analyst_text_to_sql, name: funds, description: "Fund names, departments and AUM"}
  - tool_spec: {type: cortex_search, name: research, description: "Analyst research notes about funds"}
tool_resources:
  funds:
    semantic_view: MCP_DEMO.DATA.FUNDS_SV
    execution_environment: {type: warehouse, warehouse: MCP_DEMO_WH}
  research:
    name: MCP_DEMO.DATA.RESEARCH_SVC
    max_results: 5
$$;

CREATE OR REPLACE MCP SERVER MCP_DEMO.MCP.RESEARCH FROM SPECIFICATION $$
tools:
  - title: "Research agent"
    name: "research_agent"
    type: "CORTEX_AGENT_RUN"
    identifier: "MCP_DEMO.DATA.RESEARCH_AGENT"
    description: "Governed fund and research questions"
  - title: "Research search (direct)"
    name: "research_search"
    type: "CORTEX_SEARCH_SERVICE_QUERY"
    identifier: "MCP_DEMO.DATA.RESEARCH_SVC"
    description: "Direct search over research notes"
$$;

-- Bind MCP schema to Entra (v2 issuer) and advertise the role scope
ALTER SCHEMA MCP_DEMO.MCP SET OAUTH_AUTHORIZATION_SERVER = ENTRA_MCP_V2
  OAUTH_SCOPES_SUPPORTED = 'session:role:MCP_USER';
ALTER SECURITY INTEGRATION ENTRA_MCP_V2
  SET EXTERNAL_OAUTH_ALLOWED_ROLES_LIST = ('APP_ANALYST','APP_READER','MCP_USER');

-- Least-privileged MCP role
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_AGENT_USER TO ROLE MCP_USER;
GRANT USAGE ON WAREHOUSE MCP_DEMO_WH TO ROLE MCP_USER;
GRANT USAGE ON DATABASE MCP_DEMO TO ROLE MCP_USER;
GRANT USAGE ON SCHEMA MCP_DEMO.DATA TO ROLE MCP_USER;
GRANT USAGE ON SCHEMA MCP_DEMO.MCP TO ROLE MCP_USER;
GRANT USAGE ON MCP SERVER MCP_DEMO.MCP.RESEARCH TO ROLE MCP_USER;
GRANT USAGE ON AGENT MCP_DEMO.DATA.RESEARCH_AGENT TO ROLE MCP_USER;
GRANT USAGE ON CORTEX SEARCH SERVICE MCP_DEMO.DATA.RESEARCH_SVC TO ROLE MCP_USER;
GRANT SELECT ON SEMANTIC VIEW MCP_DEMO.DATA.FUNDS_SV TO ROLE MCP_USER;
GRANT SELECT ON TABLE MCP_DEMO.DATA.FUNDS TO ROLE MCP_USER;
