#!/bin/bash
# Daily backup of ReelBot plans data from Docker volume
# Run via cron on the Coolify VPS (root@76.13.29.110)
#
# Crontab entry:
#   0 3 * * * /opt/reelbot-backup/backup-plans.sh

set -euo pipefail

BACKUP_DIR="/opt/reelbot-backups"
CONTAINER_PATTERN="l0g48c8g4wsskc40co4kssc8"
MAX_BACKUPS=14  # Keep 2 weeks

mkdir -p "$BACKUP_DIR"

# Find the running container
CONTAINER=$(docker ps --format '{{.Names}}' | grep "$CONTAINER_PATTERN" | head -1)
if [ -z "$CONTAINER" ]; then
    echo "ERROR: No running container matching $CONTAINER_PATTERN"
    exit 1
fi

# Create timestamped backup
DATE=$(date +%Y-%m-%d_%H%M)
BACKUP_FILE="$BACKUP_DIR/plans_${DATE}.tar.gz"

# Copy plans from container and compress
docker cp "$CONTAINER:/app/plans" - | gzip > "$BACKUP_FILE"

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup created: $BACKUP_FILE ($SIZE)"

# Rotate old backups (keep MAX_BACKUPS most recent)
cd "$BACKUP_DIR"
ls -1t plans_*.tar.gz 2>/dev/null | tail -n +$((MAX_BACKUPS + 1)) | xargs -r rm -v

echo "Backup complete. $(ls -1 plans_*.tar.gz | wc -l) backups retained."
