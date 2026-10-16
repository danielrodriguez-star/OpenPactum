"""Pruebas locales del panel de estado, sin red ni Docker."""
import importlib.util
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'panel.py'
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location('openpactum_panel', SCRIPT)
PANEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PANEL)


class ProbeTest(unittest.TestCase):
    def test_considera_disponible_una_respuesta_http_correcta(self):
        respuesta = mock.MagicMock()
        respuesta.__enter__.return_value.getcode.return_value = 200
        with mock.patch.object(PANEL.urllib.request, 'urlopen', return_value=respuesta):
            self.assertEqual(PANEL.probe('http://servicio/'), (True, 200, None))

    def test_considera_activo_un_servicio_que_pide_autenticacion(self):
        error = urllib.error.HTTPError('http://servicio/', 401, 'No autorizado', {}, None)
        with mock.patch.object(PANEL.urllib.request, 'urlopen', side_effect=error):
            self.assertEqual(PANEL.probe('http://servicio/'), (True, 401, None))

    def test_expone_un_error_de_conexion_sin_ocultar_el_fallo(self):
        error = urllib.error.URLError('conexión rechazada')
        with mock.patch.object(PANEL.urllib.request, 'urlopen', side_effect=error):
            ready, code, detail = PANEL.probe('http://servicio/')
        self.assertFalse(ready)
        self.assertIsNone(code)
        self.assertIn('conexión rechazada', detail)


class ScanStatusTest(unittest.TestCase):
    def test_informa_cantidad_y_fecha_del_estado(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'estado-rss.json'
            state.write_text(json.dumps(['BOE-A-2026-1001', 'BOE-A-2026-1002']), encoding='utf-8')
            result = PANEL.scan_status(state)
        self.assertEqual(result['documents'], 2)
        self.assertIsNotNone(result['last_scan'])
        self.assertIsNone(result['error'])

    def test_muestra_error_si_el_estado_no_es_json_valido(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'estado-rss.json'
            state.write_text('{', encoding='utf-8')
            result = PANEL.scan_status(state)
        self.assertIsNone(result['documents'])
        self.assertIn('JSON no válido', result['error'])

    def test_un_estado_ausente_se_presenta_como_sin_ejecuciones(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = PANEL.scan_status(Path(tmp) / 'inexistente.json')
        self.assertEqual(result, {'documents': None, 'last_scan': None, 'error': None})


class HandlerTest(unittest.TestCase):
    def test_sirve_el_panel_y_expone_el_estado_en_json(self):
        estado = {
            'checked_at': '2026-10-15T12:00:00+00:00',
            'services': [],
            'scan': {'documents': 0, 'last_scan': None, 'error': None},
        }
        with mock.patch.object(PANEL, 'status', return_value=estado):
            server = ThreadingHTTPServer(('127.0.0.1', 0), PANEL.Handler)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f'http://127.0.0.1:{server.server_port}'
                with urllib.request.urlopen(base + '/') as response:
                    self.assertEqual(response.status, 200)
                    page = response.read()
                    self.assertIn(b'OpenPactum', page)
                    self.assertIn('Acción e intervención social'.encode(), page)
                    self.assertIn(b'filter-authority', page)
                    self.assertIn(b'regcon-authority', page)
                    self.assertIn(b'/api/regcon/coverage', page)
                    self.assertIn(b'/api/regcon/import', page)
                    self.assertIn('Archivar en Paperless'.encode(), page)
                    self.assertIn('convenios anteriores al 1/10/2010'.encode(), page)
                    self.assertIn(b'Mis convenios', page)
                    self.assertIn('Catálogo de convenios consultados'.encode(), page)
                    self.assertIn(b'/api/catalog?', page)
                    self.assertIn('Añadir otro sector'.encode(), page)
                    self.assertIn(b'BOE-A-2026-4641', page)
                    self.assertIn(b'30.816,22', page)
                    self.assertIn(b'1.695 en 2029', page)
                    self.assertIn(b'/api/regcon/summary/status', page)
                    self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                with urllib.request.urlopen(base + '/api/status') as response:
                    self.assertEqual(json.loads(response.read()), estado)
                result = {
                    'source': 'REGCON', 'mode': 'query', 'query': 'metal',
                    'authority_filter': '8',
                    'page': 1, 'pages': 1, 'total': 1, 'results': [{
                        'code': '08001234012025',
                        'denomination': 'Convenio del metal',
                        'procedure': 'CONVENIO COLECTIVO (TEXTO NUEVO)',
                        'authority': 'Barcelona',
                        'publication_date': '12/01/2025',
                        'valid_from': '01/01/2025',
                        'valid_until': '31/12/2026',
                        'record_id': '42',
                        'publication_available': True,
                    }],
                }
                with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
                    PANEL,
                    'AGREEMENT_CATALOG',
                    PANEL.AgreementCatalog(Path(tmp) / 'catalog.sqlite'),
                ):
                    with mock.patch.object(PANEL, 'search', return_value=result) as search_call:
                        with urllib.request.urlopen(
                            base + '/api/regcon/search?mode=query&q=metal&authority=8'
                        ) as response:
                            self.assertEqual(json.loads(response.read()), result)
                    search_call.assert_called_once_with('query', 'metal', 1, '8')
                    with urllib.request.urlopen(base + '/api/catalog?limit=10&offset=0') as response:
                        catalog = json.loads(response.read())
                        self.assertEqual(catalog['total'], 1)
                        self.assertEqual(
                            catalog['conventions'][0]['publications'][0]['record_id'],
                            '42',
                        )
                    with mock.patch.object(PANEL, 'authorities', return_value={
                        'source': 'REGCON',
                        'source_url': 'https://expinterweb.mites.gob.es/regcon/pub/consultaPublicaEstatal',
                        'historical_url': 'https://expinterweb.mites.gob.es/regcon/pub/consultaPublicaRegconAntiguo',
                        'checked_at': '2026-10-16T12:00:00+00:00',
                        'authorities': [{'code': '8', 'name': 'Barcelona'}],
                    }):
                        with urllib.request.urlopen(base + '/api/regcon/coverage') as response:
                            coverage = json.loads(response.read())
                    self.assertEqual(coverage['observed_authorities'], 1)
                    self.assertEqual(coverage['observed']['Barcelona']['conventions'], 1)
                    with self.assertRaises(urllib.error.HTTPError) as invalid_catalog:
                        urllib.request.urlopen(base + '/api/catalog?limit=500')
                    self.assertEqual(invalid_catalog.exception.code, 400)
                import_request = urllib.request.Request(
                    base + '/api/regcon/import',
                    data=json.dumps({
                        'mode': 'query',
                        'query': 'metal',
                        'page': 1,
                        'record': '42',
                        'authority': '8',
                        'title': 'Convenio del metal',
                        'code': '08001234012025',
                    }).encode('utf-8'),
                    headers={
                        'Content-Type': 'application/json',
                        'Origin': base,
                    },
                    method='POST',
                )
                with mock.patch.object(
                    PANEL,
                    'publication_url',
                    return_value='https://www.boe.es/documento.pdf',
                ) as source, mock.patch.object(
                    PANEL,
                    'import_official_publication',
                    return_value={
                        'status': 'queued',
                        'filename': 'OpenPactum-08001234012025-abc.pdf',
                        'sha256': 'abc',
                    },
                ) as import_call:
                    with urllib.request.urlopen(import_request) as response:
                        self.assertEqual(response.status, 202)
                        self.assertEqual(json.loads(response.read())['status'], 'queued')
                source.assert_called_once_with('query', 'metal', 1, '42', '8')
                import_call.assert_called_once_with(
                    'https://www.boe.es/documento.pdf',
                    'Convenio del metal',
                    '08001234012025',
                    PANEL.PAPERLESS_CONSUME,
                )
                cross_origin_request = urllib.request.Request(
                    base + '/api/regcon/import',
                    data=b'{}',
                    headers={
                        'Content-Type': 'application/json',
                        'Origin': 'https://example.org',
                    },
                    method='POST',
                )
                with self.assertRaises(urllib.error.HTTPError) as cross_origin:
                    urllib.request.urlopen(cross_origin_request)
                self.assertEqual(cross_origin.exception.code, 403)
                with mock.patch.object(PANEL, 'publication_url', return_value='https://bon.navarra.es/documento') as publication:
                    class NoRedirect(urllib.request.HTTPRedirectHandler):
                        def redirect_request(self, *args, **kwargs):
                            return None

                    with self.assertRaises(urllib.error.HTTPError) as redirect:
                        urllib.request.build_opener(NoRedirect()).open(
                            base + '/api/regcon/publication?mode=query&q=metal&page=1&record=42')
                    self.assertEqual(redirect.exception.code, 302)
                    self.assertEqual(
                        redirect.exception.headers['Location'],
                        'https://bon.navarra.es/documento',
                    )
                    publication.assert_called_once_with('query', 'metal', 1, '42', '')
                job_id = 'a' * 32
                job = {'job_id': job_id, 'status': 'pending', 'result': None, 'error': None}
                summary = {
                    'summary': 'Resumen probado [p. 1]',
                    'source_url': 'https://bon.navarra.es/documento.pdf',
                    'document_sha256': 'abc123',
                    'model': 'qwen2.5:1.5b',
                    'pages': 12,
                    'cached': False,
                    'generated_at': '2026-10-15T12:00:00+00:00',
                }
                with mock.patch.object(
                    PANEL, 'publication_url', return_value=summary['source_url']
                ) as summary_publication, \
                        mock.patch.object(PANEL.SUMMARY_JOBS, 'start', return_value=job):
                    with urllib.request.urlopen(
                        base + '/api/regcon/summary?mode=query&q=metal&page=1&record=42&authority=8'
                    ) as response:
                        self.assertEqual(response.status, 202)
                        self.assertEqual(json.loads(response.read()), job)
                    summary_publication.assert_called_once_with('query', 'metal', 1, '42', '8')
                with mock.patch.object(PANEL.SUMMARY_JOBS, 'get', return_value=job):
                    with urllib.request.urlopen(
                        base + f'/api/regcon/summary/status?id={job_id}'
                    ) as response:
                        self.assertEqual(json.loads(response.read()), job)
                completed = {
                    'job_id': job_id,
                    'status': 'done',
                    'result': summary,
                    'error': None,
                }
                with mock.patch.object(PANEL.SUMMARY_JOBS, 'get', return_value=completed):
                    with urllib.request.urlopen(
                        base + f'/api/regcon/summary/status?id={job_id}'
                    ) as response:
                        self.assertEqual(json.loads(response.read()), completed)
                with mock.patch.object(PANEL, 'publication_url', return_value=summary['source_url']), \
                        mock.patch.object(
                            PANEL.SUMMARY_JOBS, 'start',
                            side_effect=PANEL.SummaryBusyError('Ya está ocupado.'),
                        ):
                    with self.assertRaises(urllib.error.HTTPError) as busy:
                        urllib.request.urlopen(
                            base + '/api/regcon/summary?mode=query&q=metal&page=1&record=42')
                    self.assertEqual(busy.exception.code, 429)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base + '/ruta-desconocida')
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
