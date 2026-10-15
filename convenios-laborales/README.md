# Convenios laborales — instalación local

**Estado:** el instalador y la configuración se han validado sin Docker (sintaxis, `shellcheck`, esquema de Compose y simulación del instalador); **no se han probado todavía en una máquina con Docker**. No se garantiza cumplimiento RGPD por instalar software: evalúe además acceso, copias, retención y proveedor SMTP.

## Dos formas de instalar

- **Despliegue autónomo (fases 3-4, validado con Docker Desktop en Windows)**:
  [despliegue/README.md](despliegue/README.md).
  No requiere clonar el repositorio, los secretos se generan en un volumen gestionado por
  `secretos-init`, Paperless se prepara automáticamente y el programador sustituye a la tarea cron.
  La imagen de arranque automatiza la puesta en marcha con un comando cuando se publique.
  Pendientes en
  [docs/INVENTARIO-FASE-5.md](docs/INVENTARIO-FASE-5.md).
- **Instalación con checkout (la probada hasta ahora)**: las secciones siguientes, con
  `instalar.sh`. Se retira en la fase 5.

## Instalación automática (Debian/Ubuntu)

Copie **esta carpeta** a su equipo (por ejemplo, `~/convenios-laborales/`) y ejecute con su usuario normal, **sin sudo** (la pedirá cuando haga falta):

```bash
cd ~/convenios-laborales
./instalar.sh
```

El instalador:

1. Comprueba el sistema (Debian/Ubuntu, amd64/arm64, RAM y espacio libre; se recomiendan ≥16 GB de RAM y ≥30 GB libres).
2. Instala `python3`, `curl`, `cron`, `flock` (util-linux), `poppler-utils` (`pdftotext`) y activa cron.
3. Instala Docker Engine + Compose v2 desde el [repositorio oficial de Docker](https://docs.docker.com/engine/install/) si no están, activa el servicio y añade su usuario al grupo `docker` (vuelva a iniciar sesión después para usar `docker` sin sudo). Si detecta el Docker de la distribución (`docker.io`) u otros paquetes incompatibles, se detiene y le indica qué hacer, sin desinstalar nada.
4. Ejecuta `scripts/preparar.sh`: `.env` con secretos aleatorios (permisos 600), UID/GID de su usuario para Paperless, modelo según la RAM y directorios locales.
5. Descarga las imágenes, arranca la pila y espera a que Changedetection, Paperless y AnythingLLM respondan.
6. Crea el administrador de Paperless (`admin`, o el de `PAPERLESS_ADMIN_USER`) con contraseña aleatoria guardada en `credenciales.txt` (permisos 600; cámbiela tras el primer acceso y borre el fichero) y crea las etiquetas.
7. Espera a que se descarguen los modelos de Ollama y comprueba que están disponibles.
8. Instala la tarea cron del monitor del BOE (cada seis horas).

Opciones: `--sin-arrancar` (solo dependencias y configuración), `--sin-cron`, `--no-esperar-modelos`, `--ayuda`. Es seguro volver a ejecutarlo: no regenera secretos existentes, no cambia la contraseña de un administrador existente ni duplica el cron. Si algo falla, termina con un resumen de los problemas y el comando de diagnóstico. En derivadas de Debian/Ubuntu no reconocidas indique la base del repositorio de Docker: `DOCKER_DISTRO=debian DOCKER_CODENAME=bookworm ./instalar.sh`.

Quedan manuales, porque requieren decisiones o credenciales suyas: el asistente inicial y la clave API de AnythingLLM, las fuentes y notificaciones de Changedetection y el SMTP del monitor (ver secciones siguientes). En el despliegue autónomo, el panel local está en http://localhost:8080 y muestra los accesos, el estado de los servicios y la última comprobación del BOE. Las descargas (imágenes y modelos, unos 20 GB) pueden tardar bastante.

## Instalación manual y otros sistemas

Requisitos: Docker Engine + plugin Compose v2, cron, Python 3, curl, flock, conexión a internet **solo para descargar imágenes/modelos y consultar BOE/REGCON**. RAM recomendada ≥16 GB para llama3.1:8b (con menos se selecciona qwen2.5:7b, que también puede requerir bastante memoria y disco). En Debian/Ubuntu siga la [guía oficial de Docker Engine](https://docs.docker.com/engine/install/debian/) e instale `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`; después `sudo systemctl enable --now docker` y `sudo usermod -aG docker "$USER"` (vuelva a iniciar sesión). Windows/macOS requieren Docker Desktop (gratuito solo bajo sus condiciones de licencia; para una alternativa libre use Linux con Docker Engine/Podman Compose); el instalador automático no los cubre. Verifique `docker --version && docker compose version`.

```bash
cd ~/convenios-laborales
./scripts/preparar.sh
# Verifique .env y proteja los secretos; prepare contraseña de usuario de Paperless aparte.
# Si su UID no es 1000 (id -u), AnythingLLM necesita: sudo chown -R 1000:1000 anythingllm
docker compose config -q
docker compose up -d
docker compose ps
# Espere a que termine la descarga de modelos:
docker compose logs -f modelos
```

Estructura: `changedetection/`, `paperless/consume/`, `paperless/export/`, `anythingllm/`, `scripts/`, `docker-compose.yml`, `instalar.sh`. Los datos persistentes quedan en volúmenes Docker y directorios locales; no borre estos sin copia. Los puertos están ligados a `127.0.0.1`, no expuestos a la red. Docker y la descarga de modelos necesitan internet; durante el uso, **la vigilancia BOE y el SMTP sí salen de la máquina**. Si el requisito literal es que ningún dato salga, no configure SMTP externo ni habilite monitorización externa; use un relay SMTP propio y confirme la política aplicable.

## Accesos y activación

- Panel OpenPactum (solo despliegue autónomo): http://localhost:8080 — resumen local del estado de
  los servicios, la última comprobación del BOE y accesos a las herramientas. No sustituye su
  configuración: las fuentes, el SMTP y la carga/organización documental se preparan en las
  herramientas enlazadas.

- Changedetection: http://localhost:5000 — añada allí las fuentes que el monitor no cubre (REGCON es web, no RSS; vea `scripts/fuentes-rss.txt`) y las URL de sus boletines provinciales. Ajuste filtros por convenio y selectores para reducir falsos avisos. Configure notificaciones en la interfaz con una URL Apprise `mailto://USUARIO:CLAVE@SERVIDOR:587/?to=DESTINO&from=ORIGEN`; codifique caracteres especiales de usuario/clave y utilice TLS según su servidor. Guarde la URL solo en la interfaz local; proteja el acceso. Sin SMTP no hay alertas de Changedetection.
- Paperless: http://localhost:8000 — el despliegue autónomo crea el administrador y sus etiquetas al primer arranque. Las credenciales se guardan en `paperless/credenciales.txt` dentro de `OPENPACTUM_DATOS` (modo 600 en Linux); cámbiela tras el primer acceso. Con `instalar.sh`, las credenciales están en el `credenciales.txt` de la instalación. En instalación manual, cree el administrador con `docker compose exec paperless python manage.py createsuperuser`; en Perfil → tokens API obtenga token y ejecute `PAPERLESS_TOKEN='...' ./scripts/crear-etiquetas.sh`. El OCR español/inglés se aplica automáticamente a PDFs colocados en `paperless/consume/`; compruebe que hay texto extraído. La carpeta `consume/` es local al host y Paperless retira ficheros al procesarlos.
- AnythingLLM: http://localhost:3001 — configure Ollama en `http://ollama:11434`, modelo indicado en `.env`, embeddings `nomic-embed-text` y LanceDB. Complete el asistente inicial. Cree clave API en AnythingLLM, copie `scripts/convenios.txt.example` a `scripts/convenios.txt`, una línea por convenio, y ejecute `ANYTHINGLLM_API_KEY='...' ./scripts/crear-workspaces.sh`. Suba manualmente el PDF del convenio desde Paperless (descárguelo o exporte) a su workspace, **insértelo en el contexto** y pregunte citando artículo y versión; valide siempre contra el texto oficial. Paperless y AnythingLLM no sincronizan documentos automáticamente.

## Monitor del BOE y correo

Copie `scripts/config-email.env.example` a `scripts/config-email.env`, rellene servidor SMTP, credenciales y destinatario y `chmod 600 scripts/config-email.env`. Para TLS implícito use puerto 465 y `SMTP_STARTTLS=false`; para STARTTLS, puerto 587 y `true`. Use SMTP autohospedado si desea evitar un tercero. Ejecute primero `./scripts/monitor-convenios.sh`: lee el canal temático de convenios colectivos del BOE (https://www.boe.es/rss/canal.php?c=ccolectivos, que publica los convenios de los dos últimos meses; puede cambiarse con `OPENPACTUM_RSS`), descarga los PDFs oficiales a `paperless/consume/`, comprueba su firma y mantiene estado en `scripts/.estado-rss.json`; no compara versiones ni interpreta jurídicamente el cambio. Luego `./scripts/instalar-cron.sh` instala la ejecución cada seis horas (`instalar.sh` ya lo hace salvo con `--sin-cron`); vea `scripts/monitor.log`. Si SMTP no está configurado se registra la novedad localmente, sin correo; configure SMTP **antes** de la primera ejecución si necesita recibir todas las alertas. El RSS puede no incluir toda la historia ni todos los boletines provinciales: Changedetection supervisa las fuentes adicionales que configure manualmente.

## Comparación de versiones

En Paperless descargue ambas versiones y compárelas con `diff -u texto-antiguo.txt texto-nuevo.txt` tras extraer texto con `pdftotext -layout archivo.pdf texto.txt` (paquete `poppler-utils`), o use el texto OCR exportado de Paperless. Guarde ambos documentos con fechas, referencias BOE y etiquetas `vigente`/`derogado`; la comparación no está automatizada. Revise tablas y maquetación manualmente.

## Privacidad y mantenimiento

No exponga los puertos públicamente. Haga copias de seguridad de los volúmenes (`docker volume ls`), `changedetection/`, `anythingllm/`, `.env` y PDFs; cifre las copias. `anythingllm/.env` guarda la configuración del asistente de AnythingLLM. Las imágenes fijadas requieren actualizaciones de seguridad periódicas. Los modelos y contenedores ocupan varios GB. Para diagnosticar: `docker compose ps`, `docker compose logs --tail=100 paperless`, `docker compose logs --tail=100 modelos`. No suba tokens ni documentos al repositorio.
