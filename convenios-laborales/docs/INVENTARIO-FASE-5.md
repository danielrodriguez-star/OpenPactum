# Inventario para la fase 5

Estado actualizado tras validar el despliegue con Docker Desktop en Windows. La pila arranca,
Paperless prepara el administrador y las etiquetas, y el panel local muestra el estado; esta lista
se limita a los pendientes que aún no están resueltos.

## 1. Pendientes técnicos

| Pendiente | Consecuencia hoy | Qué haría falta |
| --- | --- | --- |
| Digests de las imágenes sin fijar | Un cambio de etiqueta puede traer una versión distinta sin que el repositorio cambie | Fijar `imagen@sha256:…` (o al menos etiquetas de parche) para todas las imágenes |
| Redis con la etiqueta flotante `redis:7-alpine` | Se actualiza solo al descargar; puede romper la pila sin aviso | Fijar una versión concreta (y su digest) |
| `cap_add: SYS_ADMIN` en AnythingLLM sin verificar | Se concede una capacidad amplia al contenedor sin saber si la necesita | Probar AnythingLLM sin `cap_add`; si funciona, retirarlo; si no, documentar por qué se necesita |
| `MIGRACION.md` sin escribir | Quien tenga la instalación con `instalar.sh` no tiene guía para pasar al despliegue nuevo | Documentar el paso: conservar datos, reutilizar secretos, no perder el estado del monitor |
| Validación del despliegue fuera de Windows | Los permisos POSIX, el hardware y los volúmenes no se han verificado en Linux | Ejecutar el mismo ciclo de instalación, reinicio y persistencia en las plataformas que se quieran soportar |

## 2. Retirada de la instalación con checkout (fase 5)

Se retiran cuando el despliegue nuevo esté validado en las plataformas objetivo y haya una guía
segura de migración:

- `instalar.sh` (instalador de Debian/Ubuntu) y sus opciones.
- `scripts/` del host: `monitor-convenios.sh`, `instalar-cron.sh`, `preparar.sh`,
  `crear-etiquetas.sh`, `crear-workspaces.sh` y `fuentes-rss.txt`. La tarea cron y la preparación
  de secretos y datos las hace ahora el programador del manifiesto y `secretos-init`.
- `docker-compose.yml` y `.env.example` de la raíz de `convenios-laborales/` (versión con checkout),
  sustituidos por `despliegue/compose.yaml` y `despliegue/.env.example`.
- `monitor-convenios.py` **no** se retira: es el contenido de la imagen del monitor. Lo lógico es
  moverlo junto a su `Dockerfile` (`monitor/`) y actualizar el flujo de la imagen y las pruebas.

## 3. Mejoras de seguridad que no se han aplicado

Ninguna de estas está puesta (no se han probado y algunas pueden romper servicios):

- `security_opt: ["no-new-privileges:true"]` en los servicios que lo admitan.
- Sistemas de ficheros de solo lectura (`read_only: true`) con `tmpfs` para lo que necesite
  escribir.
- Límites de recursos (`mem_limit`, `cpus`) y rotación de registros (`logging.options.max-size`),
  útil con modelos que llenan el disco.
- Endurecer `secretos-init`: ficheros 0600 y propietario por servicio en vez de 0640 con grupo
  compartido, y revisar si Paperless puede usar algún mecanismo mejor que el `env_file` proyectado.
- Publicar los puertos solo con `-it`/SSH al equipo, o añadir autenticación por delante
  (hoy se limitan a `127.0.0.1`, que es lo mínimo razonable).

## 4. Funcionalidad que sigue siendo manual

- El panel consulta en tiempo real los registros públicos de REGCON y enlaza a la publicación
  oficial. Desde resultados con publicación directa se puede añadir el PDF original, incluido el PDF
  enlazado desde una página HTML, o la transcripción de la página cuando no hay PDF descargable, al
  directorio de entrada de Paperless; la importación es bajo demanda y Paperless procesa los
  documentos de forma asíncrona. Los resultados son trámites y
  pueden repetir un mismo convenio (texto nuevo, revisiones, etc.). REGCON separa
  la consulta de registros anteriores al 1 de octubre de 2010; no se presenta esta búsqueda como
  una copia local completa ni como una consulta histórica exhaustiva.
- El panel conserva en `OPENPACTUM_DATOS/panel/catalogo.sqlite` un catálogo local de los resultados
  consultados, agrupando los trámites por código REGCON y autoridad. Cada publicación conserva su
  tipo de trámite, fechas y consulta de origen. No se precargan registros: hay que consultar cada
  búsqueda para que el convenio y sus versiones aparezcan en el catálogo. Los favoritos y sectores
  personalizados siguen siendo específicos de cada navegador.
- La búsqueda actual permite seleccionar una autoridad de la lista pública que REGCON ofrece en
  ese momento. La sección de cobertura compara esa lista con las autoridades ya observadas en el
  catálogo; no demuestra que se hayan capturado todos sus convenios. La consulta histórica
  independiente de REGCON para registros anteriores al 1 de octubre de 2010 se enlaza como fuente,
  pero todavía no se consulta desde OpenPactum.
- El panel ofrece accesos de sector editables (tres iniciales y hasta 40 adicionales), búsqueda,
  filtros de territorio y tipo de trámite sobre la página actual y una lista de seguimiento que se
  conserva solo en el navegador actual. Para los trámites con publicación oficial directa en PDF o
  HTML se puede generar un resumen bajo demanda, extrayendo el documento y usando Ollama local; el resumen
  persistido se guarda en `OPENPACTUM_DATOS/panel`, no el PDF. La caché se identifica por huella del
  contenido y modelo, y una sola generación se admite simultáneamente. Los PDF se citan por página y
  las páginas web por sección cuando está disponible. No cubre trámites sin publicación directa,
  documentos que no sean PDF/HTML, PDF escaneado sin texto ni la consulta histórica de REGCON; los resúmenes son
  orientativos y requieren contraste humano. La ficha salarial estructurada disponible del convenio
  estatal de Acción e Intervención Social 2026-2029 resume ámbitos, vigencia, jornada, vacaciones
  y retribución con referencias a artículos, e incluye los salarios base brutos anuales de los
  grupos profesionales 0-4 para 2026-2029, cotejados con el anexo II del BOE-A-2026-4641. Los
  importes no incluyen complementos. El cálculo de complementos, escenarios y comparación de
  versiones requieren incorporación y verificación documental.
- Asistente inicial y clave API de AnythingLLM; subir los PDF a los workspaces (Paperless y
  AnythingLLM no se sincronizan solos).
- Configurar SMTP del monitor y las fuentes de Changedetection.
- Comparación de versiones de convenios: hojas de cálculo, `pdftotext` y `diff -u` a mano.
