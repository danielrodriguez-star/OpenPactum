#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f .env ]] || cp .env.example .env
python3 - <<'PY'
from pathlib import Path
import secrets
p=Path('.env')
s=p.read_text()
for placeholder in ('CAMBIAR_CON_SECRETO_ALEATORIO','CAMBIAR_CON_OTRO_SECRETO_ALEATORIO'):
    s=s.replace(placeholder,secrets.token_urlsafe(48))
p.write_text(s)
p.chmod(0o600)
PY
if [[ $(awk '/MemTotal:/ {print $2}' /proc/meminfo) -lt 16777216 ]]; then
  sed -i 's/^MODELO=.*/MODELO=qwen2.5:7b/' .env
fi
echo "Preparado .env (modelo: $(grep '^MODELO=' .env)); revise los secretos antes de arrancar."
