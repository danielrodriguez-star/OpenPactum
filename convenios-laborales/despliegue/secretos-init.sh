#!/bin/sh
# Secretos del despliegue y preparación del árbol de datos (fase 3).
#
# Se ejecuta como servicio de Compose, una vez por arranque:
#
#   docker compose --env-file .env run --rm --no-deps secretos-init
#
# Genera los secretos que falten en un volumen propio (nunca sobrescribe los existentes),
# los proyecta para los servicios que solo saben leerlos como variables de entorno y deja
# listos los directorios del host con el propietario y los permisos que necesitan los
# contenedores que no corren como root.
#
# Para guardar un secreto que no se puede generar (por ejemplo, la contraseña SMTP):
#
#   printf '%s' 'clave' | docker compose --env-file .env run --rm -T --no-deps secretos-init escribir smtp_password
#
# Rutas (sobreescribibles para las pruebas):
#   OPENPACTUM_SECRETOS_DIR        volumen general de secretos (por defecto /secretos)
#   OPENPACTUM_SECRETOS_ADMIN_DIR  volumen de clave admin      (por defecto /secretos-admin)
#   OPENPACTUM_DATOS_DIR           datos del host               (por defecto /datos)
set -eu

SECRETOS=${OPENPACTUM_SECRETOS_DIR:-/secretos}
SECRETOS_ADMIN=${OPENPACTUM_SECRETOS_ADMIN_DIR:-/secretos-admin}
DATOS=${OPENPACTUM_DATOS_DIR:-/datos}
USUARIO_UID=${USERMAP_UID:-1000}
USUARIO_GID=${USERMAP_GID:-1000}
# Paperless no admite el convenio *_FILE, así que Compose carga este fichero con `env_file`.
PROYECCION="$DATOS/secretos/paperless.env"

soy_root=0
if [ "$(id -u)" = 0 ]; then
  soy_root=1
fi

avisado=0
avisar_sin_root() {
  if [ "$avisado" = 0 ]; then
    echo "  aviso: sin privilegios de root no se ajustan propietarios ni grupos"
    avisado=1
  fi
}

generar() {
  # $1: nombre del fichero. $2 (opcional): directorio del secreto.
  # 48 bytes en base64, sin saltos de línea.
  directorio=${2:-$SECRETOS}
  mkdir -p "$directorio"
  fichero="$directorio/$1"
  if [ -s "$fichero" ]; then
    echo "  conservado: $1"
  else
    umask 027
    head -c 48 /dev/urandom | base64 | tr -d '\n' > "$fichero"
    echo "  generado: $1"
  fi
  chmod 0640 "$fichero"
  if [ "$soy_root" = 1 ]; then
    chgrp "$USUARIO_GID" "$fichero"
  fi
}

escribir() {
  # $1: nombre del fichero. Lee el valor por la entrada estándar y no lo imprime nunca.
  fichero="$SECRETOS/$1"
  umask 027
  cat > "$fichero"
  chmod 0640 "$fichero"
  if [ "$soy_root" = 1 ]; then
    chgrp "$USUARIO_GID" "$fichero"
  fi
  echo "  escrito: $1"
}

proyectar() {
  umask 027
  {
    printf 'PAPERLESS_DBPASS=%s\n' "$(cat "$SECRETOS/postgres_password")"
    printf 'PAPERLESS_SECRET_KEY=%s\n' "$(cat "$SECRETOS/paperless_secret_key")"
  } > "$PROYECCION"
  chmod 0640 "$PROYECCION"
  if [ "$soy_root" = 1 ]; then
    chgrp "$USUARIO_GID" "$PROYECCION"
  else
    avisar_sin_root
  fi
  echo "  proyección para Paperless: $PROYECCION"
}

preparar_datos() {
  mkdir -p "$DATOS/changedetection" "$DATOS/paperless/consume" "$DATOS/paperless/export" \
           "$DATOS/anythingllm" "$DATOS/monitor/estado" "$DATOS/panel"
  if [ "$soy_root" = 1 ]; then
    chown -R "$USUARIO_UID:$USUARIO_GID" "$DATOS/paperless" "$DATOS/anythingllm" \
      "$DATOS/monitor" "$DATOS/panel"
    chmod 0770 "$DATOS/paperless/consume"
  else
    avisar_sin_root
  fi
  # AnythingLLM guarda la configuración del asistente en un fichero, no en un directorio.
  if [ ! -e "$DATOS/anythingllm/.env" ]; then
    : > "$DATOS/anythingllm/.env"
  fi
  if [ "$soy_root" = 1 ]; then
    chown "$USUARIO_UID:$USUARIO_GID" "$DATOS/anythingllm/.env"
  fi
  echo "  datos preparados: $DATOS"
}

case "${1:-generar}" in
  generar)
    mkdir -p "$SECRETOS" "$DATOS/secretos"
    echo "Secretos en $SECRETOS:"
    generar postgres_password
    generar paperless_secret_key
    generar paperless_admin_password "$SECRETOS_ADMIN"
    proyectar
    preparar_datos
    echo "Listo. No se ha impreso ningún secreto."
    ;;
  escribir)
    if [ "$#" -ne 2 ]; then
      echo "Uso: secretos-init.sh escribir NOMBRE (el valor se lee de la entrada estándar)" >&2
      exit 2
    fi
    mkdir -p "$SECRETOS"
    echo "Secretos en $SECRETOS:"
    escribir "$2"
    ;;
  --ayuda|-h|--help)
    echo "Uso: secretos-init.sh [generar|escribir NOMBRE|--ayuda]"
    echo "  generar          (por defecto) crea los secretos que falten, los proyecta y prepara los datos"
    echo "  escribir NOMBRE  guarda en el volumen el valor leído de la entrada estándar"
    ;;
  *)
    echo "Subcomando no reconocido: $1 (use --ayuda)" >&2
    exit 2
    ;;
esac
