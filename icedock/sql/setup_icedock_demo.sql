-- Demo backend for Icedock (LDC_*). Entra user -> MCP -> Cortex Agent.
USE ROLE ACCOUNTADMIN;
CREATE ROLE IF NOT EXISTS LDC_MCP_USER;
GRANT ROLE LDC_MCP_USER TO USER KELLER;
CREATE WAREHOUSE IF NOT EXISTS LDC_WH WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 INITIALLY_SUSPENDED = TRUE;
CREATE DATABASE IF NOT EXISTS LDC_DEMO;
CREATE SCHEMA IF NOT EXISTS LDC_DEMO.DATA;
CREATE SCHEMA IF NOT EXISTS LDC_DEMO.MCP;
USE SCHEMA LDC_DEMO.DATA;

CREATE OR REPLACE TABLE USER_FUND_ENTITLEMENT (login_name STRING, fund_id STRING);
INSERT INTO USER_FUND_ENTITLEMENT VALUES ('KELLER','F1');

CREATE OR REPLACE TABLE FUNDS (fund_id STRING, fund_name STRING, department STRING, aum_eur NUMBER);
INSERT INTO FUNDS VALUES ('F1','Alpha Equity','Equity',1000000),('F2','Secret Beta','Fixed Income',2000000);

CREATE OR REPLACE TABLE RESEARCH (doc STRING, fund_id STRING);
INSERT INTO RESEARCH VALUES
 ('Analyst note: Alpha Equity outlook positive, overweight tech.','F1'),
 ('Analyst note: Secret Beta is planning a confidential duration shift.','F2');

CREATE OR REPLACE ROW ACCESS POLICY RAP_FUND AS (f STRING) RETURNS BOOLEAN ->
  EXISTS (SELECT 1 FROM LDC_DEMO.DATA.USER_FUND_ENTITLEMENT e
          WHERE e.login_name = CURRENT_USER() AND e.fund_id = f);
ALTER TABLE FUNDS ADD ROW ACCESS POLICY RAP_FUND ON (fund_id);

CREATE OR REPLACE SEMANTIC VIEW FUNDS_SV
  TABLES (funds AS LDC_DEMO.DATA.FUNDS PRIMARY KEY (fund_id))
  DIMENSIONS (funds.fund_id AS fund_id, funds.fund_name AS fund_name, funds.department AS department)
  METRICS (funds.total_aum AS SUM(aum_eur));

CREATE OR REPLACE CORTEX SEARCH SERVICE RESEARCH_SVC
  ON doc ATTRIBUTES fund_id WAREHOUSE = LDC_WH TARGET_LAG = '1 day'
  AS SELECT doc, fund_id FROM LDC_DEMO.DATA.RESEARCH;

CREATE OR REPLACE AGENT LDC_DEMO.DATA.RESEARCH_AGENT FROM SPECIFICATION $$
models:
  orchestration: auto
instructions:
  response: "Answer briefly. Always list every fund name you found."
tools:
  - tool_spec: {type: cortex_analyst_text_to_sql, name: funds, description: "Fund names, departments and AUM"}
  - tool_spec: {type: cortex_search, name: research, description: "Analyst research notes about funds"}
tool_resources:
  funds:
    semantic_view: LDC_DEMO.DATA.FUNDS_SV
    execution_environment: {type: warehouse, warehouse: LDC_WH}
  research:
    name: LDC_DEMO.DATA.RESEARCH_SVC
    max_results: 5
$$;

CREATE OR REPLACE MCP SERVER LDC_DEMO.MCP.RESEARCH FROM SPECIFICATION $$
tools:
  - title: "Research agent"
    name: "research_agent"
    type: "CORTEX_AGENT_RUN"
    identifier: "LDC_DEMO.DATA.RESEARCH_AGENT"
    description: "Governed fund and research questions (row access applies per user)"
  - title: "Research search (direct)"
    name: "research_search"
    type: "CORTEX_SEARCH_SERVICE_QUERY"
    identifier: "LDC_DEMO.DATA.RESEARCH_SVC"
    description: "Search analyst research notes"
$$;

GRANT DATABASE ROLE SNOWFLAKE.CORTEX_AGENT_USER TO ROLE LDC_MCP_USER;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE LDC_MCP_USER;
GRANT USAGE ON WAREHOUSE LDC_WH TO ROLE LDC_MCP_USER;
GRANT USAGE ON DATABASE LDC_DEMO TO ROLE LDC_MCP_USER;
GRANT USAGE ON SCHEMA LDC_DEMO.DATA TO ROLE LDC_MCP_USER;
GRANT USAGE ON SCHEMA LDC_DEMO.MCP TO ROLE LDC_MCP_USER;
GRANT USAGE ON MCP SERVER LDC_DEMO.MCP.RESEARCH TO ROLE LDC_MCP_USER;
GRANT USAGE ON AGENT LDC_DEMO.DATA.RESEARCH_AGENT TO ROLE LDC_MCP_USER;
GRANT USAGE ON CORTEX SEARCH SERVICE LDC_DEMO.DATA.RESEARCH_SVC TO ROLE LDC_MCP_USER;
GRANT SELECT ON SEMANTIC VIEW LDC_DEMO.DATA.FUNDS_SV TO ROLE LDC_MCP_USER;
GRANT SELECT ON TABLE LDC_DEMO.DATA.FUNDS TO ROLE LDC_MCP_USER;

-- Additive: allow the new role on the existing Entra v2 integration
ALTER SECURITY INTEGRATION ENTRA_SSO_SCOPED_V2 SET EXTERNAL_OAUTH_ALLOWED_ROLES_LIST = ('APP_ANALYST','APP_READER','LDC_MCP_USER');
