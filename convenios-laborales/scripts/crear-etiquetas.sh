#!/usr/bin/env bash
set -euo pipefail
: "${PAPERLESS_TOKEN:?Cree un token API en Paperless y exporte PAPERLESS_TOKEN}"
BASE=${PAPERLESS_URL:-http://localhost:8000}
for name in convenio-estatal convenio-autonomico convenio-provincial convenio-empresa tabla-salarial revision-salarial vigente derogado; do
  if ! curl -fsS -H "Authorization: Token $PAPERLESS_TOKEN" "$BASE/api/tags/?name=$name" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if any(x["name"]==sys.argv[1] for x in d.get("results",[])) else 1)' "$name"; then
    curl -fsS -X POST "$BASE/api/tags/" -H "Authorization: Token $PAPERLESS_TOKEN" -H 'Content-Type: application/json' -d "$(python3 -c 'import json,sys;print(json.dumps({"name":sys.argv[1]}))' "$name")" >/dev/null
    echo "Creada: $name"
  fi
done
