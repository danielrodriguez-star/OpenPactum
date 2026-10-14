# Despliegue autónomo (fase 3)

**Estado: sin probar con Docker real.** El manifiesto y el arranque se han escrito y se validan
por sintaxis, pero **nunca se han arrancado** en un equipo con Docker. La validación de Compose
(`docker compose config -q`) se hace solo en CI, porque en el equipo de desarrollo no hay Docker.
Lo que sigue describe el uso previsto, no una instalación verificada.

Este directorio contiene el despliegue **sin clonar el repositorio**: el manifiesto y sus
ficheros auxiliares se pueden descargar sueltos y ejecutar en cualquier equipo con Docker.

| Fichero | Para qué sirve |
| --- | --- |
| `compose.yaml` | Manifiesto de la pila completa (vigilancia, Paperless, Ollama, AnythingLLM, monitor y programador). |
| `.env.example` | Configuración del despliegue: prefijo, rutas, secretos, modelo y SMTP. |
| `validar-despliegue.sh` | Prueba local: sintaxis, pruebas unitarias y validez del manifiesto. |

## Requisitos

- Docker Engine con el plugin Compose v2 (`docker compose version`).
- ~20 GB libres para imágenes y modelos, y RAM suficiente para el modelo elegido (≥16 GB
  recomendados para `llama3.1:8b`).
- No hace falta Python, cron ni clonar el repositorio: el monitor va en su propio contenedor
  (imagen `openpactum-monitor`) y el programador sustituye a la tarea cron del host.

## Puesta en marcha

1. Descargue la carpeta (o solo estos ficheros) a un directorio del equipo, por ejemplo
   `/var/lib/openpactum/despliegue` y `/var/lib/openpactum/datos` para los datos.
2. Cree el fichero de configuración y revise los valores:

   ```bash
   cd /var/lib/openpactum/despliegue
   cp .env.example .env
   chmod 600 .env
   ```

   Como mínimo, cambie `POSTGRES_PASSWORD` y `PAPERLESS_SECRET_KEY` (genere dos valores
   distintos, por ejemplo con `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`),
   indique la etiqueta publicada en `OPENPACTUM_VERSION` y ajuste `USERMAP_UID`/`USERMAP_GID`
   a su usuario (`id -u`, `id -g`). Con menos de 16 GB de RAM, cambie también `MODELO`.
3. Arranque la pila y compruebe el estado:

   ```bash
   docker compose --env-file .env -f compose.yaml up -d
   docker compose --env-file .env -f compose.yaml ps
   docker compose --env-file .env -f compose.yaml logs -f modelos   # descarga de modelos
   ```

Los puertos se publican **solo en `127.0.0.1`**: Changedetection en 5000, Paperless en 8000 y
AnythingLLM en 3001. Ollama no publica puerto. El servicio `datos-init` prepara el árbol de datos
(directorios, propietario y permisos) antes de arrancar el resto; el resto de pasos manuales de la
instalación con `instalar.sh` (crear el administrador de Paperless, etiquetas, asistente de
AnythingLLM, SMTP) siguen siendo manuales y están descritos en el
[README de la instalación](../README.md).

### Prefijo del proyecto

`OPENPACTUM_PREFIJO` (por defecto `openpactum`) nombra el proyecto de Compose y los volúmenes
(`openpactum_postgres_datos`, `openpactum_ollama_datos`, …). Sirve para tener dos instalaciones en
el mismo equipo sin que se pisen; los nombres de los volúmenes están fijados de forma explícita
para que cambiar el prefijo no deje los datos anteriores huérfanos.

### Monitor y programador

- `programador`: repite el monitor cada `OPENPACTUM_INTERVALO` segundos (6 h por defecto, la misma
  cadencia que la tarea cron anterior).
- `monitor`: ejecución manual, `docker compose run --rm monitor`.
- Los avisos por correo se configuran con `SMTP_*` en el fichero de entorno; sin `SMTP_HOST` el
  monitor solo deja constancia en el log del contenedor.

## Prueba local

`despliegue/validar-despliegue.sh` reúne las comprobaciones que **sí** se pueden hacer sin arrancar
la pila. Necesita el repositorio, `python3` y, para las pruebas del manifiesto, PyYAML
(`python3 -m pip install pyyaml`). Docker es opcional:

```bash
cd convenios-laborales
python3 -m pip install pyyaml            # solo la primera vez
./despliegue/validar-despliegue.sh
```

Hace tres cosas:

1. Comprueba la sintaxis de los scripts con el intérprete indicado en su shebang (`sh -n` o
   `bash -n`).
2. Ejecuta las pruebas unitarias (`python3 -m unittest discover -s tests`), incluidas las que
   comprueban las invariantes del manifiesto: servicios esperados, imágenes sin `latest`, puertos
   solo en `127.0.0.1`, volúmenes con nombre explícito, dependencias entre servicios, etc.
3. Si hay Docker, valida el manifiesto con `docker compose config -q` usando valores de prueba y un
   prefijo distinto del habitual. Si no lo hay, lo indica y continúa.

Opciones: `--sin-sintaxis`, `--sin-pruebas` y `--sin-docker` (es lo que usa la CI para no repetir
las pruebas). **Lo que no prueba**: arrancar la pila, crear volúmenes, permisos reales, descarga de
modelos ni el asistente inicial de las aplicaciones. Eso requiere un equipo con Docker y está
pendiente.

## Pendientes conocidos de este despliegue

- `COMPOSE_SHA256` no está definido: sin esa variable de repositorio no se construye la imagen del
  contenedor de arranque (fase 4).
- Los digests de las imágenes no están fijados y Redis usa la etiqueta flotante `7-alpine`.
- El `cap_add: SYS_ADMIN` de AnythingLLM no se ha verificado.
- `MIGRACION.md` (paso desde la instalación con `instalar.sh`) todavía no está escrito.
