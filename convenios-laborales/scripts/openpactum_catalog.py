"""Catálogo local de convenios y trámites observados en REGCON."""
from datetime import datetime, timezone
from hashlib import sha256
import sqlite3
from pathlib import Path


class CatalogError(Exception):
    """Error legible al guardar o consultar el catálogo local."""


class AgreementCatalog:
    def __init__(self, database_path):
        self.database_path = Path(database_path)

    def _connect(self):
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.database_path, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys = ON')
            connection.execute('PRAGMA busy_timeout = 10000')
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS conventions (
                    id TEXT PRIMARY KEY,
                    code TEXT NOT NULL,
                    denomination TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    valid_from TEXT NOT NULL DEFAULT '',
                    valid_until TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS publications (
                    id TEXT PRIMARY KEY,
                    convention_id TEXT NOT NULL REFERENCES conventions(id) ON DELETE CASCADE,
                    record_id TEXT,
                    procedure TEXT NOT NULL,
                    publication_date TEXT NOT NULL DEFAULT '',
                    valid_from TEXT NOT NULL DEFAULT '',
                    valid_until TEXT NOT NULL DEFAULT '',
                    publication_available INTEGER NOT NULL DEFAULT 0,
                    mode TEXT NOT NULL,
                    query TEXT NOT NULL,
                    authority_code TEXT NOT NULL DEFAULT '',
                    page INTEGER NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE (convention_id, id)
                );
                CREATE INDEX IF NOT EXISTS publications_by_convention
                    ON publications(convention_id, last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS conventions_by_updated
                    ON conventions(updated_at DESC);
            """)
            publication_columns = {
                row['name'] for row in connection.execute('PRAGMA table_info(publications)')
            }
            if 'authority_code' not in publication_columns:
                connection.execute(
                    "ALTER TABLE publications ADD COLUMN authority_code TEXT NOT NULL DEFAULT ''")
            return connection
        except sqlite3.Error as exc:
            raise CatalogError(f'No se pudo abrir el catálogo local: {exc}') from exc
        except OSError as exc:
            raise CatalogError(f'No se pudo preparar el catálogo local: {exc}') from exc

    @staticmethod
    def _text(value):
        return value.strip() if isinstance(value, str) else ''

    @classmethod
    def _convention_id(cls, code, denomination, authority):
        identifier = code or denomination
        identity = f'{identifier.casefold()}|{authority.casefold()}'
        return sha256(identity.encode('utf-8')).hexdigest()

    @classmethod
    def _publication_id(cls, convention_id, row):
        record_id = cls._text(row.get('record_id'))
        if record_id:
            key = record_id
        else:
            key = '|'.join(cls._text(row.get(field)) for field in (
                'procedure', 'publication_date', 'valid_from', 'valid_until',
            ))
        return sha256(f'{convention_id}|{key}'.encode('utf-8')).hexdigest()

    def record_search(self, result):
        mode = result.get('mode')
        query = self._text(result.get('query'))
        page = result.get('page')
        rows = result.get('results')
        if mode not in ('query', 'code') or not query or not isinstance(page, int) or page < 1:
            raise CatalogError('La respuesta de REGCON no contiene los datos de búsqueda esperados.')
        if not isinstance(rows, list):
            raise CatalogError('La respuesta de REGCON no contiene una lista de trámites válida.')

        observed_at = datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            with connection:
                for row in rows:
                    if not isinstance(row, dict):
                        raise CatalogError('REGCON devolvió un trámite con formato no válido.')
                    code = self._text(row.get('code'))
                    denomination = self._text(row.get('denomination'))
                    authority = self._text(row.get('authority'))
                    if not denomination or not authority or not (code or denomination):
                        continue
                    convention_id = self._convention_id(code, denomination, authority)
                    values = {
                        field: self._text(row.get(field))
                        for field in ('valid_from', 'valid_until')
                    }
                    connection.execute("""
                        INSERT INTO conventions
                            (id, code, denomination, authority, valid_from, valid_until, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            code = excluded.code,
                            denomination = excluded.denomination,
                            authority = excluded.authority,
                            valid_from = excluded.valid_from,
                            valid_until = excluded.valid_until,
                            updated_at = excluded.updated_at
                    """, (
                        convention_id, code, denomination, authority,
                        values['valid_from'], values['valid_until'], observed_at,
                    ))
                    publication_id = self._publication_id(convention_id, row)
                    record_id = self._text(row.get('record_id')) or None
                    connection.execute("""
                        INSERT INTO publications (
                            id, convention_id, record_id, procedure, publication_date,
                            valid_from, valid_until, publication_available, mode, query,
                            authority_code, page, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            record_id = excluded.record_id,
                            procedure = excluded.procedure,
                            publication_date = excluded.publication_date,
                            valid_from = excluded.valid_from,
                            valid_until = excluded.valid_until,
                            publication_available = excluded.publication_available,
                            mode = excluded.mode,
                            query = excluded.query,
                            authority_code = excluded.authority_code,
                            page = excluded.page,
                            last_seen_at = excluded.last_seen_at
                    """, (
                        publication_id, convention_id, record_id,
                        self._text(row.get('procedure')),
                        self._text(row.get('publication_date')),
                        values['valid_from'], values['valid_until'],
                        int(bool(row.get('publication_available'))),
                        mode, query, self._text(result.get('authority_filter')),
                        page, observed_at,
                    ))
        except CatalogError:
            raise
        except sqlite3.Error as exc:
            raise CatalogError(f'No se pudieron guardar los trámites en el catálogo local: {exc}') from exc
        finally:
            connection.close()

    def list_conventions(self, limit=100, offset=0):
        if not isinstance(limit, int) or limit < 1 or limit > 200:
            raise ValueError('El límite del catálogo debe estar entre 1 y 200.')
        if not isinstance(offset, int) or offset < 0:
            raise ValueError('El desplazamiento del catálogo no es válido.')
        connection = self._connect()
        try:
            total = connection.execute('SELECT COUNT(*) FROM conventions').fetchone()[0]
            conventions = connection.execute("""
                SELECT id, code, denomination, authority, valid_from, valid_until, updated_at
                FROM conventions
                ORDER BY updated_at DESC, denomination COLLATE NOCASE
                LIMIT ? OFFSET ?
            """, (limit, offset)).fetchall()
            entries = []
            for convention in conventions:
                publications = connection.execute("""
                    SELECT record_id, procedure, publication_date, valid_from, valid_until,
                           publication_available, mode, query, authority_code, page, last_seen_at
                    FROM publications
                    WHERE convention_id = ?
                    ORDER BY last_seen_at DESC, publication_date DESC
                """, (convention['id'],)).fetchall()
                entries.append({
                    'id': convention['id'],
                    'code': convention['code'],
                    'denomination': convention['denomination'],
                    'authority': convention['authority'],
                    'valid_from': convention['valid_from'],
                    'valid_until': convention['valid_until'],
                    'updated_at': convention['updated_at'],
                    'publication_count': len(publications),
                    'publications': [
                        {
                            **dict(publication),
                            'publication_available': bool(publication['publication_available']),
                        }
                        for publication in publications
                    ],
                })
            return {'total': total, 'limit': limit, 'offset': offset, 'conventions': entries}
        except sqlite3.Error as exc:
            raise CatalogError(f'No se pudo consultar el catálogo local: {exc}') from exc
        finally:
            connection.close()

    def coverage_by_authority(self):
        connection = self._connect()
        try:
            rows = connection.execute("""
                SELECT authority, COUNT(*) AS conventions, MAX(updated_at) AS last_seen_at
                FROM conventions
                GROUP BY authority
                ORDER BY authority COLLATE NOCASE
            """).fetchall()
            return {
                row['authority']: {
                    'conventions': row['conventions'],
                    'last_seen_at': row['last_seen_at'],
                }
                for row in rows
            }
        except sqlite3.Error as exc:
            raise CatalogError(f'No se pudo medir la cobertura local por autoridad: {exc}') from exc
        finally:
            connection.close()
