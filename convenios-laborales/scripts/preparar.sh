#!/usr/bin/env bash
# Prepara .env y los directorios locales. Es idempotente: puede ejecutarse varias veces.
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || cp .env.example .env

# Sustituye los marcadores por secretos aleatorios (solo si siguen presentes) y fija el
# UID/GID del usuario actual; añade las claves que falten en un .env de versiones anteriores.
USUARIO_UID=$(id -u) USUARIO_GID=$(id -g) python3 - <<'PY'
import os
import re
import secrets
from pathlib import Path

p = Path('.env')
s = p.read_text()
for placeholder in ('CAMBIAR_CON_SECRETO_ALEATORIO', 'CAMBIAR_CON_OTRO_SECRETO_ALEATORIO'):
    s = s.replace(placeholder, secrets.token_urlsafe(48))
if os.environ['USUARIO_UID'] != '0':
    for key, value in (('USERMAP_UID', os.environ['USUARIO_UID']), ('USERMAP_GID', os.environ['USUARIO_GID'])):
        if re.search(rf'^{key}=', s, flags=re.M):
            s = re.sub(rf'^{key}=.*$', f'{key}={value}', s, flags=re.M)
        else:
            s = s.rstrip('\n') + f'\n{key}={value}\n'
p.write_text(s)
p.chmod(0o600)
PY

# Con menos de 16 GB de RAM se usa un modelo más ligero, salvo que el usuario haya elegido otro.
if [[ $(awk '/MemTotal:/ {print $2}' /proc/meminfo) -lt 16777216 ]] && grep -q '^MODELO=llama3.1:8b$' .env; then
  sed -i 's/^MODELO=.*/MODELO=qwen2.5:7b/' .env
fi

# Directorios montados en los contenedores: si no existen, Docker los crearía como root.
mkdir -p changedetection anythingllm paperless/consume paperless/export
# AnythingLLM guarda la configuración del asistente en este fichero; debe ser un fichero, no un directorio.
if [[ -d anythingllm/.env ]]; then
  echo "ERROR: anythingllm/.env es un directorio (lo creó Docker). Detenga la pila y elimínelo: rmdir anythingllm/.env" >&2
  exit 1
fi
[[ -e anythingllm/.env ]] || touch anythingllm/.env

echo "Preparado .env (modelo: $(grep '^MODELO=' .env | cut -d= -f2)); revise los secretos antes de arrancar."
