"""Pruebas locales de envío de publicaciones al directorio de Paperless."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'openpactum_paperless.py'
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location('openpactum_paperless', SCRIPT)
PAPERLESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PAPERLESS)


class PaperlessImportTest(unittest.TestCase):
    def test_guarda_pdf_original_con_nombre_determinista(self):
        pdf = b'%PDF-1.7\ncontenido de prueba'
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            PAPERLESS,
            'download_document',
            return_value=(
                pdf,
                'application/pdf',
                'utf-8',
                'https://www.boe.es/documento.pdf',
            ),
        ):
            first = PAPERLESS.import_official_publication(
                'https://www.boe.es/documento.pdf',
                'Convenio de prueba',
                '08001234012025',
                tmp,
            )
            second = PAPERLESS.import_official_publication(
                'https://www.boe.es/documento.pdf',
                'Convenio de prueba',
                '08001234012025',
                tmp,
            )
            destination = Path(tmp) / first['filename']
            self.assertEqual(destination.read_bytes(), pdf)
            self.assertEqual(first['status'], 'queued')
            self.assertEqual(second['status'], 'already_queued')
            self.assertEqual(list(Path(tmp).iterdir()), [destination])

    def test_guarda_html_como_texto_y_conserva_la_fuente(self):
        page = (
            b'<html><body><main><h1>Convenio de prueba</h1>'
            b'<p>Articulo 1. Ambito. Texto oficial</p></main></body></html>'
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            PAPERLESS,
            'download_document',
            return_value=(
                page,
                'text/html',
                'utf-8',
                'https://www.boe.es/convenio',
            ),
        ):
            result = PAPERLESS.import_official_publication(
                'https://www.boe.es/convenio',
                'Convenio de prueba',
                '08001234012025',
                tmp,
            )
            document = (Path(tmp) / result['filename']).read_text(encoding='utf-8')
        self.assertTrue(result['filename'].endswith('.txt'))
        self.assertIn('Fuente oficial: https://www.boe.es/convenio', document)
        self.assertIn('Convenio de prueba', document)
        self.assertIn('Texto oficial', document)

    def test_descarga_el_pdf_enlazado_desde_la_publicacion_html(self):
        page = (
            b'<html><body><main><p>Convenio de prueba</p>'
            b'<a href="/documentos/convenio">Descargar el PDF</a></main></body></html>'
        )
        pdf = b'%PDF-1.7\ncontenido original'
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            PAPERLESS,
            'download_document',
            side_effect=[
                (
                    page,
                    'text/html',
                    'utf-8',
                    'https://www.boe.es/anuncio/123',
                ),
                (
                    pdf,
                    'application/pdf',
                    'utf-8',
                    'https://www.boe.es/documentos/convenio',
                ),
            ],
        ) as download:
            result = PAPERLESS.import_official_publication(
                'https://www.boe.es/anuncio/123',
                'Convenio de prueba',
                '08001234012025',
                tmp,
            )
            self.assertEqual(
                (Path(tmp) / result['filename']).read_bytes(),
                pdf,
            )
        self.assertTrue(result['filename'].endswith('.pdf'))
        self.assertEqual(
            download.call_args_list[1].args[0],
            'https://www.boe.es/documentos/convenio',
        )

    def test_rechaza_formato_no_admitido(self):
        with mock.patch.object(
            PAPERLESS,
            'download_document',
            return_value=(b'datos', 'application/octet-stream', 'utf-8', 'https://www.boe.es/doc'),
        ):
            with self.assertRaises(PAPERLESS.PaperlessImportError):
                PAPERLESS.import_official_publication(
                    'https://www.boe.es/doc',
                    'Convenio',
                    '123',
                    '.',
                )

    def test_falla_claramente_si_no_existe_el_directorio_compartido(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            PAPERLESS,
            'download_document',
            return_value=(
                b'%PDF-1.7\ncontenido',
                'application/pdf',
                'utf-8',
                'https://www.boe.es/documento.pdf',
            ),
        ):
            with self.assertRaisesRegex(
                PAPERLESS.PaperlessImportError,
                'directorio compartido',
            ):
                PAPERLESS.import_official_publication(
                    'https://www.boe.es/documento.pdf',
                    'Convenio',
                    '123',
                    Path(tmp) / 'no-existe',
                )
