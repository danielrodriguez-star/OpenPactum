"""Pruebas del monitor del BOE sin red ni SMTP.

Ejecución: python3 -m unittest discover -s convenios-laborales/tests -v
"""
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'monitor-convenios.py'
FUENTES = Path(__file__).resolve().parent.parent / 'scripts' / 'fuentes-rss.txt'
CANAL_BOE = 'https://www.boe.es/rss/canal.php?c=ccolectivos'
# Respuesta del canal temático de convenios del BOE. El tercer elemento no es un convenio y
# no debería estar en el canal: sirve para comprobar la red de seguridad del filtro.
RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Resolucion por la que se registra el convenio colectivo de ejemplo</title>
    <link>https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-1001</link>
    <description>Convenio colectivo de empresa</description>
    <pubDate>Tue, 13 Oct 2026 06:00:00 +0200</pubDate>
  </item>
  <item>
    <title>Orden sobre otra materia</title>
    <link>https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-1002</link>
    <description>Sin relacion</description>
    <pubDate>Tue, 13 Oct 2026 06:00:00 +0200</pubDate>
  </item>
  <item>
    <title>Convenio colectivo con enlace ajeno</title>
    <link>https://evil.example.com/?id=BOE-A-2026-1003</link>
    <description>convenio colectivo</description>
    <pubDate>Tue, 13 Oct 2026 06:00:00 +0200</pubDate>
  </item>
</channel></rss>
"""


def cargar_modulo(entorno):
    """Carga el script con las variables de entorno indicadas (las rutas se leen al importar)."""
    antiguo = {k: os.environ.get(k) for k in entorno}
    try:
        for k, v in entorno.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        spec = importlib.util.spec_from_file_location(
            f'monitor_{id(entorno)}', SCRIPT)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo
    finally:
        for k, v in antiguo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class RutasTest(unittest.TestCase):
    def test_rutas_por_defecto_conservan_la_instalacion_con_checkout(self):
        m = cargar_modulo({'OPENPACTUM_ESTADO': None, 'OPENPACTUM_CONSUME': None})
        self.assertEqual(m.STATE.parts[-2:], ('scripts', '.estado-rss.json'))
        self.assertEqual(m.CONSUME.parts[-2:], ('paperless', 'consume'))

    def test_rutas_configurables_por_entorno(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = cargar_modulo({
                'OPENPACTUM_ESTADO': str(Path(tmp) / 'estado' / 'rss.json'),
                'OPENPACTUM_CONSUME': str(Path(tmp) / 'consume'),
            })
            self.assertEqual(m.STATE, Path(tmp) / 'estado' / 'rss.json')
            self.assertEqual(m.CONSUME, Path(tmp) / 'consume')


class CanalTest(unittest.TestCase):
    def test_usa_el_canal_de_convenios_colectivos_del_boe(self):
        m = cargar_modulo({'OPENPACTUM_RSS': None})
        self.assertEqual(m.RSS, CANAL_BOE)

    def test_canal_configurable_por_entorno(self):
        m = cargar_modulo({'OPENPACTUM_RSS': 'https://boletin.ejemplo.test/rss.xml'})
        self.assertEqual(m.RSS, 'https://boletin.ejemplo.test/rss.xml')

    def test_el_canal_por_defecto_esta_documentado_en_fuentes_rss(self):
        self.assertIn(CANAL_BOE, FUENTES.read_text(encoding='utf-8'))


class ContrasenaSmtpTest(unittest.TestCase):
    def test_lee_fichero_y_quita_salto_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            fichero = Path(tmp) / 'smtp_password'
            fichero.write_text('secreto-123\n', encoding='utf-8')
            m = cargar_modulo({})
            with mock.patch.dict(os.environ, {'SMTP_PASSWORD_FILE': str(fichero), 'SMTP_PASSWORD': 'otra'}):
                self.assertEqual(m.smtp_password(), 'secreto-123')

    def test_usa_variable_si_no_hay_fichero(self):
        m = cargar_modulo({})
        with mock.patch.dict(os.environ, {'SMTP_PASSWORD': 'desde-variable'}, clear=False):
            os.environ.pop('SMTP_PASSWORD_FILE', None)
            self.assertEqual(m.smtp_password(), 'desde-variable')


class FlujoTest(unittest.TestCase):
    def _ejecutar(self, m, pdf_bytes=b'%PDF-1.4 contenido'):
        urls = []

        def falso_fetch(url):
            urls.append(url)
            return RSS_XML if url == m.RSS else pdf_bytes

        with mock.patch.object(m, 'fetch', side_effect=falso_fetch), \
                mock.patch.dict(os.environ, {'SMTP_HOST': ''}):
            m.main()
        return urls

    def test_descarga_solo_convenios_validos_y_no_repite(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = cargar_modulo({
                'OPENPACTUM_ESTADO': str(Path(tmp) / 'estado' / 'rss.json'),
                'OPENPACTUM_CONSUME': str(Path(tmp) / 'consume'),
            })
            urls = self._ejecutar(m)
            pdfs = sorted(p.name for p in (Path(tmp) / 'consume').iterdir())
            self.assertEqual(pdfs, ['BOE-A-2026-1001.pdf'])
            self.assertTrue(any(u.endswith('/BOE-A-2026-1001.pdf') for u in urls))
            self.assertFalse(any('evil.example.com' in u for u in urls))
            estado = json.loads((Path(tmp) / 'estado' / 'rss.json').read_text())
            self.assertEqual(estado, ['BOE-A-2026-1001'])

            # Segunda ejecución: no vuelve a descargar lo ya procesado.
            urls2 = self._ejecutar(m)
            self.assertEqual([u for u in urls2 if u.endswith('.pdf')], [])
            estado_modificado = (Path(tmp) / 'estado' / 'rss.json').stat().st_mtime
            self.assertGreater(estado_modificado, 0)

    def test_rechaza_respuesta_que_no_es_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = cargar_modulo({
                'OPENPACTUM_ESTADO': str(Path(tmp) / 'rss.json'),
                'OPENPACTUM_CONSUME': str(Path(tmp) / 'consume'),
            })
            with self.assertRaises(ValueError):
                self._ejecutar(m, pdf_bytes=b'<html>error</html>')
            self.assertEqual(list((Path(tmp) / 'consume').glob('*.pdf')), [])

    def test_actualiza_fecha_del_estado_en_una_ejecucion_sin_novedades(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = cargar_modulo({
                'OPENPACTUM_ESTADO': str(Path(tmp) / 'rss.json'),
                'OPENPACTUM_CONSUME': str(Path(tmp) / 'consume'),
            })
            self._ejecutar(m)
            estado = Path(tmp) / 'rss.json'
            os.utime(estado, (1, 1))
            self._ejecutar(m)
            self.assertGreater(estado.stat().st_mtime, 1)


if __name__ == '__main__':
    unittest.main()
