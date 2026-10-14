# Inventario para la fase 5

Recuento de lo que queda pendiente después de las fases 1 a 4. Nada de esta lista está hecho: es
el punto de partida para repartir el trabajo.

## 1. Pendientes que bloquean o degradan el despliegue nuevo

| Pendiente | Consecuencia hoy | Qué haría falta |
| --- | --- | --- |
| `COMPOSE_SHA256` sin definir como variable de repositorio | La imagen de arranque **no se construye** (el flujo de CI la salta) ni se publica | Calcular `sha256sum convenios-laborales/despliegue/compose.yaml` y definirlo en las variables del repositorio; actualizarlo cuando cambie el manifiesto |
| Digests de las imágenes sin fijar | Un cambio de etiqueta puede traer una versión distinta sin que el repositorio cambie | Fijar `imagen@sha256:…` (o al menos etiquetas de parche) para todas las imágenes |
| Redis con la etiqueta flotante `redis:7-alpine` | Se actualiza solo al descargar; puede romper la pila sin aviso | Fijar una versión concreta (y su digest) |
| `cap_add: SYS_ADMIN` en AnythingLLM sin verificar | Se concede una capacidad amplia al contenedor sin saber si la necesita | Probar AnythingLLM sin `cap_add`; si funciona, retirarlo; si no, documentar por qué se necesita |
| Nadie ha arrancado la pila con Docker real | Manifiesto, secretos, permisos y arranque solo están validados por sintaxis | Prueba en un equipo con Docker: `arriba`, comprobar salud de los servicios, reiniciar y comprobar que los datos y los secretos persisten |
| `MIGRACION.md` sin escribir | Quien tenga la instalación con `instalar.sh` no tiene guía para pasar al despliegue nuevo | Documentar el paso: conservar datos, reutilizar secretos, no perder el estado del monitor |
| Imagen de arranque sin validar en CI | Su Dockerfile no se construye en ningún flujo hasta que exista `COMPOSE_SHA256` | Construirla (sin publicar) en los pull request una vez definida la variable |

## 2. Retirada de la instalación con checkout (fase 5)

Se retiran cuando el despliegue nuevo esté probado con Docker:

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

- Crear el administrador de Paperless y sus etiquetas.
- Asistente inicial y clave API de AnythingLLM; subir los PDF a los workspaces (Paperless y
  AnythingLLM no se sincronizan solos).
- Configurar SMTP del monitor y las fuentes de Changedetection.
- Comparación de versiones de convenios: hojas de cálculo, `pdftotext` y `diff -u` a mano.
