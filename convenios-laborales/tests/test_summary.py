"""Pruebas locales de extracción y resumen de documentos, sin red ni Ollama."""
import importlib.util
import json
from email.message import Message
from pathlib import Path
import tempfile
import time
from threading import Event
from unittest import TestCase
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'openpactum_summary.py'
SPEC = importlib.util.spec_from_file_location('openpactum_summary_test', SCRIPT)
SUMMARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUMMARY)


class SummaryTest(TestCase):
    def test_rechaza_fuentes_que_no_sean_dominio_oficial_https(self):
        for url in (
            'http://www.boe.es/documento.pdf',
            'https://evil.com/documento.pdf',
            'https://www.boe.es.evil.com/documento.pdf',
            'https://user@www.boe.es/documento.pdf',
        ):
            with self.subTest(url=url), self.assertRaises(SUMMARY.SummaryError):
                SUMMARY._validate_official_url(url)

    def test_descarga_publicacion_html_oficial(self):
        with patch.object(SUMMARY, '_validate_official_url', return_value='https://www.boe.es/a'):
            with patch.object(SUMMARY.urllib.request, 'build_opener') as build_opener:
                response = build_opener.return_value.open.return_value.__enter__.return_value
                response.geturl.return_value = 'https://www.boe.es/a'
                response.headers = Message()
                response.headers['Content-Type'] = 'text/html; charset=utf-8'
                response.read.return_value = b'<html><main>Texto oficial</main></html>'
                content, content_type, charset, final_url = SUMMARY.download_document(
                    'https://www.boe.es/a')
        self.assertEqual(content, b'<html><main>Texto oficial</main></html>')
        self.assertEqual(content_type, 'text/html')
        self.assertEqual(charset, 'utf-8')
        self.assertEqual(final_url, 'https://www.boe.es/a')

    def test_extrae_secciones_html_y_omite_navegacion_y_scripts(self):
        content = (
            '<html><head><title>Ruido</title></head><body><nav>Menú</nav>'
            '<main><h1>Convenio colectivo</h1><p>Texto general</p>'
            '<h2>Artículo 1. Ámbito</h2><p>Se aplica al sector.</p>'
            '<script>secreto();</script></main></body></html>'
        ).encode('utf-8')
        sections = SUMMARY.extract_html_sections(content)
        self.assertEqual(sections, [
            ('Convenio colectivo', 'Texto general'),
            ('Artículo 1. Ámbito', 'Se aplica al sector.'),
        ])

    def test_prioriza_el_contenido_del_anuncio_sobre_el_resto_de_la_pagina(self):
        content = (
            '<main><section id="content"><h2>Convenio</h2><p>Texto oficial.</p>'
            '</section><h2>Acceso</h2><p>Texto ajeno al anuncio.</p></main>'
        ).encode('utf-8')
        self.assertEqual(
            SUMMARY.extract_html_sections(content),
            [('Convenio', 'Texto oficial.')],
        )

    def test_detecta_articulos_dentro_de_publicaciones_html(self):
        sections = SUMMARY._split_html_articles([(
            'Convenio',
            'Introducción. Artículo 1. Ámbito funcional. Se aplica al sector. '
            'Artículo 2. Vigencia. El convenio dura dos años.',
        )])
        self.assertEqual(sections, [
            ('Convenio', 'Introducción.'),
            ('Artículo 1. Ámbito funcional.', 'Se aplica al sector.'),
            ('Artículo 2. Vigencia.', 'El convenio dura dos años.'),
        ])

    def test_rechaza_html_vacio_o_que_supere_limite_de_extraccion(self):
        with self.assertRaisesRegex(SUMMARY.SummaryError, 'no contiene texto legible'):
            SUMMARY.extract_html_sections(b'<html><nav>Solo navegacion</nav></html>')
        with patch.object(SUMMARY, 'MAX_DOCUMENT_CHARACTERS', 5):
            with self.assertRaisesRegex(SUMMARY.SummaryError, 'supera el límite'):
                SUMMARY.extract_html_sections(b'<main><p>Texto demasiado largo</p></main>')

    def test_resumen_se_genera_por_fragmentos_y_se_reutiliza_desde_cache(self):
        source_url = 'https://www.boe.es/documento.pdf'
        pages = [(1, 'Ámbito y jornada.'), (4, 'Salario base: 20.000 euros.')]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(SUMMARY, 'download_document', return_value=(
                    b'%PDF-documento', 'application/pdf', 'utf-8', source_url)), \
                    patch.object(SUMMARY, 'extract_pdf_pages', return_value=pages), \
                    patch.object(SUMMARY, '_generate', side_effect=[
                        'Ámbito y salario [p. 1 y p. 4].',
                        'Resumen práctico [p. 1 y p. 4].',
                    ]) as generate:
                first = SUMMARY.summarize_document(
                    source_url, tmp, 'http://ollama:11434', 'qwen2.5:1.5b')
                self.assertFalse(first['cached'])
                self.assertEqual(first['summary'], 'Resumen práctico [p. 1 y p. 4].')
                self.assertEqual(first['pages'], 4)
                self.assertIn('Ámbito y salario', generate.call_args_list[1].args[2])

            cached_path = next(Path(tmp).glob('*.json'))
            cached_data = json.loads(cached_path.read_text(encoding='utf-8'))
            self.assertEqual(cached_data['document_sha256'], first['document_sha256'])
            with patch.object(SUMMARY, 'download_document', return_value=(
                    b'%PDF-documento', 'application/pdf', 'utf-8', source_url)), \
                    patch.object(SUMMARY, '_summarize_chunks') as summarize:
                second = SUMMARY.summarize_document(
                    source_url, tmp, 'http://ollama:11434', 'qwen2.5:1.5b')
            self.assertTrue(second['cached'])
            self.assertEqual(second['summary'], first['summary'])
            summarize.assert_not_called()

    def test_divide_documentos_largos_sin_perder_la_referencia_de_pagina(self):
        chunks = SUMMARY._split_pages([(17, 'x' * (SUMMARY.CHUNK_CHARACTERS + 100))])
        self.assertEqual(len(chunks), 2)
        self.assertIn('[Referencia: p. 17]', chunks[0])
        self.assertIn('[Referencia: p. 17]', chunks[1])
        self.assertLessEqual(max(map(len, chunks)), SUMMARY.CHUNK_CHARACTERS)

    def test_resumen_html_cita_seccion_y_no_muestra_paginas(self):
        source_url = 'https://bon.navarra.es/es/anuncio/-/texto/2025/241/4'
        html = (
            '<main><h2>Artículo 1. Ámbito</h2>'
            '<p>Se aplica al personal del sector.</p></main>'
        ).encode('utf-8')
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(SUMMARY, 'download_document', return_value=(
                    html, 'text/html', 'utf-8', source_url)), \
                    patch.object(SUMMARY, '_generate', side_effect=[
                        'Ámbito: aplica al sector [Artículo 1. Ámbito].',
                        'Resumen [Artículo 1. Ámbito].',
                    ]) as generate:
                result = SUMMARY.summarize_document(
                    source_url, tmp, 'http://ollama:11434', 'qwen2.5:1.5b')
        self.assertEqual(result['pages'], None)
        self.assertEqual(result['source_type'], 'text/html')
        self.assertIn('[Referencia: Artículo 1. Ámbito]', generate.call_args_list[0].args[2])
        self.assertEqual(result['source_url'], source_url)

    def test_rechaza_pdf_sin_texto_extraible(self):
        with self.assertRaisesRegex(SUMMARY.SummaryError, 'PDF oficial'):
            SUMMARY.extract_pdf_pages(b'not a PDF')

    def test_trabajo_en_segundo_plano_reutiliza_el_mismo_trabajo_y_entrega_resultado(self):
        jobs = SUMMARY.SummaryJobs()
        started = Event()
        finish = Event()
        result = {'summary': 'Convenio resumido [p. 2].'}

        def summarize(*_):
            started.set()
            finish.wait(timeout=2)
            return result

        with patch.object(SUMMARY, 'summarize_document', side_effect=summarize):
            job = jobs.start(
                'https://www.boe.es/convenio.pdf',
                'cache',
                'http://ollama:11434',
                'qwen2.5:1.5b',
            )
            self.assertTrue(started.wait(timeout=1))
            repeated = jobs.start(
                'https://www.boe.es/convenio.pdf',
                'cache',
                'http://ollama:11434',
                'qwen2.5:1.5b',
            )
            self.assertEqual(repeated['job_id'], job['job_id'])
            with self.assertRaises(SUMMARY.SummaryBusyError):
                jobs.start(
                    'https://www.boe.es/otro-convenio.pdf',
                    'cache',
                    'http://ollama:11434',
                    'qwen2.5:1.5b',
                )
            finish.set()
            deadline = time.monotonic() + 2
            completed = jobs.get(job['job_id'])
            while completed['status'] == 'pending' and time.monotonic() < deadline:
                time.sleep(0.01)
                completed = jobs.get(job['job_id'])
        self.assertEqual(completed['status'], 'done')
        self.assertEqual(completed['result'], result)

    def test_trabajo_entrega_un_error_explicito_si_el_resumen_falla(self):
        jobs = SUMMARY.SummaryJobs()
        with patch.object(
            SUMMARY,
            'summarize_document',
            side_effect=SUMMARY.SummaryError('Ollama no está disponible.'),
        ):
            job = jobs.start(
                'https://www.boe.es/convenio.pdf',
                'cache',
                'http://ollama:11434',
                'qwen2.5:1.5b',
            )
            deadline = time.monotonic() + 2
            status = jobs.get(job['job_id'])
            while status['status'] == 'pending' and time.monotonic() < deadline:
                time.sleep(0.01)
                status = jobs.get(job['job_id'])
        self.assertEqual(status['status'], 'error')
        self.assertEqual(status['error'], 'Ollama no está disponible.')


if __name__ == '__main__':
    import unittest
    unittest.main()
