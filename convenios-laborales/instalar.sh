#!/usr/bin/env bash
# Instalador de OpenPactum (convenios-laborales) para Debian y Ubuntu.
#
# Instala las dependencias del sistema y Docker Engine + Compose v2 (repositorio oficial
# de Docker), prepara .env y los directorios, arranca la pila, espera a que responda,
# crea el administrador y las etiquetas de Paperless, descarga los modelos e instala el cron.
# Es idempotente: puede volver a ejecutarse para completar o reparar una instalación.
set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
cd "$DIR"

ARRANCAR=1
CRON=1
ESPERAR_MODELOS=1

uso() {
  cat <<'EOF'
Uso: ./instalar.sh [opciones]

Ejecútelo con su usuario normal (no como root ni con sudo); pedirá la contraseña de
sudo cuando la necesite.

Opciones:
  --sin-arrancar         Solo instala dependencias y prepara la configuración; no arranca la pila.
  --sin-cron             No instala la tarea programada del monitor del BOE.
  --no-esperar-modelos   No espera a que termine la descarga de los modelos de Ollama.
  -h, --ayuda            Muestra esta ayuda.

Variables opcionales:
  PAPERLESS_ADMIN_USER   Nombre del administrador de Paperless que se crea (por defecto: admin).
  DOCKER_DISTRO, DOCKER_CODENAME
                         Fuerzan el repositorio de Docker (p. ej. debian bookworm) en
                         distribuciones derivadas que no se detectan automáticamente.
EOF
}

while (($#)); do
  case "$1" in
    --sin-arrancar) ARRANCAR=0 ;;
    --sin-cron) CRON=0 ;;
    --no-esperar-modelos) ESPERAR_MODELOS=0 ;;
    -h | --ayuda) uso; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; uso >&2; exit 2 ;;
  esac
  shift
done

# --- Utilidades ---------------------------------------------------------------
if [[ -t 1 ]]; then N=$'\e[1m'; V=$'\e[32m'; A=$'\e[33m'; R=$'\e[31m'; F=$'\e[0m'; else N=''; V=''; A=''; R=''; F=''; fi
paso() { printf '\n%s==> %s%s\n' "$N" "$*" "$F"; }
ok() { printf '%s  ✔ %s%s\n' "$V" "$*" "$F"; }
aviso() { printf '%s  ! %s%s\n' "$A" "$*" "$F" >&2; }
fallo() { printf '%sERROR: %s%s\n' "$R" "$*" "$F" >&2; exit 1; }
FALLOS=()
registrar_fallo() { aviso "$1"; FALLOS+=("$1"); }

activar_servicio() {
  if [[ -d /run/systemd/system ]]; then
    sudo systemctl enable --now "$1" >/dev/null
  else
    aviso "Sin systemd: se inicia $1 con 'service', pero no arrancará solo al reiniciar."
    sudo service "$1" start >/dev/null
  fi
}

# --- Comprobaciones previas -----------------------------------------------------
paso "Comprobando el sistema"
[[ $(uname -s) == Linux ]] || fallo "Este instalador es para Linux (Debian/Ubuntu). En Windows/macOS siga el README."
if [[ $EUID -eq 0 ]]; then
  fallo "No lo ejecute como root${SUDO_USER:+ ni con sudo}. Use su usuario normal: ./instalar.sh"
fi
command -v sudo >/dev/null || fallo "Falta sudo. Instálelo como root (apt-get install sudo) y añada su usuario al grupo sudo."
if ! command -v apt-get >/dev/null || ! command -v dpkg >/dev/null; then
  fallo "Distribución no compatible: se necesita apt (Debian/Ubuntu). Instale a mano Docker Engine + Compose v2, python3, curl, cron, flock (util-linux) y poppler-utils, y ejecute ./instalar.sh de nuevo."
fi
[[ -r /etc/os-release ]] || fallo "No se encuentra /etc/os-release."
# shellcheck disable=SC1091
. /etc/os-release
ARQ=$(dpkg --print-architecture)
case "$ARQ" in
  amd64 | arm64) ;;
  *) fallo "Arquitectura $ARQ no compatible con las imágenes de Ollama/AnythingLLM (se necesita amd64 o arm64)." ;;
esac
ok "${PRETTY_NAME:-$ID} ($ARQ)"

echo "  Se pedirá la contraseña de sudo para instalar paquetes y servicios."
sudo -v || fallo "No se pudo obtener permiso de sudo."
# Mantiene vivo el permiso de sudo durante las esperas largas (descarga de imágenes y modelos).
( while kill -0 "$$" 2>/dev/null; do sudo -n true 2>/dev/null; sleep 50; done ) >/dev/null 2>&1 &
SUDO_KEEPALIVE=$!
trap 'kill "$SUDO_KEEPALIVE" 2>/dev/null || true' EXIT

RAM_KB=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
RAM_GB=$((RAM_KB / 1024 / 1024))
if ((RAM_KB < 8 * 1024 * 1024)); then
  aviso "RAM: ${RAM_GB} GB. Con menos de 8 GB los modelos de lenguaje pueden no funcionar o ir muy lentos."
else
  ok "RAM: ${RAM_GB} GB"
fi
# Espacio libre donde Docker guarda imágenes y volúmenes (o /var si aún no existe).
DOCKER_RAIZ=/var/lib/docker; [[ -d $DOCKER_RAIZ ]] || DOCKER_RAIZ=/var
LIBRE_GB=$(($(df -Pk "$DOCKER_RAIZ" | awk 'NR==2 {print $4}') / 1024 / 1024))
if ((LIBRE_GB < 30)); then
  aviso "Espacio libre en $DOCKER_RAIZ: ${LIBRE_GB} GB. Imágenes y modelos ocupan unos 20 GB; se recomiendan al menos 30 GB."
else
  ok "Espacio libre en $DOCKER_RAIZ: ${LIBRE_GB} GB"
fi

# --- Paquetes del sistema --------------------------------------------------------
paso "Instalando dependencias del sistema"
sudo apt-get update -q
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
  ca-certificates curl gnupg python3 cron util-linux poppler-utils
for cmd in curl python3 flock crontab pdftotext; do
  command -v "$cmd" >/dev/null || fallo "No se encuentra '$cmd' tras instalar los paquetes."
done
activar_servicio cron
ok "python3, curl, cron, flock y pdftotext disponibles; servicio cron activo"

# --- Docker Engine + Compose v2 ----------------------------------------------------
paso "Comprobando Docker"
instalar_repo_docker() {
  local distro=${DOCKER_DISTRO:-} codename=${DOCKER_CODENAME:-}
  if [[ -z $distro ]]; then
    if [[ $ID == ubuntu || " ${ID_LIKE:-} " == *" ubuntu "* ]]; then
      distro=ubuntu; codename=${codename:-${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}}
    elif [[ $ID == debian ]]; then
      distro=debian; codename=${codename:-${VERSION_CODENAME:-}}
    else
      fallo "No se reconoce la distribución '$ID' para el repositorio de Docker. Indique la base, por ejemplo: DOCKER_DISTRO=debian DOCKER_CODENAME=bookworm ./instalar.sh"
    fi
  fi
  [[ -n $codename ]] || fallo "No se pudo determinar la versión de $distro. Use DOCKER_CODENAME=..."
  echo "  Configurando el repositorio oficial de Docker ($distro $codename)"
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL "https://download.docker.com/linux/$distro/gpg" -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  printf 'Types: deb\nURIs: https://download.docker.com/linux/%s\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' \
    "$distro" "$codename" "$ARQ" | sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null
  sudo apt-get update -q
}

if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  ok "Docker ya instalado ($(docker --version | cut -d, -f1)); se reutiliza"
elif command -v docker >/dev/null; then
  if dpkg -s docker-ce >/dev/null 2>&1; then
    echo "  Docker CE sin el plugin Compose v2: se instala docker-compose-plugin"
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q docker-compose-plugin
  else
    fallo "Hay un Docker instalado sin Compose v2 (probablemente el paquete docker.io de la distribución).
  Instale el plugin Compose v2 o sustitúyalo por Docker CE siguiendo https://docs.docker.com/engine/install/
  (los contenedores e imágenes existentes podrían perderse al cambiar de paquete) y ejecute ./instalar.sh de nuevo."
  fi
else
  CONFLICTOS=$(dpkg-query -W -f='${db:Status-Abbrev} ${Package}\n' docker.io docker-compose docker-doc podman-docker containerd runc 2>/dev/null | awk '$1 ~ /^ii/ {print $2}' | paste -sd' ' - || true)
  if [[ -n $CONFLICTOS ]]; then
    fallo "Paquetes incompatibles con Docker CE instalados: $CONFLICTOS
  Revíselos y desinstálelos si no los necesita (sudo apt-get remove $CONFLICTOS) y ejecute ./instalar.sh de nuevo."
  fi
  instalar_repo_docker
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  ok "Docker Engine y Compose v2 instalados"
fi
activar_servicio docker

USUARIO=$(id -un)
if ! id -nG "$USUARIO" | tr ' ' '\n' | grep -qx docker; then
  sudo usermod -aG docker "$USUARIO"
  aviso "Se ha añadido '$USUARIO' al grupo docker: cierre sesión y vuelva a entrar para usar 'docker' sin sudo."
fi
# En esta sesión el grupo nuevo aún no aplica: se usa sudo si hace falta.
if docker info >/dev/null 2>&1; then DOCKER=(docker); else DOCKER=(sudo docker); fi
"${DOCKER[@]}" info >/dev/null 2>&1 || fallo "El servicio Docker no responde. Revise: sudo systemctl status docker"
compose() { "${DOCKER[@]}" compose "$@"; }
VERSION_COMPOSE=$(compose version --short 2>/dev/null || echo 0)
[[ ${VERSION_COMPOSE#v} =~ ^([2-9]|[1-9][0-9]+)\. ]] || fallo "Se necesita Docker Compose v2 o superior (detectado: $VERSION_COMPOSE)."
ok "Docker $("${DOCKER[@]}" version --format '{{.Server.Version}}') y Compose ${VERSION_COMPOSE#v} funcionando"

# --- Configuración ---------------------------------------------------------------
paso "Preparando la configuración"
./scripts/preparar.sh
if [[ $(id -u) != 1000 ]]; then
  # La imagen de AnythingLLM escribe con UID 1000; sin esto no podría guardar datos.
  sudo chown -R 1000:1000 anythingllm
  aviso "anythingllm/ pasa a pertenecer al UID 1000 (usuario del contenedor); para copiarlo use sudo."
fi
if [[ ! -f scripts/config-email.env ]]; then
  cp scripts/config-email.env.example scripts/config-email.env
  chmod 600 scripts/config-email.env
  ok "Creado scripts/config-email.env (vacío: rellénelo para recibir avisos por correo)"
fi
[[ -f scripts/convenios.txt ]] || cp scripts/convenios.txt.example scripts/convenios.txt
compose config -q || fallo "docker-compose.yml o .env no son válidos (ver mensaje anterior)."
ok "Configuración válida"

if ((ARRANCAR == 0)); then
  paso "Dependencias instaladas y configuración preparada (--sin-arrancar)"
  echo "  Para arrancar: ./instalar.sh  (o: docker compose up -d)"
  exit 0
fi

# --- Arranque --------------------------------------------------------------------
paso "Descargando imágenes (varios GB; puede tardar)"
compose pull
paso "Arrancando la pila"
compose up -d
ok "Contenedores iniciados"

esperar_http() { # nombre url segundos
  local nombre=$1 url=$2 limite=$3 inicio codigo
  inicio=$SECONDS
  printf '  Esperando a %s' "$nombre"
  while ((SECONDS - inicio < limite)); do
    codigo=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" || true)
    if [[ $codigo =~ ^(2..|3..|401|403)$ ]]; then
      printf '\n'; ok "$nombre responde en $url"; return 0
    fi
    printf '.'; sleep 5
  done
  printf '\n'
  registrar_fallo "$nombre no responde en $url tras ${limite}s. Revise: docker compose logs --tail=100"
  return 1
}

paso "Comprobando servicios"
esperar_http Changedetection http://127.0.0.1:5000/ 300 || true
# El primer arranque de Paperless aplica las migraciones de la base de datos: puede tardar varios minutos.
PAPERLESS_OK=0
esperar_http Paperless http://127.0.0.1:8000/api/ 900 && PAPERLESS_OK=1
esperar_http AnythingLLM http://127.0.0.1:3001/api/ping 300 || true

# --- Paperless: administrador y etiquetas ------------------------------------------
CREDENCIALES=credenciales.txt
if ((PAPERLESS_OK)); then
  paso "Configurando Paperless (administrador y etiquetas)"
  ADMIN=${PAPERLESS_ADMIN_USER:-admin}
  CLAVE=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
  # Usuario y contraseña viajan por la entrada estándar, no como argumentos visibles en 'ps'.
  CODIGO='
import sys
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
nombre, clave = sys.stdin.read().split("\n")[:2]
u = User.objects.filter(username=nombre).first()
estado = "existente"
if u is None:
    u = User.objects.create_superuser(nombre, "", clave)
    estado = "creado"
token, _ = Token.objects.get_or_create(user=u)
print("ESTADO=" + estado)
print("TOKEN=" + token.key)
'
  ERRORES=$(mktemp)
  if SALIDA=$(printf '%s\n%s\n' "$ADMIN" "$CLAVE" | compose exec -T -u paperless paperless python3 manage.py shell -c "$CODIGO" 2>"$ERRORES") \
    && grep -q '^TOKEN=' <<<"$SALIDA"; then
    ESTADO=$(sed -n 's/^ESTADO=//p' <<<"$SALIDA")
    TOKEN=$(sed -n 's/^TOKEN=//p' <<<"$SALIDA")
    if [[ $ESTADO == creado ]]; then
      (umask 077; printf 'Paperless (http://localhost:8000)\nusuario: %s\ncontraseña: %s\n' "$ADMIN" "$CLAVE" >"$CREDENCIALES")
      ok "Administrador '$ADMIN' creado; credenciales en $DIR/$CREDENCIALES (cámbiela tras el primer acceso)"
    else
      ok "El administrador '$ADMIN' ya existía; no se ha cambiado su contraseña"
    fi
    if [[ $TOKEN =~ ^[0-9a-f]{40}$ ]] && PAPERLESS_TOKEN=$TOKEN PAPERLESS_URL=http://127.0.0.1:8000 ./scripts/crear-etiquetas.sh; then
      ok "Etiquetas de Paperless creadas o ya presentes"
    else
      registrar_fallo "No se pudieron crear las etiquetas de Paperless (ejecute luego scripts/crear-etiquetas.sh)."
    fi
  else
    tail -n 5 "$ERRORES" >&2
    registrar_fallo "No se pudo crear el administrador de Paperless. Hágalo a mano: docker compose exec paperless python manage.py createsuperuser"
  fi
  rm -f "$ERRORES"
fi
unset CLAVE TOKEN SALIDA

# --- Modelos de Ollama -------------------------------------------------------------
MODELO=$(sed -n 's/^MODELO=//p' .env)
if ((ESPERAR_MODELOS)); then
  paso "Descargando modelos de Ollama ($MODELO y nomic-embed-text; varios GB)"
  echo "  Progreso en otra terminal: docker compose logs -f modelos"
  ID_MODELOS=$(compose ps -aq modelos || true)
  if [[ -n $ID_MODELOS ]] && [[ $("${DOCKER[@]}" wait "$ID_MODELOS") == 0 ]]; then
    LISTA=$(compose exec -T ollama ollama list 2>/dev/null | awk 'NR>1 {print $1}' || true)
    [[ $MODELO == *:* ]] && ETIQUETA_MODELO=$MODELO || ETIQUETA_MODELO=$MODELO:latest
    if grep -qxF "$ETIQUETA_MODELO" <<<"$LISTA" && grep -qxF nomic-embed-text:latest <<<"$LISTA"; then
      ok "Modelos disponibles en Ollama"
    else
      registrar_fallo "La descarga terminó pero Ollama no lista los modelos. Revise: docker compose logs modelos"
    fi
  else
    registrar_fallo "Falló la descarga de modelos. Revise: docker compose logs modelos; para reintentar: docker compose up -d modelos"
  fi
else
  aviso "No se espera a los modelos; compruebe el final con: docker compose logs -f modelos"
fi

# --- Monitor del BOE (cron) ---------------------------------------------------------
if ((CRON)); then
  paso "Instalando la tarea programada del monitor del BOE"
  ./scripts/instalar-cron.sh
  if ! grep -qE '^SMTP_HOST=.+' scripts/config-email.env; then
    aviso "SMTP sin configurar: el monitor descargará los PDF a Paperless pero solo registrará las novedades en scripts/monitor.log, sin correo. Rellene scripts/config-email.env para recibir avisos."
  fi
fi

# --- Resumen ------------------------------------------------------------------------
paso "Resumen"
cat <<EOF
  Changedetection: http://localhost:5000
  Paperless:       http://localhost:8000   (credenciales: $( [[ -f $CREDENCIALES ]] && echo "$DIR/$CREDENCIALES" || echo "las de su administrador"))
  AnythingLLM:     http://localhost:3001
  Modelo:          $MODELO

  Pasos que requieren su intervención (detalles en README.md):
   1. AnythingLLM: complete el asistente inicial (Ollama ya preconfigurado), cree una clave API en
      Ajustes → Developer API, edite scripts/convenios.txt y ejecute:
      ANYTHINGLLM_API_KEY='...' ./scripts/crear-workspaces.sh
   2. Changedetection: añada las URL de scripts/fuentes-rss.txt y de sus boletines provinciales
      y configure las notificaciones por correo.
   3. Correo del monitor del BOE: rellene scripts/config-email.env (chmod 600 ya aplicado).
EOF

if ((${#FALLOS[@]})); then
  printf '\n%sLa instalación ha terminado con %d problema(s):%s\n' "$R" "${#FALLOS[@]}" "$F" >&2
  printf '  - %s\n' "${FALLOS[@]}" >&2
  echo "Corrija lo indicado y vuelva a ejecutar ./instalar.sh (es seguro repetirlo)." >&2
  exit 1
fi
printf '\n%sInstalación completada.%s\n' "$V" "$F"
