#!/usr/bin/env python3
"""Vigila el RSS del BOE, descarga PDFs oficiales y envía avisos SMTP."""
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
STATE = ROOT / 'scripts/.estado-rss.json'
CONSUME = ROOT / 'paperless/consume'
RSS = 'https://www.boe.es/rss/c.php?f=disposiciones&c=221'
USER_AGENT = 'OpenPactum/1.0 (vigilancia de convenios)'


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': USER_AGENT}), timeout=30) as r:
        return r.read()


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
                server.login(os.environ['SMTP_USER'], os.environ.get('SMTP_PASSWORD', ''))
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as server:
            if os.environ.get('SMTP_USER'):
                server.login(os.environ['SMTP_USER'], os.environ.get('SMTP_PASSWORD', ''))
            server.send_message(msg)


def main():
    root = ET.fromstring(fetch(RSS))
    seen = set(json.loads(STATE.read_text()) if STATE.exists() else [])
    new = []
    for item in root.findall('.//item'):
        title = (item.findtext('title') or '').strip()
        description = ' '.join(item.itertext())
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
        new.append((title, link))
        print(f'Descargado {identifier}: {title}')
    if new:
        STATE.write_text(json.dumps(sorted(seen), ensure_ascii=False))
        mail(new)
    else:
        print('Sin novedades.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Error de monitorización: {exc}', file=sys.stderr)
        sys.exit(1)
