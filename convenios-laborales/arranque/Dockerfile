# Imagen del contenedor de arranque de OpenPactum (fase 4).
#
# Despliega la pila con un solo comando desde el manifiesto publicado, sin clonar el
# repositorio. Necesita el socket de Docker del host, lo que equivale a control total del
# equipo anfitrión: es un riesgo asumido y documentado en despliegue/README.md.
#
# Contexto de construcción: convenios-laborales/ (ver .github/workflows/arranque-imagen.yml).
ARG ALPINE_IMAGE=alpine:3.20
FROM ${ALPINE_IMAGE}

# docker-cli + docker-cli-compose para hablar con el socket del host; curl para el manifiesto.
RUN apk add --no-cache ca-certificates curl docker-cli docker-cli-compose \
 && rm -rf /var/cache/apk/*

ARG OPENPACTUM_VERSION=dev
ARG OPENPACTUM_URL_MANIFIESTO=""
# Vacío por defecto: la imagen solo se construye si el repositorio define COMPOSE_SHA256.
ARG OPENPACTUM_COMPOSE_SHA256=""
LABEL org.opencontainers.image.title="openpactum-arranque" \
      org.opencontainers.image.description="Arranque del despliegue de OpenPactum (OpenPactum)" \
      org.opencontainers.image.source="https://github.com/danielrodriguez-star/OpenPactum" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${OPENPACTUM_VERSION}"

ENV OPENPACTUM_VERSION=${OPENPACTUM_VERSION} \
    OPENPACTUM_URL_MANIFIESTO=${OPENPACTUM_URL_MANIFIESTO} \
    OPENPACTUM_COMPOSE_SHA256=${OPENPACTUM_COMPOSE_SHA256} \
    OPENPACTUM_RAIZ=/var/lib/openpactum

COPY arranque/arrancar.sh /usr/local/lib/openpactum/arrancar.sh
# El manifiesto y el script de secretos van fijados a la imagen: se copian al desplegar.
COPY despliegue/secretos-init.sh /usr/local/lib/openpactum/secretos-init.sh
COPY despliegue/.env.example /usr/local/lib/openpactum/ejemplo.env

RUN chmod 0755 /usr/local/lib/openpactum/arrancar.sh

ENTRYPOINT ["/bin/sh", "/usr/local/lib/openpactum/arrancar.sh"]
CMD ["arriba"]
