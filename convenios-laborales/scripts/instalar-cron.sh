#!/usr/bin/env bash
set -euo pipefail
SCRIPT=$(realpath "$(dirname "$0")/monitor-convenios.sh")
ENTRY="0 */6 * * * $SCRIPT >> $(dirname "$SCRIPT")/monitor.log 2>&1"
{ crontab -l 2>/dev/null | grep -Fv "$SCRIPT" || true; echo "$ENTRY"; } | crontab -
echo "Cron instalado: $ENTRY"
