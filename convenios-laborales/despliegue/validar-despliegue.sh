#!/bin/sh
# Validación local del despliegue autónomo (fase 3).
#
# Comprueba lo que se puede comprobar sin arrancar la pila: sintaxis de los scripts, pruebas
# unitarias y, si hay Docker, la validez del manifiesto con `docker compose config`. No arranca
# la pila ni comprueba permisos, modelos o integraciones; esas pruebas requieren Docker real.
#
# Es un script de desarrollo: necesita el repositorio, python3 y, para las pruebas del
# manifiesto, PyYAML (python3 -m pip install pyyaml). Docker es opcional.
set -eu

DESPLIEGUE=$(cd "$(dirname "$0")" && pwd)
RAIZ=$(dirname "$DESPLIEGUE")

sintaxis=1
pruebas=1
docker=1
for opcion in "$@"; do
  case "$opcion" in
    --sin-sintaxis) sintaxis=0 ;;
    --sin-pruebas) pruebas=0 ;;
    --sin-docker) docker=0 ;;
    --ayuda|-h|--help)
      echo "Uso: $0 [--sin-sintaxis] [--sin-pruebas] [--sin-docker]"
      echo "  --sin-sintaxis  no comprueba la sintaxis de los scripts"
      echo "  --sin-pruebas   no ejecuta las pruebas unitarias (útil si ya se ejecutaron)"
      echo "  --sin-docker    no valida el manifiesto con 'docker compose config'"
      exit 0
      ;;
    *)
      echo "Opción no reconocida: $opcion (use --ayuda)" >&2
      exit 2
      ;;
  esac
done

fallos=0

if [ "$sintaxis" = 1 ]; then
  echo "== Sintaxis de los scripts =="
  for fichero in "$DESPLIEGUE"/*.sh "$RAIZ"/scripts/*.sh; do
    [ -e "$fichero" ] || continue
    # Los scripts con shebang de bash se comprueban con bash: no son POSIX.
    interprete='sh'
    case "$(head -n 1 "$fichero")" in
      *bash*) interprete='bash' ;;
    esac
    if ! command -v "$interprete" >/dev/null 2>&1; then
      echo "  omitido (no hay $interprete): ${fichero#"$RAIZ"/}"
    elif "$interprete" -n "$fichero"; then
      echo "  correcto: ${fichero#"$RAIZ"/}"
    else
      echo "  ERROR de sintaxis: $fichero" >&2
      fallos=$((fallos + 1))
    fi
  done
fi

if [ "$pruebas" = 1 ]; then
  echo "== Pruebas unitarias =="
  if ! (cd "$RAIZ" && python3 -m unittest discover -s tests); then
    echo "RECUERDE: las pruebas del manifiesto necesitan PyYAML (python3 -m pip install pyyaml)." >&2
    fallos=$((fallos + 1))
  fi
fi

if [ "$docker" = 1 ]; then
  echo "== Manifiesto de Compose =="
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    # Valores de validación y un prefijo distinto del habitual: `config` comprueba sintaxis e
    # interpolación, pero no descarga ni arranca nada.
    if OPENPACTUM_VERSION=0.0.0-validacion \
       POSTGRES_PASSWORD=validacion \
       PAPERLESS_SECRET_KEY=validacion \
       OPENPACTUM_PREFIJO=validacion \
       docker compose -f "$DESPLIEGUE/compose.yaml" config -q; then
      echo "  manifiesto válido (con prefijo de proyecto 'validacion')"
    else
      echo "  ERROR: el manifiesto no es válido" >&2
      fallos=$((fallos + 1))
    fi
  else
    echo "  Docker no disponible: se omite la validación de Compose (la hace la CI)."
  fi
fi

if [ "$fallos" -gt 0 ]; then
  echo "Validación con $fallos problema(s)." >&2
  exit 1
fi

echo "Validación correcta."
