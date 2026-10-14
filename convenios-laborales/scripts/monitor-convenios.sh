#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f scripts/config-email.env ]]; then
  set -a
  # Archivo local de confianza, protegido con chmod 600.
  source scripts/config-email.env
  set +a
fi
exec flock -n scripts/.monitor.lock python3 scripts/monitor-convenios.py
