#!/usr/bin/env bash
set -euo pipefail
: "${ANYTHINGLLM_API_KEY:?Genere una clave API en AnythingLLM y exporte ANYTHINGLLM_API_KEY}"
BASE=${ANYTHINGLLM_URL:-http://localhost:3001}
LISTA=${1:-"$(dirname "$0")/convenios.txt"}
[[ -f "$LISTA" ]] || { echo "Copie convenios.txt.example a convenios.txt" >&2; exit 1; }
while IFS= read -r name || [[ -n "$name" ]]; do
  [[ -z "$name" || "$name" == \#* ]] && continue
  payload=$(python3 -c 'import json,sys;print(json.dumps({"name":sys.argv[1]}))' "$name")
  curl -fsS -X POST "$BASE/api/v1/workspace/new" -H "Authorization: Bearer $ANYTHINGLLM_API_KEY" -H 'Content-Type: application/json' -d "$payload" || echo "No se pudo crear: $name" >&2
  echo
done < "$LISTA"
