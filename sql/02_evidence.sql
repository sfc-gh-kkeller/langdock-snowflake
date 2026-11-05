-- Evidence after the Langdock tests: identity, role, IP, agent attribution, policies
-- Who ran which agent query, with which role
SELECT user_name, role_name, start_time, agent_type, LEFT(query_text, 80) AS q
FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
       END_TIME_RANGE_START => DATEADD('hour', -2, CURRENT_TIMESTAMP()), RESULT_LIMIT => 10000))
WHERE role_name = 'MCP_USER'
ORDER BY start_time DESC;

-- Sign-ins with the Entra token, and from which IP (Langdock egress)
SELECT user_name, event_timestamp, client_ip, first_authentication_factor, is_success, error_message
FROM TABLE(INFORMATION_SCHEMA.LOGIN_HISTORY(DATEADD('hour', -2, CURRENT_TIMESTAMP()), CURRENT_TIMESTAMP()))
WHERE first_authentication_factor = 'OAUTH_ACCESS_TOKEN'
ORDER BY event_timestamp DESC;

-- Data accessed, agent attribution and row access policy (ACCOUNT_USAGE has latency)
SELECT query_start_time, user_name, agents_info, direct_objects_accessed, policies_referenced
FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY
WHERE query_start_time > DATEADD('day', -1, CURRENT_TIMESTAMP())
  AND agents_info IS NOT NULL
ORDER BY query_start_time DESC;
