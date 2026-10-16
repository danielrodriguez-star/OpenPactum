"""Envío de publicaciones oficiales al directorio de entrada de Paperless."""
from hashlib import sha256
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import tempfile
from threading import Lock
import urllib.parse

from openpactum_summary import (
    SummaryError,
    download_document,
    extract_html_sections,
)


class PaperlessImportError(Exception):
    """Error legible al preparar una publicación para Paperless."""


_IMPORT_LOCK = Lock()


class _PdfLink(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.href = None
        self.text = []
        self.candidates = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.text = []

    def handle_data(self, data):
        if self.href:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.href:
            label = ' '.join(' '.join(self.text).split()).lower()
            try:
                path = urllib.parse.urlsplit(self.href).path.lower()
            except ValueError:
                path = ''
            if 'pdf' in label or path.endswith('.pdf'):
                self.candidates.append(self.href)
            self.href = None
            self.text = []


def _linked_pdf_url(content, charset, page_url):
    parser = _PdfLink()
    try:
        parser.feed(content.decode(charset, errors='replace'))
    except LookupError as exc:
        raise PaperlessImportError(
            'No se pudo interpretar la codificación de la publicación web.'
        ) from exc
    if not parser.candidates:
        return None
    return urllib.parse.urljoin(page_url, parser.candidates[0])


def import_official_publication(url, title, code, consume_dir):
    try:
        content, content_type, charset, final_url = download_document(url)
        if content_type in ('text/html', 'application/xhtml+xml'):
            pdf_url = _linked_pdf_url(content, charset, final_url)
            if pdf_url:
                content, content_type, charset, final_url = download_document(pdf_url)
                if content_type != 'application/pdf':
                    raise PaperlessImportError(
                        'El enlace de descarga de la publicación no devolvió un PDF.'
                    )
        if content_type == 'application/pdf':
            document = content
            extension = '.pdf'
        elif content_type in ('text/html', 'application/xhtml+xml'):
            sections = extract_html_sections(content, charset)
            body = [
                f'Título: {title}',
                f'Código REGCON: {code or "no indicado"}',
                f'Fuente oficial: {final_url}',
                '',
            ]
            for heading, text in sections:
                body.extend((heading, text, ''))
            document = '\n'.join(body).encode('utf-8')
            extension = '.txt'
        else:
            raise PaperlessImportError(
                'La publicación oficial no es PDF ni una página web compatible.'
            )
    except SummaryError as exc:
        raise PaperlessImportError(str(exc)) from exc

    digest = sha256(document).hexdigest()
    safe_code = re.sub(r'[^A-Za-z0-9_-]', '_', str(code or 'sin-codigo'))[:48]
    safe_title = re.sub(r'[^\w-]+', '_', str(title), flags=re.UNICODE)[:60].strip('_')
    filename = f'OpenPactum-{safe_code}-{safe_title}-{digest[:20]}{extension}'
    directory = Path(consume_dir)
    if not directory.is_dir():
        raise PaperlessImportError(
            'No está disponible el directorio compartido de entrada de Paperless.'
        )

    target = directory / filename
    with _IMPORT_LOCK:
        if target.exists():
            return {'status': 'already_queued', 'filename': filename, 'sha256': digest}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='wb',
                prefix=f'.{filename}.',
                suffix='.partial',
                dir=directory,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(document)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except OSError as exc:
            raise PaperlessImportError(
                'No se pudo guardar la publicación en el directorio de entrada de Paperless.'
            ) from exc
        finally:
            if temporary is not None and temporary.exists():
                try:
                    temporary.unlink()
                except OSError as exc:
                    raise PaperlessImportError(
                        'No se pudo limpiar el archivo temporal de importación de Paperless.'
                    ) from exc

    return {'status': 'queued', 'filename': filename, 'sha256': digest}
