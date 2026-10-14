"""Pruebas del manifiesto de despliegue autónomo (fase 3).

No requieren Docker: solo leen `despliegue/compose.yaml` y comprueban las invariantes que
debe cumplir el despliegue. La validación real de Compose se hace en CI.

Requieren PyYAML:  python3 -m pip install pyyaml
Ejecución:         python3 -m unittest discover -s convenios-laborales/tests -v
"""
import os
import re
import subprocess
import unittest
from pathlib import Path

import yaml

DESPLIEGUE = Path(__file__).resolve().parent.parent / 'despliegue'
COMPOSE = DESPLIEGUE / 'compose.yaml'
ENV_EJEMPLO = DESPLIEGUE / '.env.example'

# Valores presentes para poder interpolar el manifiesto en las pruebas.
ENTORNO = {
    'OPENPACTUM_VERSION': '0.0.0-pruebas',
    'POSTGRES_PASSWORD': 'pruebas',
    'PAPERLESS_SECRET_KEY': 'pruebas',
    'USERMAP_UID': '1000',
    'USERMAP_GID': '1000',
}
PATRON_VARIABLE = re.compile(r'\$\{([A-Z_][A-Z0-9_]*)(:[-?])?([^}]*)\}')


def interpolar(texto, entorno=None):
    """Interpolación mínima al estilo de Compose: ${VAR}, ${VAR:-defecto}, ${VAR:?error}."""
    valores = dict(ENTORNO)
    valores.update(entorno or {})
    # En Compose, `$$` escapa un dólar literal (lo consume el shell del contenedor).
    protegido = texto.replace('$$', '\x00')

    def sustituir(coincidencia):
        nombre, operador, valor = coincidencia.group(1), coincidencia.group(2), coincidencia.group(3)
        if nombre in valores:
            return valores[nombre]
        if operador == ':-':
            return valor
        raise AssertionError(f'Falta la variable {nombre} para interpolar el manifiesto')

    return PATRON_VARIABLE.sub(sustituir, protegido).replace('\x00', '$')


def cargar(entorno=None):
    return yaml.safe_load(interpolar(COMPOSE.read_text(encoding='utf-8'), entorno))


def texto_crudo():
    return COMPOSE.read_text(encoding='utf-8')


class ManifiestoTest(unittest.TestCase):
    def setUp(self):
        self.manifiesto = cargar()
        self.servicios = self.manifiesto['services']

    def test_define_todos_los_servicios_de_la_pila(self):
        self.assertEqual(
            sorted(self.servicios),
            ['anythingllm', 'changedetection', 'modelos', 'monitor', 'ollama', 'paperless',
             'postgres', 'programador', 'redis', 'secretos-init'],
        )

    def test_no_usa_la_clave_version_obsoleta(self):
        self.assertNotIn('version', self.manifiesto)

    def test_ninguna_imagen_usa_la_etiqueta_latest(self):
        for nombre, servicio in self.servicios.items():
            with self.subTest(servicio=nombre):
                self.assertNotRegex(servicio['image'], r':latest$')

    def test_los_puertos_se_publican_solo_en_localhost(self):
        publicados = [puerto for servicio in self.servicios.values()
                      for puerto in servicio.get('ports', [])]
        self.assertTrue(publicados)
        for puerto in publicados:
            with self.subTest(puerto=puerto):
                self.assertTrue(puerto.startswith('127.0.0.1:'), puerto)

    def test_ningun_servicio_publica_ollama(self):
        self.assertNotIn('ports', self.servicios['ollama'])

    def test_postgres_espera_al_healthcheck_antes_de_paperless(self):
        self.assertIn('healthcheck', self.servicios['postgres'])
        dependencia = self.servicios['paperless']['depends_on']['postgres']
        self.assertEqual(dependencia['condition'], 'service_healthy')

    def test_secretos_init_termina_antes_que_los_servicios_que_montan_datos(self):
        for nombre in ('changedetection', 'paperless', 'anythingllm', 'monitor', 'programador'):
            with self.subTest(servicio=nombre):
                dependencia = self.servicios[nombre]['depends_on']['secretos-init']
                self.assertEqual(dependencia['condition'], 'service_completed_successfully')

    def test_el_estado_del_monitor_no_vive_en_el_sistema_de_ficheros_del_contenedor(self):
        entorno = self.servicios['monitor']['environment']
        self.assertEqual(entorno['OPENPACTUM_ESTADO'], '/estado/estado-rss.json')
        self.assertEqual(entorno['OPENPACTUM_CONSUME'], '/consume')

    def test_el_monitor_escribe_con_el_mismo_usuario_que_paperless(self):
        # Ambos leen el mismo UID/GID, de forma que el monitor puede dejar PDF en el
        # directorio que Paperless comparte y retira.
        self.assertIn('user: "${USERMAP_UID:-1000}:${USERMAP_GID:-1000}"', texto_crudo())
        self.assertIn('USERMAP_UID: ${USERMAP_UID:-1000}', texto_crudo())
        self.assertEqual(self.servicios['monitor']['user'], '1000:1000')
        self.assertEqual(str(self.servicios['paperless']['environment']['USERMAP_UID']), '1000')

    def test_el_programador_repite_el_monitor_cada_seis_horas(self):
        programador = self.servicios['programador']
        self.assertEqual(programador['restart'], 'unless-stopped')
        orden = programador['command'][0]
        # 21600 s = 6 h, la misma cadencia que la tarea cron del host.
        self.assertIn('sleep 21600', orden)
        self.assertIn('monitor-convenios.py', orden)
        self.assertIn('sleep ${OPENPACTUM_INTERVALO:-21600}', texto_crudo())

    def test_el_monitor_de_ejecucion_manual_no_se_reinicia_solo(self):
        self.assertEqual(self.servicios['monitor']['restart'], 'no')

    def test_los_servicios_de_ejecucion_unica_no_se_reinician(self):
        for nombre in ('secretos-init', 'modelos'):
            with self.subTest(servicio=nombre):
                self.assertEqual(self.servicios[nombre]['restart'], 'no')

    def test_no_hay_nombres_de_contenedor_fijados(self):
        # container_name impide que el prefijo del proyecto se aplique y dificulta las copias.
        for nombre, servicio in self.servicios.items():
            with self.subTest(servicio=nombre):
                self.assertNotIn('container_name', servicio)

    def test_el_manifiesto_avisa_de_que_no_se_ha_probado_con_docker(self):
        self.assertIn('no se ha arrancado nunca con Docker real', texto_crudo())


class PrefijoTest(unittest.TestCase):
    def test_el_proyecto_usa_un_prefijo_configurable(self):
        self.assertIn('name: ${OPENPACTUM_PREFIJO:-openpactum}', texto_crudo())

    def test_el_prefijo_por_defecto_es_openpactum(self):
        manifiesto = cargar()
        self.assertEqual(manifiesto['name'], 'openpactum')
        for nombre, volumen in manifiesto['volumes'].items():
            with self.subTest(volumen=nombre):
                self.assertEqual(volumen['name'], f'openpactum_{nombre}')

    def test_los_volumenes_fijan_su_nombre_de_forma_explicita(self):
        # Sin `name:` explícito, Compose prefijaría los volúmenes con el nombre del proyecto y
        # cambiar el prefijo dejaría los datos anteriores huérfanos.
        crudo = texto_crudo()
        for nombre in ('redis_datos', 'postgres_datos', 'paperless_datos',
                       'paperless_media', 'ollama_datos'):
            with self.subTest(volumen=nombre):
                self.assertIn(f'name: ${{OPENPACTUM_PREFIJO:-openpactum}}_{nombre}', crudo)

    def test_cambiar_el_prefijo_renombra_proyecto_y_volumenes(self):
        manifiesto = cargar({'OPENPACTUM_PREFIJO': 'pacto-pruebas'})
        self.assertEqual(manifiesto['name'], 'pacto-pruebas')
        self.assertEqual(manifiesto['volumes']['postgres_datos']['name'], 'pacto-pruebas_postgres_datos')
        self.assertEqual(manifiesto['volumes']['ollama_datos']['name'], 'pacto-pruebas_ollama_datos')

    def test_los_datos_del_host_tambien_son_configurables(self):
        manifiesto = cargar({'OPENPACTUM_DATOS': '/tmp/openpactum-datos'})
        montajes = manifiesto['services']['changedetection']['volumes']
        self.assertEqual(montajes, ['/tmp/openpactum-datos/changedetection:/datastore'])


class ValidadorTest(unittest.TestCase):
    """El script de prueba local de la fase 3."""

    VALIDADOR = DESPLIEGUE / 'validar-despliegue.sh'

    def test_existe_y_es_ejecutable(self):
        self.assertTrue(self.VALIDADOR.is_file())
        self.assertTrue(os.access(self.VALIDADOR, os.X_OK))

    def test_sintaxis_posix_correcta(self):
        self.assertEqual(subprocess.run(['dash', '-n', str(self.VALIDADOR)],
                                        capture_output=True).returncode, 0)

    def test_documenta_sus_opciones(self):
        resultado = subprocess.run([str(self.VALIDADOR), '--ayuda'], capture_output=True, text=True)
        self.assertEqual(resultado.returncode, 0)
        for opcion in ('--sin-sintaxis', '--sin-pruebas', '--sin-docker'):
            self.assertIn(opcion, resultado.stdout)

    def test_rechaza_opciones_desconocidas(self):
        resultado = subprocess.run([str(self.VALIDADOR), '--inventada'], capture_output=True, text=True)
        self.assertEqual(resultado.returncode, 2)

    def test_comprueba_la_sintaxis_sin_docker(self):
        resultado = subprocess.run([str(self.VALIDADOR), '--sin-pruebas', '--sin-docker'],
                                   capture_output=True, text=True, cwd=str(DESPLIEGUE.parent.parent))
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn('Sintaxis de los scripts', resultado.stdout)


class DocumentacionTest(unittest.TestCase):
    LECTURA = DESPLIEGUE / 'README.md'

    def test_el_readme_documenta_la_prueba_local(self):
        texto = self.LECTURA.read_text(encoding='utf-8')
        self.assertIn('./despliegue/validar-despliegue.sh', texto)
        for opcion in ('--sin-sintaxis', '--sin-pruebas', '--sin-docker'):
            with self.subTest(opcion=opcion):
                self.assertIn(opcion, texto)

    def test_el_readme_no_promete_una_instalacion_probada(self):
        texto = self.LECTURA.read_text(encoding='utf-8')
        self.assertIn('sin probar con Docker real', texto)
        self.assertIn('nunca se han arrancado', texto)


class SecretosTest(unittest.TestCase):
    """Los secretos viven en un volumen que gestiona secretos-init, no en variables."""

    def setUp(self):
        self.manifiesto = cargar()
        self.servicios = self.manifiesto['services']

    def test_el_volumen_de_secretos_lleva_el_prefijo(self):
        self.assertIn('name: ${OPENPACTUM_PREFIJO:-openpactum}_secretos', texto_crudo())
        self.assertEqual(self.manifiesto['volumes']['secretos']['name'], 'openpactum_secretos')
        self.assertEqual(cargar({'OPENPACTUM_PREFIJO': 'otro'})['volumes']['secretos']['name'],
                         'otro_secretos')

    def test_secretos_init_monta_el_volumen_y_su_script(self):
        servicio = self.servicios['secretos-init']
        self.assertIn('secretos:/secretos', servicio['volumes'])
        # El script se monta desde el directorio del despliegue, que no tiene por qué ser el
        # directorio actual (el contenedor de arranque lo fija con OPENPACTUM_DESPLEGUE).
        self.assertIn('./secretos-init.sh:/usr/local/lib/openpactum/secretos-init.sh:ro',
                      servicio['volumes'])
        self.assertIn('- ${OPENPACTUM_DESPLEGUE:-.}/secretos-init.sh:/usr/local/lib/openpactum/'
                      'secretos-init.sh:ro', texto_crudo())
        # Necesita root para ajustar propietarios y permisos del árbol de datos.
        self.assertEqual(servicio['user'], '0:0')
        self.assertEqual(servicio['entrypoint'],
                         ['/bin/sh', '/usr/local/lib/openpactum/secretos-init.sh'])

    def test_el_script_de_secretos_existe_en_el_repositorio(self):
        self.assertTrue((DESPLIEGUE / 'secretos-init.sh').is_file())

    def test_postgres_lee_su_contrasena_del_volumen(self):
        postgres = self.servicios['postgres']
        self.assertEqual(postgres['environment']['POSTGRES_PASSWORD_FILE'],
                         '/run/secretos/postgres_password')
        self.assertIn('secretos:/run/secretos:ro', postgres['volumes'])
        self.assertNotIn('POSTGRES_PASSWORD', postgres['environment'])

    def test_paperless_carga_los_secretos_proyectados(self):
        # Su imagen no admite *_FILE: el volumen se proyecta a un fichero que carga Compose.
        paperless = self.servicios['paperless']
        self.assertEqual(paperless['env_file'], [{
            'path': '/var/lib/openpactum/datos/secretos/paperless.env',
            'required': False,
        }])
        self.assertIn('path: ${OPENPACTUM_DATOS:-/var/lib/openpactum/datos}/secretos/paperless.env',
                      texto_crudo())
        self.assertNotIn('PAPERLESS_DBPASS', paperless['environment'])
        self.assertNotIn('PAPERLESS_SECRET_KEY', paperless['environment'])

    def test_el_monitor_puede_leer_la_contrasena_smtp_del_volumen(self):
        self.assertIn('secretos:/run/secretos:ro', self.servicios['monitor']['volumes'])
        # Por defecto va vacío: se activa con SMTP_PASSWORD_FILE=/run/secretos/smtp_password.
        self.assertIn('SMTP_PASSWORD_FILE: ${SMTP_PASSWORD_FILE:-}', texto_crudo())
        self.assertIsNone(self.servicios['monitor']['environment']['SMTP_PASSWORD_FILE'])

    def test_el_ejemplo_explica_el_primer_arranque_en_dos_pasos(self):
        ejemplo = ENV_EJEMPLO.read_text(encoding='utf-8')
        self.assertIn('run --rm --no-deps secretos-init', ejemplo)
        self.assertIn('escribir smtp_password', ejemplo)
        self.assertNotRegex(ejemplo, r'(?m)^POSTGRES_PASSWORD=')
        self.assertNotRegex(ejemplo, r'(?m)^PAPERLESS_SECRET_KEY=')


class VariablesTest(unittest.TestCase):
    def test_las_variables_documentadas_aparecen_en_el_ejemplo(self):
        ejemplo = ENV_EJEMPLO.read_text(encoding='utf-8')
        for variable in ('OPENPACTUM_VERSION', 'OPENPACTUM_PROPIETARIO', 'OPENPACTUM_PREFIJO',
                         'OPENPACTUM_DATOS', 'OPENPACTUM_DESPLEGUE', 'USERMAP_UID', 'USERMAP_GID',
                         'MODELO', 'OPENPACTUM_INTERVALO', 'OPENPACTUM_RSS', 'SMTP_HOST'):
            with self.subTest(variable=variable):
                self.assertRegex(ejemplo, rf'(?m)^{re.escape(variable)}=')

    def test_la_unica_variable_obligatoria_es_la_etiqueta_del_monitor(self):
        crudo = texto_crudo()
        self.assertIn('${OPENPACTUM_VERSION:?', crudo)
        # Los secretos no se piden por variable de entorno: los genera secretos-init.
        self.assertNotIn('${POSTGRES_PASSWORD', crudo)
        self.assertNotIn('${PAPERLESS_SECRET_KEY', crudo)

    def test_el_ejemplo_no_contiene_secretos_reales(self):
        ejemplo = ENV_EJEMPLO.read_text(encoding='utf-8')
        for linea in ejemplo.splitlines():
            if linea.startswith(('POSTGRES_PASSWORD=', 'PAPERLESS_SECRET_KEY=')):
                self.assertRegex(linea, r'=CAMBIAR_CON_')


if __name__ == '__main__':
    unittest.main()
