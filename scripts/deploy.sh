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

# Push to main (Coolify watches main directly)
echo "Pushing to origin..."
git push origin main

# Trigger Coolify build
echo "Triggering Coolify deploy..."
RESPONSE=$(curl -s -X GET \
    -H "Authorization: Bearer $COOLIFY_TOKEN" \
    "$COOLIFY_URL/api/v1/deploy?uuid=$APP_UUID")

DEPLOY_UUID=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['deployments'][0]['deployment_uuid'])" 2>/dev/null)

if [ -z "$DEPLOY_UUID" ]; then
    echo "ERROR: Failed to get deployment UUID"
    echo "Response: $RESPONSE"
    exit 1
fi

echo "Deploy queued: $DEPLOY_UUID"

# Poll deployment status every 15s, max 10 minutes (40 attempts)
MAX_ATTEMPTS=40
POLL_INTERVAL=15
attempt=0

echo "Polling deployment status..."
while [ "$attempt" -lt "$MAX_ATTEMPTS" ]; do
    attempt=$((attempt + 1))
    sleep "$POLL_INTERVAL"

    STATUS_RESPONSE=$(curl -s -X GET \
        -H "Authorization: Bearer $COOLIFY_TOKEN" \
        "$COOLIFY_URL/api/v1/deployments?filter=$APP_UUID")

    STATUS=$(echo "$STATUS_RESPONSE" | python3 -c "
import json, sys
deployments = json.load(sys.stdin)
for d in deployments:
    if d.get('deployment_uuid') == '$DEPLOY_UUID':
        print(d['status'])
        break
" 2>/dev/null || echo "unknown")

    elapsed=$((attempt * POLL_INTERVAL))
    echo "  [$elapsed s] Status: $STATUS"

    case "$STATUS" in
        finished)
            echo ""
            echo "Deploy SUCCEEDED in ${elapsed}s"

            # Health check
            echo "Checking health endpoint..."
            sleep 5  # brief grace period for container startup
            HEALTH=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 \
                "https://reelbot.leadneedleai.com/health")

            if [ "$HEALTH" = "200" ]; then
                echo "Health check PASSED (HTTP $HEALTH)"
            else
                echo "WARNING: Health check returned HTTP $HEALTH"
                echo "The deploy succeeded but the app may not be ready yet."
                exit 1
            fi
            exit 0
            ;;
        failed)
            echo ""
            echo "Deploy FAILED after ${elapsed}s"
            echo "Check logs at: $COOLIFY_URL"
            exit 1
            ;;
        queued|in_progress)
            # Still working, continue polling
            ;;
        *)
            echo "  Unexpected status: $STATUS (will keep polling)"
            ;;
    esac
done

echo ""
echo "TIMEOUT: Deploy did not finish within $((MAX_ATTEMPTS * POLL_INTERVAL))s"
echo "Last status: $STATUS"
echo "Check manually at: $COOLIFY_URL"
exit 1
