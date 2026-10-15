"""Pruebas locales del panel de estado, sin red ni Docker."""
import importlib.util
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'panel.py'
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
                    self.assertIn(b'OpenPactum', response.read())
                    self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                with urllib.request.urlopen(base + '/api/status') as response:
                    self.assertEqual(json.loads(response.read()), estado)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base + '/ruta-desconocida')
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
