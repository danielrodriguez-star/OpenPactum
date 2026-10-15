#!/usr/bin/env python3
"""Vigila el canal RSS de convenios colectivos del BOE, descarga PDFs oficiales y avisa por SMTP."""
import json
import os
import re
import smtplib
import ssl
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Rutas configurables para el contenedor (OPENPACTUM_ESTADO, OPENPACTUM_CONSUME).
# Por defecto se mantienen las rutas de la instalación con checkout.
STATE = Path(os.environ.get('OPENPACTUM_ESTADO') or ROOT / 'scripts/.estado-rss.json')
CONSUME = Path(os.environ.get('OPENPACTUM_CONSUME') or ROOT / 'paperless/consume')
# Canal temático oficial de convenios colectivos del BOE (publica los convenios de los dos
# últimos meses). Sustituye al canal genérico de disposiciones, que obligaba a filtrar entre
# toda la producción normativa del día. Puede apuntarse a otro canal con OPENPACTUM_RSS, pero
# entonces el filtro por «convenio colectivo» de main() sigue actuando como red de seguridad.
RSS = os.environ.get('OPENPACTUM_RSS') or 'https://www.boe.es/rss/canal.php?c=ccolectivos'
USER_AGENT = 'OpenPactum/1.0 (vigilancia de convenios)'


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': USER_AGENT}), timeout=30) as r:
        return r.read()


def smtp_password():
    # SMTP_PASSWORD_FILE permite leer la contraseña desde un fichero (Docker secrets).
    # Se quitan solo los saltos de línea finales.
    fichero = os.environ.get('SMTP_PASSWORD_FILE')
    if fichero:
        return Path(fichero).read_text(encoding='utf-8').rstrip('\r\n')
    return os.environ.get('SMTP_PASSWORD', '')


def mail(items):
    host = os.environ.get('SMTP_HOST', '')
    if not host:
        print('SMTP sin configurar: novedades registradas en el log local; no se envió correo.')
        return
    required = ('SMTP_PORT', 'SMTP_FROM', 'SMTP_TO')
    if any(not os.environ.get(k) for k in required):
        raise ValueError('Faltan parámetros SMTP_PORT, SMTP_FROM o SMTP_TO')
    msg = EmailMessage()
    msg['From'] = os.environ['SMTP_FROM']
    msg['To'] = os.environ['SMTP_TO']
    msg['Subject'] = f'BOE: {len(items)} novedades de convenios colectivos'
    msg.set_content('\n\n'.join(f'{title}\n{link}' for title, link in items))
    port = int(os.environ['SMTP_PORT'])
    if os.environ.get('SMTP_STARTTLS', 'true').lower() == 'true':
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            if os.environ.get('SMTP_USER'):
                server.login(os.environ['SMTP_USER'], smtp_password())
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as server:
            if os.environ.get('SMTP_USER'):
                server.login(os.environ['SMTP_USER'], smtp_password())
            server.send_message(msg)


def guardar_estado(seen):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=STATE.parent, prefix=STATE.name + '.',
            suffix='.tmp', delete=False) as f:
        f.write(json.dumps(sorted(seen), ensure_ascii=False))
        temporal = Path(f.name)
    temporal.replace(STATE)


def main():
    root = ET.fromstring(fetch(RSS))
    seen = set(json.loads(STATE.read_text()) if STATE.exists() else [])
    new = []
    for item in root.findall('.//item'):
        title = (item.findtext('title') or '').strip()
        description = ' '.join(item.itertext())
        # Red de seguridad: el canal por defecto solo publica convenios, pero con OPENPACTUM_RSS
        # puede apuntarse a un canal más amplio (por ejemplo, el de disposiciones generales).
        if 'convenio colectivo' not in (title + ' ' + description).lower():
            continue
        link = (item.findtext('link') or '').strip()
        # Solo se aceptan identificadores BOE auténticos; no se descargan enlaces arbitrarios del feed.
        parsed = urllib.parse.urlparse(link)
        if parsed.hostname not in ('www.boe.es', 'boe.es'):
            continue
        identifier = urllib.parse.parse_qs(parsed.query).get('id', [''])[0]
        if not re.fullmatch(r'BOE-[A-Z]-\d{4}-\d+', identifier):
            continue
        if identifier in seen:
            continue
        date = parsedate_to_datetime(item.findtext('pubDate') or '').date()
        pdf_url = f'https://www.boe.es/boe/dias/{date:%Y/%m/%d}/pdfs/{identifier}.pdf'
        pdf = fetch(pdf_url)
        if not pdf.startswith(b'%PDF'):
            raise ValueError(f'La respuesta de {identifier} no es un PDF')
        CONSUME.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=CONSUME, suffix='.tmp', delete=False) as f:
            f.write(pdf)
            tmp = Path(f.name)
        tmp.replace(CONSUME / f'{identifier}.pdf')
        seen.add(identifier)
        guardar_estado(seen)
        new.append((title, link))
        print(f'Descargado {identifier}: {title}')
    guardar_estado(seen)
    if new:
        mail(new)
    else:
        print('Sin novedades.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Error de monitorización: {exc}', file=sys.stderr)
        sys.exit(1)
