# Imagen del monitor del BOE de OpenPactum.
# Usa solo la biblioteca estándar de Python: no instala dependencias.
# Contexto de construcción: convenios-laborales/scripts/ (ver .github/workflows/monitor-imagen.yml).
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG OPENPACTUM_VERSION=dev
LABEL org.opencontainers.image.title="openpactum-monitor" \
      org.opencontainers.image.description="Vigilancia del RSS del BOE para convenios colectivos (OpenPactum)" \
      org.opencontainers.image.source="https://github.com/danielrodriguez-star/OpenPactum" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${OPENPACTUM_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENPACTUM_ESTADO=/data/estado/estado-rss.json \
    OPENPACTUM_CONSUME=/data/consume

# Usuario sin privilegios y con UID/GID fijos. Los volúmenes se configuran en el despliegue (fase 3).
RUN groupadd --system --gid 10001 openpactum \
 && useradd --system --uid 10001 --gid openpactum --home-dir /nonexistent --shell /usr/sbin/nologin openpactum \
 && mkdir -p /data/estado /data/consume \
 && chown -R 10001:10001 /data

COPY monitor-convenios.py /app/monitor-convenios.py

WORKDIR /app
USER 10001:10001
ENTRYPOINT ["python3", "/app/monitor-convenios.py"]
