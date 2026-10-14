# Convenios laborales — instalación local

**Estado:** configuración preparada, no desplegada en esta sesión: el entorno de desarrollo no tiene Docker. Ejecute los comandos en su propio equipo. No se garantiza cumplimiento RGPD por instalar software: evalúe además acceso, copias, retención y proveedor SMTP.

## Requisitos y preparación

Docker Engine + plugin Compose v2, cron, Python 3, curl, flock, conexión a internet **solo para descargar imágenes/modelos y consultar BOE/REGCON**. RAM recomendada ≥16 GB para llama3.1:8b (con menos se selecciona qwen2.5:7b, que también puede requerir bastante memoria y disco). En Debian 12: siga la [guía oficial de Docker Engine](https://docs.docker.com/engine/install/debian/) para configurar el repositorio e instalar `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`; después `sudo systemctl enable --now docker` y `sudo usermod -aG docker "$USER"` (vuelva a iniciar sesión). En Ubuntu use la guía equivalente de Ubuntu; Windows/macOS requieren Docker Desktop (gratuito solo bajo sus condiciones de licencia; para una alternativa libre use Linux con Docker Engine/Podman Compose). Verifique `docker --version && docker compose version`.

Copie **esta carpeta** a `~/convenios-laborales/` de su ordenador (o trabaje aquí si ya es su máquina):

```bash
cd ~/convenios-laborales
./scripts/preparar.sh
mkdir -p paperless/export
# Verifique .env y proteja los secretos; prepare contraseña de usuario de Paperless aparte.
docker compose config -q
docker compose up -d
docker compose ps
# Espere a que termine la descarga de modelos:
docker compose logs -f modelos
```

Estructura: `changedetection/`, `paperless/consume/`, `anythingllm/`, `scripts/`, `docker-compose.yml`. Los datos persistentes quedan en volúmenes Docker y directorios locales; no borre estos sin copia. Los puertos están ligados a `127.0.0.1`, no expuestos a la red. Docker y la descarga de modelos necesitan internet; durante el uso, **la vigilancia BOE y el SMTP sí salen de la máquina**. Si el requisito literal es que ningún dato salga, no configure SMTP externo ni habilite monitorización externa; use un relay SMTP propio y confirme la política aplicable.

## Accesos y activación

- Changedetection: http://localhost:5000 — añada allí las dos URLs de `scripts/fuentes-rss.txt` (REGCON es web, no RSS) y las URL de sus boletines provinciales. Ajuste filtros por convenio y selectores para reducir falsos avisos. Configure notificaciones en la interfaz con una URL Apprise `mailto://USUARIO:CLAVE@SERVIDOR:587/?to=DESTINO&from=ORIGEN`; codifique caracteres especiales de usuario/clave y utilice TLS según su servidor. Guarde la URL solo en la interfaz local; proteja el acceso. Sin SMTP no hay alertas de Changedetection.
- Paperless: http://localhost:8000 — cree el administrador con `docker compose exec paperless python manage.py createsuperuser`. En Perfil → tokens API obtenga token y ejecute `PAPERLESS_TOKEN='...' ./scripts/crear-etiquetas.sh`. El OCR español/inglés se aplica automáticamente a PDFs colocados en `paperless/consume/`; compruebe que hay texto extraído. La carpeta `consume/` es local al host y Paperless retira ficheros al procesarlos.
- AnythingLLM: http://localhost:3001 — configure Ollama en `http://ollama:11434`, modelo indicado en `.env`, embeddings `nomic-embed-text` y LanceDB. Complete el asistente inicial. Cree clave API en AnythingLLM, copie `scripts/convenios.txt.example` a `scripts/convenios.txt`, una línea por convenio, y ejecute `ANYTHINGLLM_API_KEY='...' ./scripts/crear-workspaces.sh`. Suba manualmente el PDF del convenio desde Paperless (descárguelo o exporte) a su workspace, **insértelo en el contexto** y pregunte citando artículo y versión; valide siempre contra el texto oficial. Paperless y AnythingLLM no sincronizan documentos automáticamente.

## Monitor del BOE y correo

Copie `scripts/config-email.env.example` a `scripts/config-email.env`, rellene servidor SMTP, credenciales y destinatario y `chmod 600 scripts/config-email.env`. Para TLS implícito use puerto 465 y `SMTP_STARTTLS=false`; para STARTTLS, puerto 587 y `true`. Use SMTP autohospedado si desea evitar un tercero. Ejecute primero `./scripts/monitor-convenios.sh`: procesa entradas nuevas del feed que contengan «convenio colectivo», descarga PDFs oficiales a `paperless/consume/`, comprueba su firma y mantiene estado en `scripts/.estado-rss.json`; no compara versiones ni interpreta jurídicamente el cambio. Luego `./scripts/instalar-cron.sh` instala la ejecución cada seis horas; vea `scripts/monitor.log`. Si SMTP no está configurado se registra la novedad localmente, sin correo; configure SMTP **antes** de la primera ejecución si necesita recibir todas las alertas. El RSS puede no incluir toda la historia ni todos los boletines provinciales: Changedetection supervisa las fuentes adicionales que configure manualmente.

## Comparación de versiones

En Paperless descargue ambas versiones y compárelas con `diff -u texto-antiguo.txt texto-nuevo.txt` tras extraer texto con `pdftotext -layout archivo.pdf texto.txt` (paquete `poppler-utils`), o use el texto OCR exportado de Paperless. Guarde ambos documentos con fechas, referencias BOE y etiquetas `vigente`/`derogado`; la comparación no está automatizada. Revise tablas y maquetación manualmente.

## Privacidad y mantenimiento

No exponga los puertos públicamente. Haga copias de seguridad de los volúmenes (`docker volume ls`), `changedetection/`, `anythingllm/`, `.env` y PDFs; cifre las copias. Las imágenes fijadas requieren actualizaciones de seguridad periódicas. Los modelos y contenedores ocupan varios GB. Para diagnosticar: `docker compose ps`, `docker compose logs --tail=100 paperless`, `docker compose logs --tail=100 modelos`. No suba tokens ni documentos al repositorio.
