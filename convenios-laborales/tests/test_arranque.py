"""Pruebas del contenedor de arranque (fase 4), sin Docker ni red.

`arranque/arrancar.sh` se ejecuta con `docker` y `curl` falsos delante en el PATH: así se
comprueba el orden de las órdenes, la verificación del manifiesto y los ficheros que crea.
"""
import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent.parent
CONVENIOS = RAIZ_REPO / 'convenios-laborales'
ARRANQUE = CONVENIOS / 'arranque'
DESPLIEGUE = CONVENIOS / 'despliegue'
SCRIPT = ARRANQUE / 'arrancar.sh'

DOCKER_FALSO = """#!/bin/sh
printf 'docker %s\\n' "$*" >> "$REGISTRO"
if [ "${DOCKER_FALLA:-0}" = 1 ]; then
  exit 1
fi
case "$1" in
  version) echo "27.0.0" ;;
esac
exit 0
"""

# Copia el fichero indicado en CURL_ORIGEN al destino de `-o`, como haría curl.
CURL_FALSO = """#!/bin/sh
destino=""
anterior=""
for argumento in "$@"; do
  if [ "$anterior" = "-o" ]; then destino="$argumento"; fi
  anterior="$argumento"
done
if [ -z "${CURL_ORIGEN:-}" ] || [ ! -f "${CURL_ORIGEN:-}" ]; then
  exit 22
fi
cp "$CURL_ORIGEN" "$destino"
"""


class ArranqueTest(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temporal.name)
        self.lib = self.raiz / 'lib'
        self.bin = self.raiz / 'bin'
        self.trabajo = self.raiz / 'trabajo'
        self.registro = self.raiz / 'registro.txt'
        for directorio in (self.lib, self.bin):
            directorio.mkdir()
        self.manifiesto = (DESPLIEGUE / 'compose.yaml').read_bytes()
        self.hash = hashlib.sha256(self.manifiesto).hexdigest()
        # Lib dentro de la imagen: el script de secretos y el ejemplo de entorno.
        shutil.copy(DESPLIEGUE / 'secretos-init.sh', self.lib / 'secretos-init.sh')
        shutil.copy(DESPLIEGUE / '.env.example', self.lib / 'ejemplo.env')
        self.manifiesto_falso = self.raiz / 'falso.yaml'
        self.manifiesto_falso.write_bytes(self.manifiesto)
        self._crear_stubs()

    def tearDown(self):
        self.temporal.cleanup()

    def _crear_stubs(self):
        for nombre, contenido in (('docker', DOCKER_FALSO), ('curl', CURL_FALSO)):
            ruta = self.bin / nombre
            ruta.write_text(contenido)
            ruta.chmod(0o755)

    def ejecutar(self, *orden, hash_manifiesto=None, curl_origen=None, docker_falla=False,
                 extra=None):
        url = self.manifiesto_falso if curl_origen is None else curl_origen
        entorno = {
            'PATH': f'{self.bin}:/usr/bin:/bin',
            'HOME': str(self.raiz),
            'REGISTRO': str(self.registro),
            'DOCKER_FALLA': '1' if docker_falla else '0',
            'CURL_ORIGEN': str(url) if url is not None else '',
            'OPENPACTUM_RAIZ': str(self.trabajo),
            'OPENPACTUM_LIB': str(self.lib),
            'OPENPACTUM_URL_MANIFIESTO': 'https://ejemplo.test/despliegue/compose.yaml',
            'OPENPACTUM_COMPOSE_SHA256': self.hash if hash_manifiesto is None else hash_manifiesto,
            'OPENPACTUM_VERSION': '0.0.0-pruebas',
        }
        entorno.update(extra or {})
        return subprocess.run(['sh', str(SCRIPT), *orden], env=entorno,
                              capture_output=True, text=True)

    @property
    def ordenes(self):
        if not self.registro.exists():
            return []
        return [linea.strip() for linea in self.registro.read_text().splitlines() if linea.strip()]

    def ordenes_de_compose(self):
        return [linea for linea in self.ordenes if linea.startswith('docker compose')]

    def ruta(self, *partes):
        return self.trabajo.joinpath(*partes)

    # --- Puesta en marcha -------------------------------------------------------------

    def test_arriba_descarga_verifica_y_arranca(self):
        resultado = self.ejecutar('arriba')
        self.assertEqual(resultado.returncode, 0, resultado.stderr + resultado.stdout)
        self.assertEqual(self.ruta('despliegue', 'compose.yaml').read_bytes(), self.manifiesto)
        self.assertIn('manifiesto descargado y verificado', resultado.stdout)

    def test_los_secretos_se_preparan_antes_de_arrancar_la_pila(self):
        resultado = self.ejecutar('arriba')
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        compose = self.ordenes_de_compose()
        preparar = next(i for i, o in enumerate(compose) if 'run --rm --no-deps secretos-init' in o)
        arrancar = next(i for i, o in enumerate(compose) if o.endswith('up -d'))
        self.assertLess(preparar, arrancar)
        self.assertEqual(compose[arrancar], self.ordenes_de_compose()[arrancar])

    def test_las_ordenes_de_compose_llevan_el_directorio_y_el_entorno(self):
        self.ejecutar('arriba')
        for orden in self.ordenes_de_compose():
            with self.subTest(orden=orden):
                self.assertIn(f'--project-directory {self.ruta("despliegue")}', orden)
                self.assertIn(f'--env-file {self.ruta("despliegue", ".env")}', orden)
                self.assertIn(f'-f {self.ruta("despliegue", "compose.yaml")}', orden)

    def test_crea_el_fichero_de_entorno_con_las_rutas_de_este_despliegue(self):
        self.ejecutar('arriba')
        entorno = self.ruta('despliegue', '.env')
        contenido = entorno.read_text()
        self.assertIn(f'OPENPACTUM_DATOS={self.trabajo}/datos', contenido)
        self.assertIn(f'OPENPACTUM_DESPLEGUE={self.trabajo}/despliegue', contenido)
        self.assertIn('OPENPACTUM_VERSION=0.0.0-pruebas', contenido)
        self.assertEqual(stat.S_IMODE(entorno.stat().st_mode), 0o600)

    def test_no_pisa_el_fichero_de_entorno_existente(self):
        destino = self.ruta('despliegue')
        destino.mkdir(parents=True)
        (destino / '.env').write_text('OPENPACTUM_MODELO=qwen2.5:7b\n')
        self.ejecutar('arriba')
        self.assertEqual((destino / '.env').read_text(), 'OPENPACTUM_MODELO=qwen2.5:7b\n')

    def test_copia_el_script_de_secretos_que_lleva_dentro_la_imagen(self):
        self.ejecutar('arriba')
        copia = self.ruta('despliegue', 'secretos-init.sh')
        self.assertEqual(copia.read_bytes(), (self.lib / 'secretos-init.sh').read_bytes())

    def test_comprueba_que_el_motor_de_docker_responde(self):
        resultado = self.ejecutar('arriba', docker_falla=True)
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn('socket', resultado.stderr)
        self.assertEqual(self.ordenes_de_compose(), [])

    # --- Verificación del manifiesto --------------------------------------------------

    def test_rechaza_un_manifiesto_que_no_coincide_con_el_hash(self):
        otro = self.raiz / 'otro.yaml'
        otro.write_text('services: {}\n')
        resultado = self.ejecutar('arriba', curl_origen=otro)
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn('no coincide con COMPOSE_SHA256', resultado.stderr)
        self.assertFalse(self.ruta('despliegue', 'compose.yaml').exists())
        self.assertEqual(self.ordenes_de_compose(), [])

    def test_no_arranca_nada_si_la_imagen_no_tiene_hash(self):
        resultado = self.ejecutar('arriba', hash_manifiesto='')
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn('COMPOSE_SHA256', resultado.stderr)
        self.assertEqual(self.ordenes_de_compose(), [])

    def test_sin_conexion_reutiliza_la_copia_verificada(self):
        destino = self.ruta('despliegue')
        destino.mkdir(parents=True)
        (destino / 'compose.yaml').write_bytes(self.manifiesto)
        resultado = self.ejecutar('arriba', curl_origen=None, extra={'CURL_ORIGEN': ''})
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn('se reutiliza la copia guardada', resultado.stdout)

    def test_sin_conexion_y_sin_copia_falla(self):
        resultado = self.ejecutar('arriba', extra={'CURL_ORIGEN': ''})
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn('no se pudo descargar', resultado.stderr)

    # --- Órdenes ----------------------------------------------------------------------

    def test_estado_lista_los_servicios(self):
        self.ejecutar('estado')
        self.assertTrue(self.ordenes_de_compose()[-1].endswith(' ps'))

    def test_abajo_retira_los_contenedores_sin_tocar_los_volumenes(self):
        resultado = self.ejecutar('abajo')
        self.assertTrue(self.ordenes_de_compose()[-1].endswith(' down'))
        self.assertIn('volúmenes', resultado.stdout)

    def test_monitor_ejecuta_el_monitor_una_vez(self):
        self.ejecutar('monitor')
        self.assertTrue(self.ordenes_de_compose()[-1].endswith(' run --rm monitor'))

    def test_actualizar_descarga_imagenes_y_reinicia(self):
        self.ejecutar('actualizar')
        compose = self.ordenes_de_compose()
        descargar = next(i for i, o in enumerate(compose) if o.endswith(' pull'))
        reiniciar = next(i for i, o in enumerate(compose) if o.endswith(' up -d'))
        self.assertLess(descargar, reiniciar)
        self.assertTrue(compose[-1].endswith(' ps'))

    def test_ayuda_y_orden_desconocida(self):
        ayuda = self.ejecutar('ayuda')
        self.assertEqual(ayuda.returncode, 0)
        for orden in ('arriba', 'abajo', 'estado', 'registros', 'monitor', 'actualizar'):
            with self.subTest(orden=orden):
                self.assertIn(orden, ayuda.stdout)
        desconocida = self.ejecutar('inventada')
        self.assertEqual(desconocida.returncode, 2)

    def test_version_muestra_el_hash_esperado(self):
        resultado = self.ejecutar('version')
        self.assertEqual(resultado.returncode, 0)
        self.assertIn(self.hash, resultado.stdout)

    # --- Coherencia con la imagen y la CI ---------------------------------------------

    def test_sintaxis_posix_y_ash(self):
        for interprete in (['dash'], ['busybox', 'sh']):
            if shutil.which(interprete[0]) is None:
                continue
            with self.subTest(interprete=interprete[0]):
                self.assertEqual(subprocess.run([*interprete, '-n', str(SCRIPT)],
                                                capture_output=True).returncode, 0)

    def test_el_dockerfile_instala_lo_necesario_y_copia_lo_que_existe(self):
        dockerfile = (ARRANQUE / 'Dockerfile').read_text()
        for paquete in ('docker-cli', 'docker-cli-compose', 'curl', 'ca-certificates'):
            with self.subTest(paquete=paquete):
                self.assertIn(paquete, dockerfile)
        self.assertIn('OPENPACTUM_COMPOSE_SHA256', dockerfile)
        self.assertIn('ENTRYPOINT ["/bin/sh", "/usr/local/lib/openpactum/arrancar.sh"]', dockerfile)
        # El contexto de construcción es convenios-laborales/: los COPY tienen que existir.
        for origen in ('arranque/arrancar.sh', 'despliegue/secretos-init.sh',
                       'despliegue/.env.example'):
            with self.subTest(origen=origen):
                self.assertIn(f'COPY {origen}', dockerfile)
                self.assertTrue((CONVENIOS / origen).is_file(), origen)

    def test_el_dockerfile_usa_la_misma_ruta_de_lib_que_el_script(self):
        dockerfile = (ARRANQUE / 'Dockerfile').read_text()
        for fichero in ('arrancar.sh', 'secretos-init.sh', 'ejemplo.env'):
            with self.subTest(fichero=fichero):
                self.assertIn(f'/usr/local/lib/openpactum/{fichero}', dockerfile)
        # El script busca ahí sus ficheros si no se le dice otra cosa.
        self.assertIn('${OPENPACTUM_LIB:-/usr/local/lib/openpactum}', SCRIPT.read_text())

    def test_la_imagen_no_se_construye_sin_la_variable_compose_sha256(self):
        workflow = (RAIZ_REPO / '.github' / 'workflows' / 'arranque-imagen.yml').read_text()
        self.assertIn("if: vars.COMPOSE_SHA256 != ''", workflow)
        self.assertIn('OPENPACTUM_COMPOSE_SHA256=${{ vars.COMPOSE_SHA256 }}', workflow)
        self.assertIn('sha256sum convenios-laborales/despliegue/compose.yaml', workflow)


class DocumentacionArranqueTest(unittest.TestCase):
    """El README del despliegue tiene que explicar el arranque y su riesgo."""

    def texto(self):
        # El markdown parte las frases en varias líneas: se comparan en una sola línea.
        return ' '.join((DESPLIEGUE / 'README.md').read_text(encoding='utf-8').split())

    def test_el_readme_documenta_el_contenedor_de_arranque(self):
        texto = self.texto()
        self.assertIn('openpactum-arranque', texto)
        self.assertIn('-v /var/run/docker.sock:/var/run/docker.sock', texto)
        self.assertIn('arriba', texto)

    def test_el_readme_avisa_del_riesgo_del_socket(self):
        self.assertIn('control total del equipo anfitrión', self.texto())

    def test_el_readme_dice_que_ya_no_hay_imagen_publicada_sin_la_variable(self):
        self.assertIn('Todavía no hay imagen publicada', self.texto())


if __name__ == '__main__':
    unittest.main()
