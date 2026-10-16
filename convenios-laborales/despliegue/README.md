# Despliegue autónomo (fase 3)

**Estado: probado con Docker Desktop en Windows**, con volúmenes y prefijo de prueba aislados:
los servicios principales respondieron, Paperless llegó a estado saludable y Ollama pudo descargar
y ejecutar un modelo pequeño. El uso con otros sistemas y hardware sigue requiriendo validación.

Este directorio contiene el despliegue **sin clonar el repositorio**: el manifiesto y sus
ficheros auxiliares se pueden descargar sueltos y ejecutar en cualquier equipo con Docker.

| Fichero | Para qué sirve |
| --- | --- |
| `compose.yaml` | Manifiesto de la pila completa (panel local, vigilancia, Paperless, Ollama, AnythingLLM, monitor y programador). |
| `.env.example` | Configuración del despliegue: prefijo, rutas, secretos, modelo y SMTP. |
| `secretos-init.sh` | Genera los secretos en su volumen, los proyecta para Paperless y prepara los datos del host. |
| `paperless-init.py` | Crea idempotentemente el administrador inicial y las etiquetas estándar de Paperless. |
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

   Indique la etiqueta publicada en `OPENPACTUM_VERSION` y ajuste `USERMAP_UID`/`USERMAP_GID` a
   su usuario (`id -u`, `id -g`). Con menos de 16 GB de RAM, cambie también `MODELO`. **No hay
   contraseñas en este fichero**: las genera `secretos-init`.
3. Primer arranque, en dos pasos (los secretos tienen que existir antes de que Compose lea la
   configuración de Paperless):

   ```bash
   docker compose --env-file .env -f compose.yaml run --rm --no-deps secretos-init
   docker compose --env-file .env -f compose.yaml up -d
   docker compose --env-file .env -f compose.yaml ps
   docker compose --env-file .env -f compose.yaml logs -f modelos   # descarga de modelos
   ```

   Los arranques siguientes ya son un solo comando (`up -d`).

Los puertos se publican **solo en `127.0.0.1`**: el panel OpenPactum en 8080, Changedetection en
5000, Paperless en 8000 y AnythingLLM en 3001. Abra http://localhost:8080 para ver el estado y
acceder a las herramientas. Ollama no publica puerto. `secretos-init` prepara los secretos y el
árbol de datos del host; cuando Paperless está sano, `paperless-init` crea automáticamente el
administrador inicial y las etiquetas. El asistente inicial de AnythingLLM y la configuración SMTP
siguen siendo manuales y están descritos en el [README de la instalación](../README.md).

### Prefijo del proyecto

`OPENPACTUM_PREFIJO` (por defecto `openpactum`) nombra el proyecto de Compose y los volúmenes
(`openpactum_postgres_datos`, `openpactum_ollama_datos`, …, incluidos los volúmenes de secretos
`openpactum_secretos` y `openpactum_paperless_admin_secretos`). Sirve para tener dos instalaciones
en el mismo equipo sin que se pisen; los
nombres de los volúmenes están fijados de forma explícita para que cambiar el prefijo no deje los
datos anteriores huérfanos.

### Secretos y datos

`secretos-init` (servicio de un solo uso, se ejecuta antes que el resto):

- Genera `postgres_password` y `paperless_secret_key` en el volumen `<prefijo>_secretos`, y
  `paperless_admin_password` en `<prefijo>_paperless_admin_secretos`, con `/dev/urandom`.
  **Nunca sobrescribe** un secreto existente y nunca lo imprime.
- Proyecta ambos en `<datos>/secretos/paperless.env` (0640, grupo `USERMAP_GID`) para Paperless,
  cuya imagen no admite el convenio `*_FILE`. Es un artefacto derivado: se puede borrar y se
  regenera a partir del volumen.
- Prepara el árbol de datos del host (directorios, propietario `USERMAP_UID:GID` y permisos de
  `paperless/consume`), que antes hacía `preparar.sh` al instalar con `instalar.sh`.

El monitor solo necesita el volumen general (por ejemplo, para SMTP); el secreto de la contraseña
del administrador queda en un volumen separado que solo monta `paperless-init`.

Después de que Paperless esté sano, `paperless-init` crea el administrador (solo si aún no existe)
y las etiquetas habituales. Las credenciales iniciales quedan en
`<OPENPACTUM_DATOS>/paperless/credenciales.txt`; cámbielas después del primer acceso y proteja o
elimine ese fichero. El servicio no cambia la contraseña de un administrador que ya exista.

Postgres sí admite ficheros (`POSTGRES_PASSWORD_FILE`) y el monitor también
(`SMTP_PASSWORD_FILE`), así que ambos leen del volumen general directamente. Para guardar un
secreto que no se genera solo:

```bash
printf '%s' 'clave-smtp' | docker compose --env-file .env -f compose.yaml run --rm -T --no-deps secretos-init escribir smtp_password
```

y después `SMTP_PASSWORD_FILE=/run/secretos/smtp_password` en el fichero de entorno. Los ficheros
se crean con permisos `0640`: si su usuario no puede leer el fichero proyectado, `docker compose`
lo dirá al arrancar (ajuste el grupo del fichero o ejecute el arranque con el mismo usuario con el
que se crearon los secretos).

### Monitor y programador

- `programador`: hace una ejecución inicial y repite el monitor cada `OPENPACTUM_INTERVALO`
  segundos (6 h por defecto, la misma cadencia que la tarea cron anterior).
- `monitor`: ejecución manual, `docker compose --profile manual run --rm monitor`. Está excluido
  del arranque normal para evitar procesar dos veces el feed junto al programador.
- Los avisos por correo se configuran con `SMTP_*` en el fichero de entorno; sin `SMTP_HOST` el
  monitor solo deja constancia en el log del contenedor.
- El panel de http://localhost:8080 está orientado a la búsqueda de convenios para RR. HH. y
  nóminas. Incluye accesos rápidos configurables: educación, acción e intervención social y ocio
  educativo vienen de serie, y se pueden añadir sectores con su propio texto de búsqueda en REGCON.
  Consulta los registros públicos de REGCON (autoridades estatales, autonómicas y provinciales),
  permite filtrar la página actual y guardar convenios en el navegador, y abre la publicación
  oficial cuando existe un enlace directo. «Archivar en Paperless» descarga bajo demanda esa
  publicación al directorio compartido `paperless/consume`: conserva el PDF original y sigue enlaces
  a un PDF desde una página HTML; si no hay PDF descargable, guarda la página como texto con su URL
  de origen. Paperless procesa los documentos de forma asíncrona;
  la acción no descarga toda la colección. Los resultados son trámites y pueden repetirse para un
  convenio. REGCON mantiene aparte los registros anteriores
  al 1 de octubre de 2010. Para cada trámite con publicación PDF o HTML accesible se puede solicitar
  un resumen con IA local: el panel extrae el texto del documento, lo procesa por fragmentos en segundo plano con
  Ollama y conserva
  solo el resumen en `OPENPACTUM_DATOS/panel`; los documentos completos no se guardan ni se envían
  a servicios externos. Se genera bajo demanda, para evitar precargar y conservar resúmenes de todo
  REGCON; la primera solicitud puede tardar varios minutos y las siguientes reutilizan la caché si
  el documento y el modelo no han cambiado. No se pueden resumir trámites sin publicación directa,
  documentos que no sean PDF/HTML, PDFs escaneados sin texto ni convenios históricos que REGCON no exponga en esta búsqueda.
  Verifique las referencias de página o artículo en el texto oficial: el contenido generado puede omitir datos
  o equivocarse y no es asesoramiento jurídico. La ficha del convenio estatal de Acción e
  Intervención Social 2026-2029 incluye además referencias a artículos y la tabla oficial de salario
  base bruto anual 2026-2029, con enlace al BOE. El cálculo de complementos y la comparación de
  versiones aún requieren incorporación y verificación documental. El panel persiste en
  `OPENPACTUM_DATOS/panel/catalogo.sqlite` los convenios y trámites que aparecen en búsquedas,
  agrupados por código y autoridad; es un catálogo de lo consultado, no la importación completa
  de REGCON. Los favoritos continúan en el almacenamiento local del navegador.
- El asistente inicial de AnythingLLM y su clave API siguen siendo pasos manuales.

## Arranque con un solo comando (fase 4)

La imagen `openpactum-arranque` hace todo lo anterior por usted: descarga el manifiesto del
repositorio y lo verifica contra el hash que lleva dentro, coloca el script de secretos, crea el
fichero de entorno a partir del ejemplo, prepara secretos y datos y arranca la pila.

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/lib/openpactum:/var/lib/openpactum \
  ghcr.io/danielrodriguez-star/openpactum-arranque:0.1.0 arriba
```

Tres cosas que no se pueden olvidar en esa orden:

- El socket de Docker, porque es el motor del host el que despliega la pila.
- El directorio de trabajo **con la misma ruta absoluta** dentro y fuera del contenedor
  (`/var/lib/openpactum`): los montajes del manifiesto los resuelve el host, así que la ruta tiene
  que significar lo mismo en los dos lados.
- `-it` solo hace falta para las órdenes que siguen la salida (`registros`).

**Riesgo asumido:** montar `/var/run/docker.sock` equivale a dar **control total del equipo
anfitrión** a ese contenedor (puede arrancar cualquier imagen como root en el host). Úselo en un
equipo de confianza, no exponga el socket a la red y revise la imagen que ejecuta.

Órdenes disponibles: `arriba` (por defecto), `abajo`, `estado`, `registros`, `monitor`,
`actualizar`, `version` y `ayuda`. Se pueden cambiar con variables de entorno: `OPENPACTUM_RAIZ`
(directorio de trabajo), `OPENPACTUM_VERSION` (etiqueta de la imagen del monitor; por defecto, la
de la propia imagen de arranque) y `USERMAP_UID`/`USERMAP_GID`.

Para construirla a mano (el contexto de construcción es `convenios-laborales/`):

```bash
docker build -f convenios-laborales/arranque/Dockerfile \
  --build-arg OPENPACTUM_VERSION=0.1.0 \
  --build-arg OPENPACTUM_URL_MANIFIESTO=https://raw.githubusercontent.com/danielrodriguez-star/OpenPactum/v0.1.0/convenios-laborales/despliegue/compose.yaml \
  --build-arg OPENPACTUM_COMPOSE_SHA256="$(sha256sum convenios-laborales/despliegue/compose.yaml | cut -d' ' -f1)" \
  -t openpactum-arranque:0.1.0 convenios-laborales
```

**Todavía no hay imagen publicada.** El flujo de GitHub Actions calcula el hash del manifiesto
desde el mismo checkout que construye la imagen; en pull requests la construye sin publicarla y en
`main` o en etiquetas semánticas la publica en GHCR. La imagen local se construyó y se probó su
orden `ayuda`; el despliegue completo desde una imagen publicada sigue pendiente.

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
las pruebas). **Lo que no prueba**: el script local no arranca la pila ni comprueba permisos, descarga de modelos
o asistentes iniciales. La pila completa sí se probó en Docker Desktop para Windows: servicios e
interfaces respondieron, Paperless procesó documentos, Ollama ejecutó un modelo, el acceso inicial
de Paperless y sus ocho etiquetas se verificaron, y repetir el bootstrap conservó la contraseña.
Esta prueba no sustituye la validación en otros sistemas y configuraciones.

## Límites y trabajo pendiente

- La pila se ha probado en Docker Desktop para Windows, no en Linux ni en otras configuraciones de
  hardware; revisa permisos, copias de seguridad y espacio disponible antes de usarla con datos
  importantes.
- Las imágenes se fijan por versión, pero no por digest; Redis mantiene la etiqueta flotante
  `7-alpine`.
- No se ha comprobado si AnythingLLM funciona sin `cap_add: SYS_ADMIN`.
- La migración desde la instalación con `instalar.sh` aún no tiene guía.
- El asistente/API de AnythingLLM, las fuentes y notificaciones de Changedetection, y el SMTP se
  configuran manualmente. Paperless y AnythingLLM no sincronizan documentos entre sí.
- La comparación de versiones de convenios sigue siendo manual; revisa siempre el PDF oficial.
