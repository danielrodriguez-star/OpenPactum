# OpenPactum

Configuración local para vigilancia y gestión de convenios colectivos españoles.

Instalación en Debian/Ubuntu con un solo comando:

```bash
cd convenios-laborales
./instalar.sh
```

## Despliegue sin clonar el repositorio

Las fases 3 y 4 añaden un despliegue autónomo en `convenios-laborales/despliegue/`: un manifiesto
que no necesita el repositorio, los secretos generados en un volumen propio, un programador que
sustituye a la tarea cron y un contenedor de arranque que lo hace todo con un solo comando.

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /var/lib/openpactum:/var/lib/openpactum \
  ghcr.io/danielrodriguez-star/openpactum-arranque:VERSION arriba
```

La pila se ha probado localmente con Docker Desktop en Windows; todavía hacen falta pruebas en
otras plataformas. La imagen de arranque aún no se ha publicado; el flujo de GitHub Actions calcula
el hash del manifiesto automáticamente al construirla. Vea
[convenios-laborales/despliegue/README.md](convenios-laborales/despliegue/README.md) y la lista de
[pendientes](convenios-laborales/docs/INVENTARIO-FASE-5.md). La instalación con `instalar.sh` sigue
siendo la vía probada hasta que la fase 5 la retire.

Vea [convenios-laborales/README.md](convenios-laborales/README.md) para lo que hace el instalador, la instalación manual, límites y operación.
