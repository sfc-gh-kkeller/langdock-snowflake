#!/usr/bin/env bash
# Finish Entra setup for the Icedock client app and write icedock/.env
set -euo pipefail
CID=${1:?client app id}
SF_APP=818a03b1-77c5-4558-95a3-c6f090f884a1
SCOPE_ID=$(az ad app show --id $SF_APP --query "api.oauth2PermissionScopes[?value=='session:role:LDC_MCP_USER'].id | [0]" -o tsv)
az ad sp show --id $CID -o none 2>/dev/null || az ad sp create --id $CID -o none
az ad app update --id $CID --web-redirect-uris http://localhost:8000/auth/callback http://localhost:8000/api/integrations/callback
az ad app permission add --id $CID --api $SF_APP --api-permissions $SCOPE_ID=Scope -o none
# Graph: openid, profile, email, offline_access
az ad app permission add --id $CID --api 00000003-0000-0000-c000-000000000000 --api-permissions \
  37f7f235-527c-4136-accd-4a02d197296e=Scope 14dad69e-099b-42c9-810b-d002981feec1=Scope \
  64a6cdd6-aab1-4aaf-94b8-3cc8405e90d0=Scope 7427e0e9-2fba-42fe-b0c0-848c9e6a8182=Scope -o none
sleep 15
az ad app permission admin-consent --id $CID
SECRET=$(az ad app credential reset --id $CID --display-name local --years 1 --query password -o tsv)
cd "$(dirname "$0")/.."
umask 077
cat > .env <<EOF
ENTRA_TENANT_ID=b3b06c45-b6f1-4d13-a720-8845b509b948
ENTRA_CLIENT_ID=$CID
ENTRA_CLIENT_SECRET=$SECRET
SNOWFLAKE_APP_ID=$SF_APP
SNOWFLAKE_ACCOUNT_URL=https://sfsenorthamerica-secfieldkeller.snowflakecomputing.com
SF_ROLE=LDC_MCP_USER
MCP_URL=https://sfsenorthamerica-secfieldkeller.snowflakecomputing.com/api/v2/databases/LDC_DEMO/schemas/MCP/mcp-servers/RESEARCH
APP_BASE_URL=http://localhost:8000
SESSION_SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')
EOF
echo "wrote .env for $CID"
