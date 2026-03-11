#!/usr/bin/env bash
# Deploy reelbot to production via Coolify API
# Usage: ./scripts/deploy.sh
set -euo pipefail

# Load Coolify token from shared env
COOLIFY_TOKEN="${COOLIFY_API_TOKEN:-}"
if [ -z "$COOLIFY_TOKEN" ]; then
    source ~/projects/openclaw/.shared-env/master.env 2>/dev/null || true
    COOLIFY_TOKEN="${COOLIFY_API_TOKEN:-}"
fi

if [ -z "$COOLIFY_TOKEN" ]; then
    echo "ERROR: COOLIFY_API_TOKEN not set"
    echo "Set it in ~/projects/openclaw/.shared-env/master.env"
    exit 1
fi

COOLIFY_URL="https://coolify.leadneedleai.com"
APP_UUID="l0g48c8g4wsskc40co4kssc8"

# Push to deploy branch
echo "Pushing to deploy branch..."
git push origin main:deploy

# Trigger Coolify build
echo "Triggering Coolify deploy..."
RESPONSE=$(curl -s -X GET \
    -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$COOLIFY_URL/api/v1/deploy?uuid=$APP_UUID")

DEPLOY_UUID=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['deployments'][0]['deployment_uuid'])" 2>/dev/null)

if [ -n "$DEPLOY_UUID" ]; then
    echo "Deploy queued: $DEPLOY_UUID"
    echo "Monitor at: $COOLIFY_URL"
else
    echo "Deploy response: $RESPONSE"
fi
