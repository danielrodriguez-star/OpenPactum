"""Bootstrap idempotente del administrador y las etiquetas predeterminadas de Paperless."""
import os
from pathlib import Path

from django.contrib.auth.models import User
from documents.models import Tag

usuario = os.environ.get('OPENPACTUM_PAPERLESS_ADMIN', 'admin')
contrasena = Path('/run/secretos-admin/paperless_admin_password').read_text(
    encoding='utf-8',
).rstrip('\r\n')
if not contrasena:
    raise RuntimeError('El secreto de contraseña del administrador de Paperless está vacío.')

administrador = User.objects.filter(username=usuario).first()
if administrador is None:
    administrador = User.objects.create_superuser(usuario, '', contrasena)
    ruta_credenciales = Path('/datos/paperless/credenciales.txt')
    contenido = (
        'Paperless (http://localhost:8000)\n'
        f'usuario: {usuario}\n'
        f'contraseña: {contrasena}\n'
        'Cambie esta contraseña después del primer acceso.\n'
    )
    if ruta_credenciales.exists():
        if ruta_credenciales.read_text(encoding='utf-8') != contenido:
            raise RuntimeError(
                f'No se sobrescriben credenciales existentes: {ruta_credenciales}'
            )
    else:
        descriptor = os.open(
            ruta_credenciales,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, 'w', encoding='utf-8') as fichero:
            fichero.write(contenido)
    print(f"Administrador '{usuario}' creado; credenciales guardadas con permisos 0600.")
else:
    print(f"Administrador '{usuario}' ya existía; no se modificó su contraseña.")

for nombre in (
    'convenio-estatal',
    'convenio-autonomico',
    'convenio-provincial',
    'convenio-empresa',
    'tabla-salarial',
    'revision-salarial',
    'vigente',
    'derogado',
):
    etiqueta, creada = Tag.objects.get_or_create(name=nombre)
    if creada:
        print(f'Etiqueta creada: {etiqueta.name}')
