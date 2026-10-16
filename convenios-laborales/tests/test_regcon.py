"""Pruebas del puente de consulta a REGCON sin acceso a Internet."""
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'openpactum_regcon.py'
SPEC = importlib.util.spec_from_file_location('openpactum_regcon_test', SCRIPT)
REGCON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGCON)


def pagina_resultados(record_id, code, title, date_range, action='Expediente'):
    return f"""<html><form id="gestionAcuerdos"><input type="hidden" name="token" value="abc"></form>
    <table summary="Tramites"><tbody><tr>
      <td>{code}</td><td>{title}</td><td>CONVENIO COLECTIVO (TEXTO NUEVO)</td>
      <td>Barcelona</td><td>12/01/2026</td><td>{date_range}</td><td>31/12/2026</td>
      <td><button name="_ver{action}{record_id}">Ver</button></td>
    </tr></tbody></table>
    <p>Resultados1 - 15&nbsp;de&nbsp;16</p>
    <a href="?pagina=2">Ultimo</a></html>"""


class RegconTest(TestCase):
    @classmethod
    def setUpClass(cls):
        class FakeRegcon(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _reply(self, content, cookie=False):
                encoded = content.encode('utf-8')
                self.send_response(200)
                if cookie:
                    self.send_header('Set-Cookie', 'SESSION=test; Path=/')
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_GET(self):
                if self.path.endswith('pagina=2'):
                    self._reply(pagina_resultados(
                        '43', '08001234012026', 'Convenio de pruebas página dos', '01/02/2026',
                        action='Apunte'))
                else:
                    self._reply(
                        '<form id="busquedaAcuerdos"><input type="hidden" '
                        'name="_esNuevaBusqueda" value="1"><select name="autoridadLaboral">'
                        '<option value="8">Barcelona</option><option value="63">Estatal</option>'
                        '</select></form>',
                        cookie=True,
                    )

            def do_POST(self):
                length = int(self.headers.get('Content-Length', '0'))
                fields = parse_qs(self.rfile.read(length).decode('utf-8'), keep_blank_values=True)
                if '_buscar' in fields:
                    self.server.last_authority = fields.get('autoridadLaboral', [''])[0]
                    self._reply(pagina_resultados(
                        '42', '08001234012025', 'Convenio de pruebas', '01/01/2026'))
                elif '_verExpediente42' in fields:
                    scheme = getattr(self.server, 'publication_scheme', 'https')
                    self._reply(
                        '<form id="expediente"></form>'
                        '<p>Para acceder a la publicación del expediente pulse en el siguiente enlace:</p>'
                        f'<a href="{scheme}://boppo.depo.gal/es/anuncio/123">Publicación oficial</a>'
                    )
                else:
                    self.send_error(400)

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), FakeRegcon)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/regcon/pub/consultaPublicaEstatal'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_busca_y_parsea_registros_nacionales_y_paginacion(self):
        with patch.object(REGCON, 'REGCON_URL', self.url), \
                patch.object(REGCON, 'REGCON_HOST', '127.0.0.1'):
            result = REGCON.search('query', 'convenio de pruebas', 1)
            second_page = REGCON.search('query', 'convenio de pruebas', 2)

        self.assertEqual(result['total'], 16)
        self.assertEqual(result['pages'], 2)
        self.assertEqual(result['results'][0]['code'], '08001234012025')
        self.assertEqual(result['results'][0]['denomination'], 'Convenio de pruebas')
        self.assertEqual(result['results'][0]['authority'], 'Barcelona')
        self.assertEqual(second_page['results'][0]['record_id'], '43')
        self.assertFalse(second_page['results'][0]['publication_available'])

    def test_expone_autoridades_de_la_lista_publica_de_regcon(self):
        with patch.object(REGCON, 'REGCON_URL', self.url), \
                patch.object(REGCON, 'REGCON_HOST', '127.0.0.1'):
            result = REGCON.authorities()
        self.assertEqual(result['source'], 'REGCON')
        self.assertTrue(result['checked_at'])
        self.assertEqual(result['historical_url'], REGCON.REGCON_HISTORICAL_URL)
        self.assertIn(
            {'code': '8', 'name': 'Barcelona'},
            result['authorities'],
        )
        self.assertIn({'code': '63', 'name': 'Estatal'}, result['authorities'])

    def test_filtra_busqueda_por_autoridad_seleccionada(self):
        with patch.object(REGCON, 'REGCON_URL', self.url), \
                patch.object(REGCON, 'REGCON_HOST', '127.0.0.1'):
            result = REGCON.search('query', 'convenio de pruebas', 1, authority='8')
        self.assertEqual(result['authority_filter'], '8')
        self.assertEqual(self.server.last_authority, '8')

    def test_rechaza_codigo_de_autoridad_con_formato_invalido(self):
        with patch.object(REGCON, 'REGCON_URL', self.url), \
                patch.object(REGCON, 'REGCON_HOST', '127.0.0.1'):
            with self.assertRaises(ValueError):
                REGCON.search('query', 'convenio', authority='8&admin=true')

    def test_parsea_todos_los_tramites_incluidos_los_apuntes(self):
        rows = []
        actions = ['Expediente', 'Apunte'] * 7 + [None]
        for index, action in enumerate(actions, start=1):
            button = f'<button name="_ver{action}{index}">Ver</button>' if action else ''
            rows.append(
                f'<tr><td>{index}</td><td>Convenio</td><td>REVISIÓN</td><td>Sevilla</td>'
                f'<td>01/01/2026</td><td>01/01/2026</td><td>31/12/2026</td>'
                f'<td>{button}</td></tr>'
            )
        parser = REGCON._Results()
        parser.feed(f'<table summary="Tramites"><tbody>{"".join(rows)}</tbody></table>')
        self.assertEqual(len(parser.rows), 15)
        self.assertTrue(parser.rows[0]['publication_available'])
        self.assertFalse(parser.rows[1]['publication_available'])
        self.assertFalse(parser.rows[-1]['publication_available'])

    def test_abre_el_enlace_de_publicacion_oficial_del_expediente(self):
        with patch.object(REGCON, 'REGCON_URL', self.url), \
                patch.object(REGCON, 'REGCON_HOST', '127.0.0.1'):
            url = REGCON.publication_url('query', 'convenio de pruebas', 1, '42')
            with self.assertRaises(ValueError):
                REGCON.publication_url('query', 'convenio de pruebas', 2, '43')
        self.assertEqual(url, 'https://boppo.depo.gal/es/anuncio/123')

    def test_actualiza_a_https_los_enlaces_http_de_fuentes_oficiales(self):
        self.server.publication_scheme = 'http'
        try:
            with patch.object(REGCON, 'REGCON_URL', self.url), \
                    patch.object(REGCON, 'REGCON_HOST', '127.0.0.1'):
                url = REGCON.publication_url('query', 'convenio de pruebas', 1, '42')
        finally:
            del self.server.publication_scheme
        self.assertEqual(url, 'https://boppo.depo.gal/es/anuncio/123')

    def test_rechaza_un_enlace_de_publicacion_que_no_sea_espanol(self):
        malicious = pagina_resultados('42', '1', 'Pruebas', '01/01/2026')

        class EvilRegcon(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _reply(self, content):
                body = content.encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.endswith('pagina='):
                    self._reply(malicious)
                else:
                    self._reply('<form id="busquedaAcuerdos"><input type="hidden" name="token" value="x"></form>')

            def do_POST(self):
                length = int(self.headers.get('Content-Length', '0'))
                fields = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
                if '_buscar' in fields:
                    self._reply(malicious)
                else:
                    self._reply(
                        '<p>Para acceder a la publicación del expediente pulse en el siguiente enlace:</p>'
                        '<a href="https://evil.com/phishing">Publicación</a>'
                    )

        server = ThreadingHTTPServer(('127.0.0.1', 0), EvilRegcon)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}/regcon/pub/consultaPublicaEstatal'
        try:
            with patch.object(REGCON, 'REGCON_URL', url), \
                    patch.object(REGCON, 'REGCON_HOST', '127.0.0.1'):
                with self.assertRaises(REGCON.RegconError):
                    REGCON.publication_url('query', 'pruebas', 1, '42')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_rechaza_terminos_y_paginas_invalidos(self):
        for args in (
            ('invalid', 'metal', 1),
            ('query', '', 1),
            ('code', 'x' * 101, 1),
            ('query', 'metal', 0),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                REGCON.search(*args)


if __name__ == '__main__':
    import unittest
    unittest.main()
