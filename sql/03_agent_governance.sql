-- =====================================================================
-- Cortex Agent governance: inventory, sensitive data, usage, error rates
-- Run as a role with ACCOUNT_USAGE access and MONITOR/USAGE on the agents
-- (tested on a live account; see README "Agent governance").
-- =====================================================================

-- 1. Inventory: every agent in the account (owner, created, comment)
SHOW AGENTS IN ACCOUNT;
SELECT "database_name" AS db, "schema_name" AS sch, "name" AS agent, "owner", "created_on", "comment"
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
-- MCP servers (how agents are exposed to external platforms such as Langdock)
SHOW MCP SERVERS IN ACCOUNT;

-- 2. Which agents touched which objects and columns, for which users,
--    under which policies, and whether a column is tagged sensitive.
--    ACCESS_HISTORY / TAG_REFERENCES (ACCOUNT_USAGE) have latency (up to ~3 h).
WITH agent_access AS (
  SELECT ah.query_id, ah.query_start_time, ah.user_name,
         a.value:agentName::string           AS agent,
         ARRAY_CONTAINS('EXTERNAL_AGENT'::variant,
           TRANSFORM(ah.agents_info, x -> x:agentType)) AS via_external_client,
         o.value:objectName::string          AS object_name,
         c.value:columnName::string          AS column_name,
         ah.policies_referenced
  FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah,
       LATERAL FLATTEN(ah.agents_info) a,
       LATERAL FLATTEN(ah.base_objects_accessed) o,
       LATERAL FLATTEN(o.value:columns, OUTER => TRUE) c
  WHERE ah.query_start_time > DATEADD(day, -30, CURRENT_TIMESTAMP())
    AND a.value:agentType::string = 'CORTEX_AGENT'
)
SELECT aa.agent, aa.object_name, aa.column_name,
       t.tag_name, t.tag_value,
       COUNT(DISTINCT aa.query_id)  AS queries,
       COUNT(DISTINCT aa.user_name) AS users,
       BOOLOR_AGG(aa.via_external_client) AS via_external_client,
       BOOLOR_AGG(ARRAY_SIZE(aa.policies_referenced) > 0) AS policy_applied
FROM agent_access aa
LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.TAG_REFERENCES t
  ON t.domain = 'COLUMN'
 AND t.object_database || '.' || t.object_schema || '.' || t.object_name = aa.object_name
 AND t.column_name = aa.column_name
 -- AND t.tag_name IN ('SENSITIVITY', 'SEMANTIC_CATEGORY', 'PRIVACY_CATEGORY')
GROUP BY ALL
ORDER BY agent, object_name, column_name;

-- 2b. Live variant for one table (no TAG_REFERENCES latency), tested:
--     agent reads of CLIENTS joined to its column tags
--     -> IBAN / CLIENT_NAME = CONFIDENTIAL, SEGMENT = PUBLIC, CLIENT_ID untagged
WITH tags AS (
  SELECT '<DB>.<SCHEMA>.' || object_name AS object_name, column_name, tag_name, tag_value
  FROM TABLE(<DB>.INFORMATION_SCHEMA.TAG_REFERENCES_ALL_COLUMNS('<DB>.<SCHEMA>.<TABLE>', 'table'))
), reads AS (
  SELECT ah.query_id, ah.query_start_time,
         a.value:agentName::string  AS agent,
         o.value:objectName::string AS object_name,
         c.value:columnName::string AS column_name
  FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY ah,
       LATERAL FLATTEN(ah.agents_info) a,
       LATERAL FLATTEN(ah.base_objects_accessed) o,
       LATERAL FLATTEN(o.value:columns) c
  WHERE ah.query_start_time > DATEADD(day, -7, CURRENT_TIMESTAMP())
    AND a.value:agentType::string = 'CORTEX_AGENT'
    AND o.value:objectName::string = '<DB>.<SCHEMA>.<TABLE>'
)
SELECT r.agent, r.column_name, t.tag_name, t.tag_value,
       COUNT(DISTINCT r.query_id) AS queries, MAX(r.query_start_time) AS last_read
FROM reads r LEFT JOIN tags t USING (object_name, column_name)
GROUP BY ALL ORDER BY r.column_name;

-- 3. Usage and error rate per agent, from agent traces (all requests,
--    including failures that never reach SQL, e.g. a missing tool target).
--    A request can report status SUCCESS while a tool failed: the failure
--    is recorded in agent.warnings (e.g. code 399569 TOOL_NOT_ACCESSIBLE).
WITH req AS (
  SELECT record_attributes:"snow.ai.observability.database.name"::string || '.' ||
         record_attributes:"snow.ai.observability.schema.name"::string   || '.' ||
         record_attributes:"snow.ai.observability.object.name"::string    AS agent,
         timestamp,
         record_attributes:"snow.ai.observability.agent.status"::string   AS status,
         TRY_PARSE_JSON(record_attributes:"snow.ai.observability.agent.warnings"::string) AS warnings,
         record_attributes:"snow.ai.observability.agent.duration"::number AS duration_ms,
         resource_attributes:"snow.user.name"::string                     AS user_name
  FROM SNOWFLAKE.LOCAL.AI_OBSERVABILITY_EVENTS
  WHERE record_type = 'SPAN'
    AND record:name::string = 'AgentV2RequestResponseInfo'
    AND timestamp > DATEADD(day, -30, CURRENT_TIMESTAMP())
)
SELECT agent,
       COUNT(*)                                             AS requests,
       COUNT(DISTINCT user_name)                            AS users,
       COUNT_IF(status <> 'SUCCESS')                        AS failed_requests,
       COUNT_IF(status = 'SUCCESS' AND ARRAY_SIZE(warnings) > 0) AS requests_with_tool_errors,
       ROUND(COUNT_IF(status <> 'SUCCESS' OR ARRAY_SIZE(warnings) > 0) / COUNT(*) * 100, 1) AS error_rate_pct,
       ROUND(APPROX_PERCENTILE(duration_ms, 0.95))          AS p95_ms,
       MAX(timestamp)                                       AS last_used
FROM req
GROUP BY agent
ORDER BY error_rate_pct DESC;

-- 3b. Error breakdown per agent and error code
SELECT record_attributes:"snow.ai.observability.object.name"::string AS agent,
       w.value:code::string AS code,
       SPLIT_PART(w.value:message::string, ':', 1) AS error,
       COUNT(*) AS n
FROM SNOWFLAKE.LOCAL.AI_OBSERVABILITY_EVENTS,
     LATERAL FLATTEN(TRY_PARSE_JSON(record_attributes:"snow.ai.observability.agent.warnings"::string)) w
WHERE record_type = 'SPAN'
  AND record:name::string = 'AgentV2RequestResponseInfo'
  AND timestamp > DATEADD(day, -30, CURRENT_TIMESTAMP())
GROUP BY ALL ORDER BY n DESC;

-- 4. SQL issued by agents: volume and failed statements per user / role
SELECT DATE_TRUNC(day, start_time) AS day, user_name, role_name,
       COUNT(*) AS agent_queries,
       COUNT_IF(execution_status <> 'SUCCESS') AS failed
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE agent_type = 'CORTEX_AGENT'
  AND start_time > DATEADD(day, -30, CURRENT_TIMESTAMP())
GROUP BY ALL ORDER BY day DESC, agent_queries DESC;
