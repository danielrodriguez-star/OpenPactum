"""Pruebas de `despliegue/secretos-init.sh` (fase 3), sin Docker ni privilegios de root.

El script se ejecuta con `sh` (POSIX) sobre directorios temporales que hacen de volumen de
secretos y de árbol de datos.
"""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / 'despliegue' / 'secretos-init.sh'


def ejecutar(*argumentos, secretos, datos, entrada=None):
    secretos_admin = secretos.parent / f'{secretos.name}_admin'
    entorno = dict(
        os.environ,
        OPENPACTUM_SECRETOS_DIR=str(secretos),
        OPENPACTUM_SECRETOS_ADMIN_DIR=str(secretos_admin),
        OPENPACTUM_DATOS_DIR=str(datos),
        USERMAP_UID='1000',
        USERMAP_GID='1000',
    )
    return subprocess.run(['sh', str(SCRIPT), *argumentos], env=entorno, input=entrada,
                          capture_output=True, text=True)


class GenerarTest(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temporal.name)
        self.secretos = self.raiz / 'secretos'
        self.datos = self.raiz / 'datos'

    def tearDown(self):
        self.temporal.cleanup()

    def generar(self, *argumentos, entrada=None):
        return ejecutar(*argumentos, secretos=self.secretos, datos=self.datos, entrada=entrada)

    def test_crea_los_secretos_del_despliegue(self):
        resultado = self.generar()
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        secretos_admin = self.secretos.parent / f'{self.secretos.name}_admin'
        self.assertEqual(sorted(p.name for p in self.secretos.iterdir()),
                         ['paperless_secret_key', 'postgres_password'])
        self.assertEqual(sorted(p.name for p in secretos_admin.iterdir()), ['paperless_admin_password'])

    def test_los_secretos_son_aleatorios_y_distintos_entre_si(self):
        self.generar()
        contrasena = (self.secretos / 'postgres_password').read_text()
        clave = (self.secretos / 'paperless_secret_key').read_text()
        admin = (self.secretos.parent / f'{self.secretos.name}_admin' /
                 'paperless_admin_password').read_text()
        self.assertGreaterEqual(len(contrasena), 60)
        self.assertNotEqual(contrasena, clave)
        self.assertNotIn(admin, (contrasena, clave))
        self.assertNotIn('\n', contrasena)

        # Dos ejecuciones en volúmenes distintos tienen que dar valores distintos.
        with tempfile.TemporaryDirectory() as otro:
            ejecutar(secretos=Path(otro) / 'secretos', datos=Path(otro) / 'datos')
            self.assertNotEqual(contrasena, (Path(otro) / 'secretos' / 'postgres_password').read_text())

    def test_no_sobrescribe_los_secretos_existentes(self):
        self.generar()
        antes = (self.secretos / 'postgres_password').read_text()
        resultado = self.generar()
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual((self.secretos / 'postgres_password').read_text(), antes)
        self.assertIn('conservado: postgres_password', resultado.stdout)

    def test_no_imprime_ningun_secreto(self):
        resultado = self.generar()
        contrasena = (self.secretos / 'postgres_password').read_text()
        clave = (self.secretos / 'paperless_secret_key').read_text()
        secreto_admin = (self.secretos.parent / f'{self.secretos.name}_admin' /
                         'paperless_admin_password').read_text()
        for secreto in (contrasena, clave, secreto_admin):
            self.assertNotIn(secreto, resultado.stdout + resultado.stderr)

    def test_los_secretos_no_son_legibles_por_todos(self):
        self.generar()
        for fichero in (self.secretos / 'postgres_password', self.secretos / 'paperless_secret_key',
                        self.secretos.parent / f'{self.secretos.name}_admin' /
                        'paperless_admin_password'):
            with self.subTest(fichero=fichero.name):
                self.assertEqual(stat.S_IMODE(fichero.stat().st_mode), 0o640)

    def test_proyecta_los_secretos_para_paperless(self):
        self.generar()
        proyeccion = self.datos / 'secretos' / 'paperless.env'
        contenido = dict(linea.split('=', 1) for linea in
                         proyeccion.read_text().splitlines() if linea)
        self.assertEqual(sorted(contenido), ['PAPERLESS_DBPASS', 'PAPERLESS_SECRET_KEY'])
        self.assertEqual(contenido['PAPERLESS_DBPASS'], (self.secretos / 'postgres_password').read_text())
        self.assertEqual(contenido['PAPERLESS_SECRET_KEY'], (self.secretos / 'paperless_secret_key').read_text())
        self.assertEqual(stat.S_IMODE(proyeccion.stat().st_mode), 0o640)

    def test_proyecta_valores_sin_espacios_ni_caracteres_que_rompan_el_env(self):
        self.generar()
        for linea in (self.datos / 'secretos' / 'paperless.env').read_text().splitlines():
            valor = linea.split('=', 1)[1]
            with self.subTest(linea=linea.split('=', 1)[0]):
                self.assertNotIn(' ', valor)
                self.assertNotIn('#', valor)

    def test_prepara_el_arbol_de_datos(self):
        self.generar()
        for directorio in ('changedetection', 'paperless/consume', 'paperless/export',
                           'anythingllm', 'monitor/estado', 'secretos'):
            with self.subTest(directorio=directorio):
                self.assertTrue((self.datos / directorio).is_dir())

    def test_crea_el_fichero_de_configuracion_de_anythingllm_sin_pisar_lo_que_haya(self):
        self.datos.mkdir(parents=True)
        (self.datos / 'anythingllm').mkdir()
        (self.datos / 'anythingllm' / '.env').write_text('LLM_PROVIDER=ollama\n')
        self.generar()
        self.assertEqual((self.datos / 'anythingllm' / '.env').read_text(), 'LLM_PROVIDER=ollama\n')
        (self.datos / 'anythingllm' / '.env').unlink()
        self.generar()
        self.assertTrue((self.datos / 'anythingllm' / '.env').is_file())

    def test_sin_root_avisa_y_no_falla(self):
        # Las pruebas no corren como root: el script debe seguir adelante avisando.
        resultado = self.generar()
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        if os.geteuid() != 0:
            self.assertIn('sin privilegios de root', resultado.stdout)


class EscribirTest(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temporal.name)
        self.secretos = self.raiz / 'secretos'
        self.datos = self.raiz / 'datos'

    def tearDown(self):
        self.temporal.cleanup()

    def test_guarda_el_valor_leido_de_la_entrada_estandar(self):
        resultado = ejecutar('escribir', 'smtp_password', secretos=self.secretos, datos=self.datos,
                             entrada='clave-smtp')
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual((self.secretos / 'smtp_password').read_text(), 'clave-smtp')
        self.assertNotIn('clave-smtp', resultado.stdout)

    def test_exige_el_nombre_del_secreto(self):
        resultado = ejecutar('escribir', secretos=self.secretos, datos=self.datos, entrada='x')
        self.assertEqual(resultado.returncode, 2)
        self.assertIn('Uso:', resultado.stderr)


class InterfazTest(unittest.TestCase):
    def test_ayuda_y_subcomando_desconocido(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            ayuda = ejecutar('--ayuda', secretos=raiz / 's', datos=raiz / 'd')
            self.assertEqual(ayuda.returncode, 0)
            self.assertIn('escribir NOMBRE', ayuda.stdout)
            desconocido = ejecutar('inventado', secretos=raiz / 's', datos=raiz / 'd')
            self.assertEqual(desconocido.returncode, 2)
            self.assertIn('no reconocido', desconocido.stderr)

    def test_sintaxis_posix_correcta(self):
        self.assertEqual(subprocess.run(['dash', '-n', str(SCRIPT)], capture_output=True).returncode, 0)

    def test_es_idempotente_al_reejecutarlo_sobre_su_propia_salida(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            primera = ejecutar(secretos=raiz / 's', datos=raiz / 'd')
            segunda = ejecutar(secretos=raiz / 's', datos=raiz / 'd')
            self.assertEqual((primera.returncode, segunda.returncode), (0, 0))
            self.assertNotIn('generado:', segunda.stdout)


if __name__ == '__main__':
    unittest.main()
