#!/bin/sh
# Contenedor de arranque de OpenPactum (fase 4): despliega la pila con un solo comando y sin
# clonar el repositorio.
#
#   docker run --rm -it \
#     -v /var/run/docker.sock:/var/run/docker.sock \
#     -v /var/lib/openpactum:/var/lib/openpactum \
#     ghcr.io/PROPIETARIO/openpactum-arranque:VERSION arriba
#
# AVISO: montar /var/run/docker.sock equivale a dar control total del equipo anfitrión (la
# pila se despliega con el motor de Docker del host). Riesgo asumido y documentado.
#
# Claves del diseño:
# - El directorio de trabajo se monta con la MISMA ruta absoluta en el host y en el contenedor
#   (OPENPACTUM_RAIZ): los montajes del manifiesto se resuelven en el host, así que las rutas
#   tienen que significar lo mismo dentro y fuera.
# - El manifiesto se descarga del repositorio y se verifica contra COMPOSE_SHA256 (fijado al
#   construir la imagen). Sin conexión se reutiliza la copia guardada si sigue cuadrando.
# - Los secretos se preparan antes de arrancar: son un requisito de la configuración de
#   Paperless (dos fases, en un solo comando).
set -eu

RAIZ=${OPENPACTUM_RAIZ:-/var/lib/openpactum}
DESPLIEGUE="$RAIZ/despliegue"
DATOS="$RAIZ/datos"
COMPOSE="$DESPLIEGUE/compose.yaml"
ENTORNO="$DESPLIEGUE/.env"
# Ficheros que la imagen trae dentro (Dockerfile) y que coloca en el directorio del despliegue.
LIB=${OPENPACTUM_LIB:-/usr/local/lib/openpactum}

URL_MANIFIESTO=${OPENPACTUM_URL_MANIFIESTO:-}
SHA_MANIFIESTO=${OPENPACTUM_COMPOSE_SHA256:-}
VERSION=${OPENPACTUM_VERSION:-dev}

ayuda() {
  cat <<'FIN'
Contenedor de arranque de OpenPactum.

Uso: arrancar.sh [ORDEN] [opciones]

Órdenes:
  arriba        (por defecto) descarga el manifiesto, prepara secretos y datos y arranca la pila
  abajo         detiene y retira los contenedores (los volúmenes y los datos se conservan)
  estado        muestra el estado de los servicios
  registros     sigue los registros de la pila (Ctrl+C para salir)
  monitor       ejecuta el monitor del BOE una vez
  actualizar    descarga las imágenes nuevas y vuelve a arrancar
  version       muestra la versión de la imagen de arranque y el hash del manifiesto esperado
  ayuda         esta ayuda

Variables de entorno útiles:
  OPENPACTUM_RAIZ               directorio de trabajo (por defecto /var/lib/openpactum)
  OPENPACTUM_VERSION            etiqueta de la imagen del monitor (por defecto, la de esta imagen)
  USERMAP_UID, USERMAP_GID      usuario del host para Paperless y el monitor (por defecto 1000)

Recuerde montar el socket de Docker y el directorio de trabajo con la misma ruta:
  -v /var/run/docker.sock:/var/run/docker.sock -v /var/lib/openpactum:/var/lib/openpactum
FIN
}

componer() {
  docker compose --project-directory "$DESPLIEGUE" --env-file "$ENTORNO" -f "$COMPOSE" "$@"
}

comprobar_docker() {
  if ! docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
    echo "ERROR: no se puede hablar con el motor de Docker del host." >&2
    echo "Monte el socket: -v /var/run/docker.sock:/var/run/docker.sock" >&2
    exit 1
  fi
}

comprobar_raiz() {
  case "$RAIZ" in
    /*) ;;
    *)
      echo "ERROR: OPENPACTUM_RAIZ tiene que ser una ruta absoluta (es $RAIZ)." >&2
      exit 1
      ;;
  esac
  mkdir -p "$DESPLIEGUE" "$DATOS"
}

verificar_manifiesto() {
  # $1: fichero a comprobar contra el hash fijado en la imagen.
  printf '%s  %s\n' "$SHA_MANIFIESTO" "$1" | sha256sum -c - >/dev/null 2>&1
}

descargar_manifiesto() {
  if [ -z "$SHA_MANIFIESTO" ]; then
    echo "ERROR: esta imagen no tiene fijado COMPOSE_SHA256." >&2
    echo "Defina la variable de repositorio COMPOSE_SHA256 con el hash del manifiesto y vuelva" >&2
    echo "a construir/publicar la imagen de arranque." >&2
    exit 1
  fi
  if [ -z "$URL_MANIFIESTO" ]; then
    echo "ERROR: esta imagen no tiene fijada la URL del manifiesto (OPENPACTUM_URL_MANIFIESTO)." >&2
    exit 1
  fi
  temporal="$COMPOSE.temporal"
  if curl -fsSL --retry 3 -o "$temporal" "$URL_MANIFIESTO"; then
    if verificar_manifiesto "$temporal"; then
      mv "$temporal" "$COMPOSE"
      echo "  manifiesto descargado y verificado ($SHA_MANIFIESTO)"
    else
      rm -f "$temporal"
      echo "ERROR: el manifiesto descargado no coincide con COMPOSE_SHA256." >&2
      echo "Puede ser un cambio del repositorio sin actualizar la variable: no se toca la copia" >&2
      echo "anterior." >&2
      exit 1
    fi
  else
    rm -f "$temporal"
    if [ -f "$COMPOSE" ] && verificar_manifiesto "$COMPOSE"; then
      echo "  aviso: no se pudo descargar el manifiesto; se reutiliza la copia guardada (verificada)"
    else
      echo "ERROR: no se pudo descargar el manifiesto y no hay una copia verificada." >&2
      exit 1
    fi
  fi
}

preparar_ficheros() {
  # Se copian siempre: van fijados a esta imagen y tienen que coincidir con el manifiesto.
  cp "$LIB/secretos-init.sh" "$DESPLIEGUE/secretos-init.sh"
  chmod 0644 "$DESPLIEGUE/secretos-init.sh"
  if [ ! -f "$ENTORNO" ]; then
    cp "$LIB/ejemplo.env" "$ENTORNO"
    # Ajustes dependientes de dónde se despliega; el resto de valores los revisa el usuario.
    sed -i \
      -e "s|^OPENPACTUM_DATOS=.*|OPENPACTUM_DATOS=$DATOS|" \
      -e "s|^OPENPACTUM_DESPLEGUE=.*|OPENPACTUM_DESPLEGUE=$DESPLIEGUE|" \
      -e "s|^OPENPACTUM_VERSION=.*|OPENPACTUM_VERSION=$VERSION|" \
      -e "s|^USERMAP_UID=.*|USERMAP_UID=${USERMAP_UID:-1000}|" \
      -e "s|^USERMAP_GID=.*|USERMAP_GID=${USERMAP_GID:-1000}|" \
      "$ENTORNO"
    chmod 600 "$ENTORNO"
    echo "  creado $ENTORNO a partir del ejemplo de la imagen (revise los valores)"
  else
    echo "  se conserva $ENTORNO (si cambió la imagen, compare sus valores con el ejemplo)"
  fi
}

preparar_todo() {
  comprobar_docker
  comprobar_raiz
  echo "== Manifiesto =="
  descargar_manifiesto
  echo "== Ficheros del despliegue =="
  preparar_ficheros
}

case "${1:-arriba}" in
  arriba)
    preparar_todo
    echo "== Secretos y datos =="
    componer run --rm --no-deps secretos-init
    echo "== Arrancando la pila =="
    componer up -d
    componer ps
    cat <<FIN

Pila arrancada (si algo no responde: $0 registros).
  Changedetection  http://localhost:5000
  Paperless        http://localhost:8000
  AnythingLLM      http://localhost:3001

Quedan pasos manuales (vea convenios-laborales/README.md): administrador de Paperless y sus
etiquetas, asistente inicial y clave API de AnythingLLM, y el SMTP del monitor.
FIN
    ;;
  abajo)
    comprobar_docker
    componer down
    echo "Contenedores retirados. Los volúmenes y los datos siguen en $RAIZ (solo se borran si los borra a mano)."
    ;;
  estado)
    comprobar_docker
    componer ps
    ;;
  registros)
    comprobar_docker
    componer logs --tail=100 --follow
    ;;
  monitor)
    comprobar_docker
    componer run --rm monitor
    ;;
  actualizar)
    preparar_todo
    echo "== Imágenes nuevas =="
    componer pull
    echo "== Reiniciando =="
    componer up -d
    componer ps
    ;;
  version)
    echo "Imagen de arranque: $VERSION"
    echo "Manifiesto esperado (COMPOSE_SHA256): ${SHA_MANIFIESTO:-(sin definir)}"
    echo "Manifiesto: ${URL_MANIFIESTO:-(sin definir)}"
    ;;
  ayuda|--ayuda|-h|--help)
    ayuda
    ;;
  *)
    echo "Orden no reconocida: $1" >&2
    ayuda >&2
    exit 2
    ;;
esac
