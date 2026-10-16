"""Consulta de solo lectura al registro público REGCON."""
from html.parser import HTMLParser
from datetime import datetime, timezone
import html as html_module
import http.cookiejar
import re
import urllib.error
import urllib.parse
import urllib.request

REGCON_URL = 'https://expinterweb.mites.gob.es/regcon/pub/consultaPublicaEstatal'
REGCON_HISTORICAL_URL = 'https://expinterweb.mites.gob.es/regcon/pub/consultaPublicaRegconAntiguo'
REGCON_HOST = 'expinterweb.mites.gob.es'
OFFICIAL_PUBLICATION_SUFFIXES = ('.es', '.cat', '.eus', '.gal')
USER_AGENT = 'OpenPactum/1.0 (consulta publica de convenios)'
MAX_RESPONSE_BYTES = 2_000_000


class RegconError(Exception):
    """Error legible al consultar el servicio público REGCON."""


class _HiddenFields(HTMLParser):
    def __init__(self, form_id):
        super().__init__(convert_charrefs=True)
        self.form_id = form_id
        self.in_form = False
        self.fields = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.in_form = attrs.get('id') == self.form_id
        elif tag == 'input' and self.in_form and attrs.get('type', '').lower() == 'hidden':
            name = attrs.get('name')
            if name:
                self.fields.append((name, attrs.get('value', '')))

    def handle_endtag(self, tag):
        if tag == 'form' and self.in_form:
            self.in_form = False


class _AuthorityOptions(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_form = False
        self.in_authority_select = False
        self.in_option = False
        self.option_value = None
        self.option_label = []
        self.authorities = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.in_form = attrs.get('id') == 'busquedaAcuerdos'
        elif self.in_form and tag == 'select':
            self.in_authority_select = attrs.get('name') == 'autoridadLaboral'
        elif self.in_authority_select and tag == 'option':
            self.in_option = True
            self.option_value = attrs.get('value')
            self.option_label = []

    def handle_data(self, data):
        if self.in_option:
            self.option_label.append(data)

    def handle_endtag(self, tag):
        if tag == 'option' and self.in_option:
            value = self.option_value
            label = ' '.join(' '.join(self.option_label).split())
            if value and label:
                self.authorities.append({'code': value, 'name': label})
            self.in_option = False
            self.option_value = None
            self.option_label = []
        elif tag == 'select':
            self.in_authority_select = False
        elif tag == 'form':
            self.in_form = False
            self.in_authority_select = False


class _Results(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.in_body = False
        self.in_row = False
        self.in_cell = False
        self.cells = []
        self.cell = []
        self.record_id = None
        self.view_field = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table' and attrs.get('summary', '').lower() == 'tramites':
            self.in_table = True
        elif tag == 'tbody' and self.in_table:
            self.in_body = True
        elif tag == 'tr' and self.in_body:
            self.in_row = True
            self.cells = []
            self.record_id = None
            self.view_field = None
        elif tag == 'td' and self.in_row:
            self.in_cell = True
            self.cell = []
        elif tag == 'br' and self.in_cell:
            self.cell.append(' ')
        elif tag == 'button' and self.in_row:
            name = attrs.get('name', '')
            match = re.fullmatch(r'_ver(?:Expediente|Apunte)(\d+)', name)
            if match:
                self.record_id = match.group(1)
                self.view_field = name

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == 'td' and self.in_cell:
            self.cells.append(' '.join(''.join(self.cell).split()))
            self.in_cell = False
        elif tag == 'tr' and self.in_row:
            if len(self.cells) >= 7:
                self.rows.append({
                    'code': self.cells[0],
                    'denomination': self.cells[1],
                    'procedure': self.cells[2],
                    'authority': self.cells[3],
                    'publication_date': self.cells[4],
                    'valid_from': self.cells[5],
                    'valid_until': self.cells[6],
                    'record_id': self.record_id,
                    'view_field': self.view_field,
                    'publication_available': bool(
                        self.view_field and self.view_field.startswith('_verExpediente')),
                })
            self.in_row = False
        elif tag == 'tbody' and self.in_body:
            self.in_body = False
        elif tag == 'table' and self.in_table:
            self.in_table = False


class _PublicationLink(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.waiting_for_link = False
        self.url = None

    def handle_data(self, data):
        if 'para acceder a la publicación del expediente' in data.lower():
            self.waiting_for_link = True

    def handle_starttag(self, tag, attrs):
        if self.waiting_for_link and tag == 'a':
            self.url = dict(attrs).get('href')
            if self.url:
                self.waiting_for_link = False


def _open(opener, url, data=None):
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html'}
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with opener.open(request, timeout=25) as response:
            final_host = urllib.parse.urlsplit(response.geturl()).hostname
            if final_host != REGCON_HOST:
                raise RegconError('REGCON redirigió a un dominio inesperado.')
            content = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RegconError(f'REGCON respondió HTTP {exc.code}.') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, 'reason', exc)
        raise RegconError(f'No se pudo conectar con REGCON: {reason}') from exc
    if len(content) > MAX_RESPONSE_BYTES:
        raise RegconError('REGCON devolvió una página mayor de lo esperado.')
    return content.decode('utf-8', errors='replace')


def _new_opener():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def authorities():
    html = _open(_new_opener(), REGCON_URL)
    parser = _AuthorityOptions()
    parser.feed(html)
    if not parser.authorities:
        raise RegconError('REGCON no devolvió la lista de autoridades laborales esperada.')
    return {
        'source': 'REGCON',
        'source_url': REGCON_URL,
        'historical_url': REGCON_HISTORICAL_URL,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'authorities': parser.authorities,
    }


def _hidden_fields(page, form_id):
    parser = _HiddenFields(form_id)
    parser.feed(page)
    if not parser.fields:
        raise RegconError('REGCON ha cambiado el formulario de consulta; no se pudo continuar.')
    return parser.fields


def _search_page(opener, mode, term, page, authority=None):
    html = _open(opener, REGCON_URL)
    fields = _hidden_fields(html, 'busquedaAcuerdos')
    fields.append(('codigoConvenio' if mode == 'code' else 'denominacion', term))
    fields.extend((('idNaturalezaConsPublica', '1'), ('_buscar', 'BUSCAR')))
    if authority not in (None, ''):
        if not re.fullmatch(r'\d{1,3}', str(authority)):
            raise ValueError('El código de autoridad REGCON no es válido.')
        fields.append(('autoridadLaboral', str(authority)))
    body = urllib.parse.urlencode(fields).encode('utf-8')
    html = _open(opener, REGCON_URL, body)
    if 'Error en la aplicación:' in html:
        raise RegconError('REGCON no pudo completar la consulta. Inténtelo más tarde.')
    if page > 1:
        page_url = f'{REGCON_URL}?pagina={page}'
        html = _open(opener, page_url)
    return html


def _result_count(html):
    plain = html_module.unescape(re.sub(r'<[^>]+>', ' ', html))
    plain = re.sub(r'\s+', ' ', plain)
    match = re.search(
        r'Resultados\s*([\d.]+)\s*-\s*([\d.]+)\s*de\s*([\d.]+)',
        plain,
        re.IGNORECASE,
    )
    if not match:
        if re.search(r'sin resultados|no se han encontrado resultados', plain, re.IGNORECASE):
            return 0, 1
        raise RegconError('REGCON devolvió una respuesta de resultados no reconocida.')
    total = int(match.group(3).replace('.', ''))
    last_page = re.search(
        r'<a\b[^>]*href=["\'][^"\']*[?&]pagina=(\d+)["\'][^>]*>\s*Ultimo\s*</a>',
        html,
        re.IGNORECASE,
    )
    return total, int(last_page.group(1)) if last_page else 1


def _validate_search(mode, term, page):
    if mode not in ('query', 'code'):
        raise ValueError('El tipo de búsqueda debe ser “query” o “code”.')
    if not isinstance(term, str) or not term.strip() or len(term.strip()) > 100:
        raise ValueError('Escriba un código o una denominación de hasta 100 caracteres.')
    if not isinstance(page, int) or page < 1 or page > 10_000:
        raise ValueError('El número de página no es válido.')
    return term.strip()


def search(mode, term, page=1, authority=None):
    term = _validate_search(mode, term, page)
    html = _search_page(_new_opener(), mode, term, page, authority)
    total, pages = _result_count(html)
    if page > pages:
        raise ValueError(f'La búsqueda solo tiene {pages} página(s).')
    parser = _Results()
    parser.feed(html)
    return {
        'source': 'REGCON',
        'mode': mode,
        'query': term,
        'authority_filter': str(authority) if authority not in (None, '') else '',
        'page': page,
        'pages': pages,
        'total': total,
        'results': [
            {key: row[key] for key in (
                'code', 'denomination', 'procedure', 'authority', 'publication_date',
                'valid_from', 'valid_until', 'record_id', 'publication_available',
            )}
            for row in parser.rows
        ],
    }


def publication_url(mode, term, page, record_id, authority=None):
    term = _validate_search(mode, term, page)
    if not isinstance(record_id, str) or not re.fullmatch(r'\d{1,12}', record_id):
        raise ValueError('El identificador del expediente no es válido.')
    opener = _new_opener()
    html = _search_page(opener, mode, term, page, authority)
    parser = _Results()
    parser.feed(html)
    row = next((item for item in parser.rows if item['record_id'] == record_id), None)
    if not row:
        raise ValueError('El expediente ya no aparece en esa página de resultados.')
    if not row['publication_available']:
        raise ValueError('Este trámite no tiene un enlace directo a una publicación oficial.')

    fields = _hidden_fields(html, 'gestionAcuerdos')
    fields.append((row['view_field'], ''))
    detail = _open(opener, REGCON_URL, urllib.parse.urlencode(fields).encode('utf-8'))
    if 'Error en la aplicación:' in detail:
        raise RegconError('REGCON no pudo abrir el expediente. Inténtelo más tarde.')
    link_parser = _PublicationLink()
    link_parser.feed(detail)
    if not link_parser.url:
        raise RegconError('REGCON no ofrece un enlace público de publicación para este expediente.')
    destination = urllib.parse.urljoin(REGCON_URL, link_parser.url)
    parsed = urllib.parse.urlsplit(destination)
    try:
        if (
            parsed.scheme == 'http'
            and parsed.port in (None, 80)
            and parsed.hostname
            and parsed.hostname.lower().endswith(OFFICIAL_PUBLICATION_SUFFIXES)
            and parsed.username is None
            and parsed.password is None
        ):
            destination = urllib.parse.urlunsplit((
                'https',
                parsed.hostname or '',
                parsed.path,
                parsed.query,
                parsed.fragment,
            ))
            parsed = urllib.parse.urlsplit(destination)
        safe_destination = (
            parsed.scheme == 'https'
            and parsed.hostname
            and parsed.hostname.lower().endswith(OFFICIAL_PUBLICATION_SUFFIXES)
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except ValueError:
        safe_destination = False
    if not safe_destination:
        raise RegconError('REGCON devolvió un enlace que no parece una publicación oficial española.')
    return destination
