"""Pruebas del catálogo local de convenios y publicaciones."""
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
from unittest import TestCase

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'openpactum_catalog.py'
SPEC = importlib.util.spec_from_file_location('openpactum_catalog_test', SCRIPT)
CATALOG_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CATALOG_MODULE)


class AgreementCatalogTest(TestCase):
    def test_agrupa_tramites_por_codigo_y_autoridad_y_conserva_versiones(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = CATALOG_MODULE.AgreementCatalog(Path(tmp) / 'catalog.sqlite')
            catalog.record_search({
                'mode': 'query',
                'query': 'intervención social',
                'page': 1,
                'authority_filter': '8',
                'results': [
                    {
                        'code': '08001234012025',
                        'denomination': 'Convenio de intervención social',
                        'authority': 'Barcelona',
                        'procedure': 'CONVENIO COLECTIVO (TEXTO NUEVO)',
                        'publication_date': '12/01/2025',
                        'valid_from': '01/01/2025',
                        'valid_until': '31/12/2026',
                        'record_id': '42',
                        'publication_available': True,
                    },
                    {
                        'code': '08001234012025',
                        'denomination': 'Convenio de intervención social',
                        'authority': 'Barcelona',
                        'procedure': 'REVISIÓN SALARIAL',
                        'publication_date': '10/01/2026',
                        'valid_from': '01/01/2026',
                        'valid_until': '31/12/2026',
                        'record_id': '43',
                        'publication_available': False,
                    },
                ],
            })
            result = catalog.list_conventions()

        self.assertEqual(result['total'], 1)
        convention = result['conventions'][0]
        self.assertEqual(convention['code'], '08001234012025')
        self.assertEqual(convention['authority'], 'Barcelona')
        self.assertEqual(convention['publication_count'], 2)
        self.assertEqual(
            {item['procedure'] for item in convention['publications']},
            {'CONVENIO COLECTIVO (TEXTO NUEVO)', 'REVISIÓN SALARIAL'},
        )
        self.assertTrue(next(
            item for item in convention['publications'] if item['record_id'] == '42'
        )['publication_available'])
        self.assertEqual(next(
            item for item in convention['publications'] if item['record_id'] == '42'
        )['authority_code'], '8')

    def test_repetir_busqueda_actualiza_observacion_sin_duplicar_tramites(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = CATALOG_MODULE.AgreementCatalog(Path(tmp) / 'catalog.sqlite')
            result = {
                'mode': 'query',
                'query': 'educación',
                'page': 1,
                'results': [{
                    'code': '08001234012025',
                    'denomination': 'Convenio de educación',
                    'authority': 'Barcelona',
                    'procedure': 'TEXTO NUEVO',
                    'publication_date': '12/01/2025',
                    'valid_from': '01/01/2025',
                    'valid_until': '31/12/2026',
                    'record_id': '42',
                    'publication_available': True,
                }],
            }
            catalog.record_search(result)
            result['query'] = 'centros educativos'
            result['authority_filter'] = '8'
            catalog.record_search(result)
            entry = catalog.list_conventions()['conventions'][0]

        self.assertEqual(entry['publication_count'], 1)
        self.assertEqual(entry['publications'][0]['query'], 'centros educativos')
        self.assertEqual(entry['publications'][0]['authority_code'], '8')

    def test_migra_la_tabla_existente_para_guardar_el_filtro_territorial(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / 'catalog.sqlite'
            connection = sqlite3.connect(database)
            try:
                connection.executescript("""
                    CREATE TABLE conventions (
                        id TEXT PRIMARY KEY, code TEXT NOT NULL, denomination TEXT NOT NULL,
                        authority TEXT NOT NULL, valid_from TEXT NOT NULL DEFAULT '',
                        valid_until TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
                    );
                    CREATE TABLE publications (
                        id TEXT PRIMARY KEY, convention_id TEXT NOT NULL,
                        record_id TEXT, procedure TEXT NOT NULL,
                        publication_date TEXT NOT NULL DEFAULT '', valid_from TEXT NOT NULL DEFAULT '',
                        valid_until TEXT NOT NULL DEFAULT '', publication_available INTEGER NOT NULL DEFAULT 0,
                        mode TEXT NOT NULL, query TEXT NOT NULL, page INTEGER NOT NULL,
                        last_seen_at TEXT NOT NULL
                    );
                """)
            finally:
                connection.close()
            catalog = CATALOG_MODULE.AgreementCatalog(database)
            catalog.record_search({
                'mode': 'query',
                'query': 'intervención',
                'page': 1,
                'authority_filter': '8',
                'results': [{
                    'code': '08001234012025',
                    'denomination': 'Convenio',
                    'authority': 'Barcelona',
                    'procedure': 'TEXTO NUEVO',
                    'record_id': '42',
                }],
            })
            publications = catalog.list_conventions()['conventions'][0]['publications']

        self.assertEqual(publications[0]['authority_code'], '8')

    def test_separa_codigos_iguales_de_autoridades_distintas(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = CATALOG_MODULE.AgreementCatalog(Path(tmp) / 'catalog.sqlite')
            for authority in ('Barcelona', 'Girona'):
                catalog.record_search({
                    'mode': 'code',
                    'query': '08001234012025',
                    'page': 1,
                    'results': [{
                        'code': '08001234012025',
                        'denomination': 'Convenio',
                        'authority': authority,
                        'procedure': 'TEXTO NUEVO',
                        'record_id': authority,
                        'publication_available': False,
                    }],
                })
            result = catalog.list_conventions()

        self.assertEqual(result['total'], 2)
        self.assertEqual(
            {item['authority'] for item in result['conventions']},
            {'Barcelona', 'Girona'},
        )

    def test_valida_paginacion_del_catalogo(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog = CATALOG_MODULE.AgreementCatalog(Path(tmp) / 'catalog.sqlite')
            for args in ((0, 0), (201, 0), (10, -1)):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    catalog.list_conventions(*args)
