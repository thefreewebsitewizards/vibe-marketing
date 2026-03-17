#!/bin/bash
# Deploy agent_loop.py to the OpenClaw VPS
# Usage: ./scripts/deploy-agent.sh
#
# Prerequisites:
# - SSH access to the VPS (217.216.90.203)
# - REELBOT_API_KEY in master.env

set -euo pipefail

VPS_HOST="217.216.90.203"
VPS_USER="root"
REMOTE_DIR="/root/reelbot-agent"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Extract secrets from master.env
MASTER_ENV="$HOME/projects/openclaw/.shared-env/master.env"
if [[ ! -f "$MASTER_ENV" ]]; then
    echo "ERROR: master.env not found at $MASTER_ENV"
    exit 1
fi
API_KEY=$(grep "^REELBOT_API_KEY=" "$MASTER_ENV" | cut -d= -f2-)
if [[ -z "$API_KEY" ]]; then
    echo "ERROR: REELBOT_API_KEY not found in master.env"
    exit 1
fi
TG_BOT_TOKEN=$(grep "^TELEGRAM_BOT_TOKEN=" "$MASTER_ENV" | cut -d= -f2- || echo "")
TG_CHAT_ID=$(grep "^TELEGRAM_CHAT_ID=" "$MASTER_ENV" | cut -d= -f2- || echo "")

echo "Deploying agent_loop.py to $VPS_USER@$VPS_HOST..."

# Create remote directory and ensure openclaw user can access it
ssh "$VPS_USER@$VPS_HOST" "mkdir -p $REMOTE_DIR && chown openclaw:openclaw $REMOTE_DIR"

# Copy agent script
scp "$SCRIPT_DIR/agent_loop.py" "$VPS_USER@$VPS_HOST:$REMOTE_DIR/agent_loop.py"
ssh "$VPS_USER@$VPS_HOST" "chown openclaw:openclaw $REMOTE_DIR/agent_loop.py"

# Create .env on VPS
ssh "$VPS_USER@$VPS_HOST" "cat > $REMOTE_DIR/.env << ENVEOF
REELBOT_API_KEY=$API_KEY
REELBOT_URL=https://reelbot.leadneedleai.com
TELEGRAM_BOT_TOKEN=$TG_BOT_TOKEN
TELEGRAM_CHAT_ID=$TG_CHAT_ID
CLAUDE_CMD=/home/openclaw/.npm-global/bin/claude
CLAUDE_TIMEOUT=300
ENVEOF"
ssh "$VPS_USER@$VPS_HOST" "chown openclaw:openclaw $REMOTE_DIR/.env && chmod 600 $REMOTE_DIR/.env"

# Install httpx if not present (handle PEP 668 externally-managed envs)
ssh "$VPS_USER@$VPS_HOST" "python3 -c 'import httpx' 2>/dev/null || apt-get install -y -qq python3-httpx || pip3 install --break-system-packages httpx"

# Install systemd service
scp "$SCRIPT_DIR/reelbot-agent.service" "$VPS_USER@$VPS_HOST:/etc/systemd/system/reelbot-agent.service"
ssh "$VPS_USER@$VPS_HOST" "systemctl daemon-reload && systemctl enable reelbot-agent && systemctl restart reelbot-agent"

echo "Deployed! Checking status..."
ssh "$VPS_USER@$VPS_HOST" "systemctl status reelbot-agent --no-pager -l" || true

echo ""
echo "Commands:"
echo "  ssh $VPS_USER@$VPS_HOST systemctl status reelbot-agent"
echo "  ssh $VPS_USER@$VPS_HOST journalctl -u reelbot-agent -f"
