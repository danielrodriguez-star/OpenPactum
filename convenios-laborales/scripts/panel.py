#!/usr/bin/env python3
"""Panel local de estado y acceso para OpenPactum."""
import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATE = Path(os.environ.get('OPENPACTUM_PANEL_ESTADO', '/estado/estado-rss.json'))
SERVICES = (
    ('changedetection', 'Vigilancia de fuentes', 'http://changedetection:5000/', 'http://localhost:5000'),
    ('paperless', 'Archivo documental', 'http://paperless:8000/', 'http://localhost:8000'),
    ('anythingllm', 'Asistente de consulta', 'http://anythingllm:3001/', 'http://localhost:3001'),
    ('ollama', 'Modelos locales', 'http://ollama:11434/api/tags', None),
)

PAGE = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#102923">
  <title>OpenPactum | Convenios laborales</title>
  <style>
    :root{color-scheme:light;--ink:#172b27;--muted:#60716c;--line:#dce5df;--paper:#f5f7f3;--card:#fff;--green:#236d53;--soft:#e5f3eb;--amber:#8a5b08;--amber-bg:#fff3d5}
    *{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
    header{background:#102923;color:white;padding:30px max(24px,calc((100vw - 1100px)/2)) 32px}
    header p{margin:6px 0 0;color:#c8d8d0}h1{font-size:clamp(1.8rem,4vw,2.7rem);line-height:1.15;margin:0;letter-spacing:-.03em}
    main{max-width:1100px;margin:28px auto;padding:0 20px 52px}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:22px}
    .toolbar p{margin:0;color:var(--muted)}button,.button{border:0;border-radius:9px;padding:10px 15px;background:var(--green);color:white;font:inherit;font-weight:650;text-decoration:none;cursor:pointer}
    button:hover,.button:hover{background:#18553f}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}
    .card,.section{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:20px}
    .card h2{font-size:1.03rem;margin:0 0 10px}.state{display:flex;align-items:center;gap:9px;font-weight:650}
    .dot{width:10px;height:10px;border-radius:50%;background:#9da9a4}.ready .dot{background:#299568}.down .dot{background:#c58a24}
    .details{font-size:.9rem;color:var(--muted);margin:5px 0 14px;overflow-wrap:anywhere}
    .open{color:var(--green);font-weight:650;text-decoration:none}.open:hover{text-decoration:underline}
    .section{margin-top:18px}.section h2{margin:0 0 8px;font-size:1.2rem}.section p{margin:5px 0;color:var(--muted)}
    .steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-top:16px}
    .step{border-top:2px solid var(--soft);padding-top:12px}.step strong{display:block;margin-bottom:4px}
    .notice{background:var(--amber-bg);border-radius:9px;padding:12px 14px;color:var(--amber);margin-top:18px}
    footer{margin-top:20px;color:var(--muted);font-size:.85rem}
    @media(max-width:560px){.toolbar{align-items:flex-start;flex-direction:column}main{margin-top:20px}}
  </style>
</head>
<body>
  <header><h1>OpenPactum</h1><p>Vigilancia y archivo local de convenios colectivos</p></header>
  <main>
    <div class="toolbar"><p id="updated" aria-live="polite">Comprobando servicios…</p><button id="refresh" type="button">Actualizar estado</button></div>
    <section class="grid" id="services" aria-label="Estado de los servicios"></section>
    <section class="section">
      <h2>Tu flujo de trabajo</h2>
      <p>OpenPactum detecta publicaciones del BOE, las archiva para su consulta y mantiene los documentos en este equipo.</p>
      <div class="steps">
        <div class="step"><strong>1. Configura fuentes y avisos</strong><p>Añade boletines o páginas en la herramienta de vigilancia. Configura el correo si quieres recibir alertas.</p><a class="open" href="http://localhost:5000">Abrir vigilancia ↗</a></div>
        <div class="step"><strong>2. Revisa el archivo</strong><p>Paperless procesa los PDF y permite buscarlos y organizarlos. En el primer arranque, las credenciales se guardan en <code>paperless/credenciales.txt</code> dentro de la carpeta de datos.</p><a class="open" href="http://localhost:8000">Abrir archivo ↗</a></div>
        <div class="step"><strong>3. Consulta tus documentos</strong><p>Configura el asistente, crea un espacio de trabajo y añade los convenios que quieras consultar.</p><a class="open" href="http://localhost:3001">Abrir asistente ↗</a></div>
      </div>
    </section>
    <section class="section" aria-live="polite">
      <h2>Vigilancia del BOE</h2>
      <p id="scan">Leyendo el estado de la vigilancia…</p>
      <p id="documents"></p>
      <div class="notice">Las respuestas del asistente pueden ser incompletas. Comprueba siempre las referencias y el texto oficial del convenio.</div>
    </section>
    <footer>Panel accesible solo desde este equipo. Las conexiones a BOE, las descargas y el correo salen a Internet cuando se configuran.</footer>
  </main>
  <script>
    const services=document.querySelector("#services");
    const updated=document.querySelector("#updated");
    const scan=document.querySelector("#scan");
    const documents=document.querySelector("#documents");
    const escapeText=value=>String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    async function refresh(){
      updated.textContent="Comprobando servicios…";
      try{
        const response=await fetch("/api/status",{cache:"no-store"});
        if(!response.ok)throw new Error(`Respuesta HTTP ${response.status}`);
        const data=await response.json();
        services.replaceChildren(...data.services.map(service=>{
          const card=document.createElement("article");
          card.className=`card ${service.ready?"ready":"down"}`;
          const link=service.url?`<a class="open" href="${escapeText(service.url)}">Abrir servicio ↗</a>`:"";
          const detail=service.error?escapeText(service.error):service.http_status?`Respuesta HTTP ${service.http_status}`:"Conectado";
          card.innerHTML=`<h2>${escapeText(service.name)}</h2><div class="state"><span class="dot"></span>${service.ready?"Disponible":"Sin conexión"}</div><p class="details">${detail}</p>${link}`;
          return card;
        }));
        const last=data.scan.last_scan?new Date(data.scan.last_scan).toLocaleString("es-ES"):"todavía no hay una ejecución registrada";
        scan.textContent=data.scan.error?`No se pudo leer el estado: ${data.scan.error}`:`Última comprobación: ${last}.`;
        documents.textContent=data.scan.documents===null?"":`${data.scan.documents} publicaciones del BOE constan en el estado del monitor.`;
        updated.textContent=`Estado actualizado ${new Date(data.checked_at).toLocaleTimeString("es-ES")}`;
      }catch(error){updated.textContent=`No se pudo actualizar el panel: ${error.message}`;}
    }
    document.querySelector("#refresh").addEventListener("click",refresh);
    refresh();
    setInterval(refresh,30000);
  </script>
</body>
</html>
""".encode('utf-8')


def probe(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'OpenPactum-Panel/1.0'})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            code = response.getcode()
        return True, code, None
    except urllib.error.HTTPError as exc:
        return exc.code < 500, exc.code, None if exc.code < 500 else f'El servicio respondió HTTP {exc.code}'
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, 'reason', exc)
        return False, None, str(reason)


def scan_status(path=STATE):
    try:
        documents = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(documents, list) or any(not isinstance(item, str) for item in documents):
            return {'documents': None, 'last_scan': None, 'error': 'el formato del estado no es válido'}
        last_scan = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        return {'documents': len(documents), 'last_scan': last_scan, 'error': None}
    except FileNotFoundError:
        return {'documents': None, 'last_scan': None, 'error': None}
    except json.JSONDecodeError:
        return {'documents': None, 'last_scan': None, 'error': 'el fichero del estado contiene JSON no válido'}
    except OSError as exc:
        return {'documents': None, 'last_scan': None, 'error': str(exc)}


def status():
    with ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
        results = list(pool.map(lambda service: probe(service[2]), SERVICES))
    services = [
        {
            'id': service_id,
            'name': name,
            'url': public_url,
            'ready': result[0],
            'http_status': result[1],
            'error': result[2],
        }
        for (service_id, name, _, public_url), result in zip(SERVICES, results)
    ]
    return {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'services': services,
        'scan': scan_status(),
    }


class Handler(BaseHTTPRequestHandler):
    def _respond(self, content_type, content, code=200):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header(
            'Content-Security-Policy',
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path == '/':
            self._respond('text/html; charset=utf-8', PAGE)
        elif self.path == '/api/status':
            content = json.dumps(status(), ensure_ascii=False).encode('utf-8')
            self._respond('application/json; charset=utf-8', content)
        else:
            self._respond('text/plain; charset=utf-8', b'No encontrado', 404)

def main():
    host = os.environ.get('OPENPACTUM_PANEL_HOST', '127.0.0.1')
    port = int(os.environ.get('OPENPACTUM_PANEL_PORT', '8080'))
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f'Panel OpenPactum disponible en http://{host}:{port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
