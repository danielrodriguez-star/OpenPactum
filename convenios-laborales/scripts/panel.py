#!/usr/bin/env python3
"""Panel local de estado y acceso para OpenPactum."""
import json
import os
import urllib.error
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from openpactum_catalog import AgreementCatalog, CatalogError
from openpactum_regcon import RegconError, authorities, publication_url, search
from openpactum_summary import (
    SummaryBusyError,
    SummaryError,
    SummaryJobs,
)
from openpactum_paperless import PaperlessImportError, import_official_publication

STATE = Path(os.environ.get('OPENPACTUM_PANEL_ESTADO', '/estado/estado-rss.json'))
SUMMARY_CACHE = Path(os.environ.get('OPENPACTUM_PANEL_CACHE', '/cache/resumenes'))
CATALOG_DB = Path(os.environ.get('OPENPACTUM_PANEL_CATALOG', '/cache/catalogo.sqlite'))
OLLAMA_URL = os.environ.get('OPENPACTUM_OLLAMA_URL', 'http://ollama:11434')
OLLAMA_MODEL = os.environ.get('OPENPACTUM_OLLAMA_MODEL', 'qwen2.5:1.5b')
PAPERLESS_CONSUME = Path(os.environ.get('OPENPACTUM_PAPERLESS_CONSUME', '/consume'))
SUMMARY_JOBS = SummaryJobs()
AGREEMENT_CATALOG = AgreementCatalog(CATALOG_DB)
SECTORS = [
    {
        'id': 'educacion',
        'name': 'Educación',
        'description': 'Convenios de enseñanza, centros educativos y servicios relacionados.',
        'query': 'educación',
    },
    {
        'id': 'accion-social',
        'name': 'Acción e intervención social',
        'description': 'Convenios de intervención social, atención y servicios comunitarios.',
        'query': 'acción e intervención social',
    },
    {
        'id': 'ocio-educativo',
        'name': 'Ocio educativo',
        'description': 'Ocio educativo, animación sociocultural y actividades de tiempo libre.',
        'query': 'ocio educativo',
    },
]
VERIFIED_FACTS = {
    '99100155012015': {
        'name': 'III Convenio colectivo estatal de acción e intervención social 2026-2029',
        'source': 'https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-4641',
        'source_label': 'BOE-A-2026-4641',
        'facts': [
            {
                'label': 'Ámbito',
                'text': 'Estatal; comprende organizaciones cuya actividad principal sea la acción e intervención social. El encaje concreto depende del ámbito funcional del artículo 7 y del catálogo del anexo I.',
                'reference': 'Arts. 4 y 7; anexo I',
            },
            {
                'label': 'Vigencia',
                'text': 'Vigente desde su publicación hasta el 31 de diciembre de 2029. Los efectos económicos se aplican desde el 1 de enero de 2026.',
                'reference': 'Art. 6',
            },
            {
                'label': 'Jornada máxima anual',
                'text': '1.715 horas en 2026; 1.710 en 2027; 1.700 en 2028; 1.695 en 2029.',
                'reference': 'Art. 22',
            },
            {
                'label': 'Vacaciones',
                'text': '23 días laborables por año trabajado, o la parte proporcional correspondiente.',
                'reference': 'Art. 26',
            },
            {
                'label': 'Otras materias',
                'text': 'Regula subrogación y contratación, clasificación profesional, descansos y permisos, excedencias, representación, régimen disciplinario, formación, prevención de riesgos y medidas sociales.',
                'reference': 'Arts. 13-63',
            },
            {
                'label': 'Retribución',
                'text': 'La estructura incluye salario base, complementos salariales, otras percepciones compensatorias y pagas extraordinarias. Las cuantías son brutas anuales; para jornadas inferiores se prorratean. La tabla siguiente muestra solo salario base.',
                'reference': 'Art. 51; anexo II',
            },
        ],
        'salary_years': [
            {'year': 2026, 'values': ['30.816,22', '26.284,42', '23.720,72', '20.794,47', '18.127,19']},
            {'year': 2027, 'values': ['31.740,71', '27.072,96', '24.432,34', '21.418,31', '18.761,65']},
            {'year': 2028, 'values': ['33.169,04', '28.291,24', '25.531,80', '22.382,13', '19.605,91']},
            {'year': 2029, 'values': ['34.661,65', '29.564,34', '26.680,73', '23.389,33', '20.488,18']},
        ],
    },
}
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
    *{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
    header{background:#102923;color:white;padding:22px max(24px,calc((100vw - 1160px)/2)) 25px}
    .brand{display:flex;align-items:center;justify-content:space-between;gap:20px;max-width:1160px;margin:auto}
    header p{margin:4px 0 0;color:#c8d8d0}h1{font-size:clamp(1.65rem,4vw,2.2rem);line-height:1.15;margin:0;letter-spacing:-.03em}
    nav{display:flex;gap:8px;flex-wrap:wrap}nav a{color:#e2eee8;text-decoration:none;padding:7px 11px;border-radius:8px;font-weight:600}nav a:hover{background:#25473d}
    main{max-width:1160px;margin:28px auto;padding:0 20px 52px}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:20px}
    .toolbar p{margin:0;color:var(--muted)}button,.button{border:0;border-radius:9px;padding:10px 15px;background:var(--green);color:white;font:inherit;font-weight:650;text-decoration:none;cursor:pointer}
    button:hover,.button:hover{background:#18553f}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #93c9ab;outline-offset:2px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}
    .card,.section{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:20px}
    .card h2{font-size:1.03rem;margin:0 0 10px}.state{display:flex;align-items:center;gap:9px;font-weight:650}
    .dot{width:10px;height:10px;border-radius:50%;background:#9da9a4}.ready .dot{background:#299568}.down .dot{background:#c58a24}
    .details{font-size:.9rem;color:var(--muted);margin:5px 0 14px;overflow-wrap:anywhere}
    .open{color:var(--green);font-weight:650;text-decoration:none}.open:hover{text-decoration:underline}
    .section{margin-top:22px}.section h2{margin:0 0 8px;font-size:1.2rem}.section p{margin:5px 0;color:var(--muted)}
    .hero{background:#e5f3eb;border:1px solid #d0e7d8;border-radius:16px;padding:clamp(20px,4vw,36px);margin-bottom:20px}
    .eyebrow{font-size:.8rem;letter-spacing:.09em;text-transform:uppercase;color:var(--green);font-weight:750}
    .hero h2{font-size:clamp(1.5rem,4vw,2.2rem);line-height:1.2;letter-spacing:-.025em;margin:5px 0 9px;max-width:760px}
    .hero>p{max-width:740px;color:#52645e}
    .focus-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));gap:12px;margin-top:20px}
    .focus-card{display:flex;flex-direction:column;align-items:flex-start;background:white;border:1px solid var(--line);border-radius:12px;padding:16px}
    .focus-card strong{font-size:1rem}.focus-card p{flex:1;font-size:.9rem;color:var(--muted);margin:4px 0 12px}
    .focus-card .remove-sector{margin:8px 0 0;padding:5px 8px;background:#f5e9e5;color:#7b3829;font-size:.82rem}
    .add-sector{margin-top:14px}.add-sector summary{color:var(--green)}
    .sector-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-top:12px}
    .sector-form label{display:flex;flex-direction:column;gap:4px;font-size:.88rem;font-weight:650}
    .sector-form input{min-width:0;padding:9px;border:1px solid var(--line);border-radius:8px;font:inherit}
    .sector-form button{align-self:end;justify-self:start}
    .sector-message{grid-column:1/-1;font-size:.9rem;color:var(--muted)}
    .search-panel{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:20px;margin-top:20px}
    .filters{display:flex;align-items:end;flex-wrap:wrap;gap:12px;margin-top:12px}
    .field{display:flex;flex-direction:column;gap:4px;font-size:.88rem;font-weight:650}
    .field select{min-width:180px}
    .search-form input,.search-form select,.field select{padding:10px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--ink);font:inherit}
    .search-form{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 0}
    .search-form input{min-width:200px;flex:1}
    .search-form select{min-width:160px}
    .notice{background:var(--amber-bg);border-radius:9px;padding:12px 14px;color:var(--amber);margin-top:18px}
    .visually-hidden{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
    .results-wrap{overflow-x:auto;margin-top:14px}
    .results{width:100%;border-collapse:collapse;font-size:.9rem}
    .results th,.results td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid var(--line)}
    .results th{color:var(--muted);white-space:nowrap}
    .results td:first-child{font-family:ui-monospace,monospace;white-space:nowrap}
    .results a{color:var(--green);font-weight:650;white-space:nowrap}
    .results button{padding:6px 9px;font-size:.85rem;white-space:nowrap}
    .results .saved-action{background:#e5f3eb;color:#18553f}
    .results .summary-action{padding:6px 9px;font-size:.85rem}
    .results .summary-action:disabled{background:#9da9a4;cursor:wait}
    .results .import-action{padding:6px 9px;font-size:.85rem}
    .result-count{font-weight:650;color:var(--ink)!important;margin-top:12px!important}
    .pagination{display:flex;align-items:center;justify-content:center;gap:14px;margin-top:16px}
    .pagination button{padding:7px 12px}
    .pagination button:disabled{background:#9da9a4;cursor:not-allowed}
    .search-note{font-size:.9rem}
    .saved-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin-top:14px}
    .saved-item{background:white;border:1px solid var(--line);border-radius:11px;padding:15px}
    .saved-item h3{margin:0 0 5px;font-size:1rem}.saved-item p{font-size:.88rem}
    .saved-actions{display:flex;align-items:center;gap:12px;margin-top:10px}
    .saved-actions button{background:#f5e9e5;color:#7b3829;padding:6px 9px;font-size:.85rem}
    .saved-actions .import-action{background:var(--green);color:white}
    .convention-fiche{margin-top:14px;padding-top:10px;border-top:1px solid var(--line)}
    .convention-fiche summary{color:var(--green)}
    .fiche-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:12px 0}
    .fiche-fact{padding:11px;background:#f5f7f3;border-radius:9px}
    .fiche-fact strong{display:block}.fiche-fact p{margin:4px 0;color:var(--ink)}
    .salary-wrap{overflow-x:auto;margin-top:12px}
    .salary-table{width:100%;border-collapse:collapse;font-size:.9rem}
    .salary-table th,.salary-table td{text-align:right;padding:8px;border-bottom:1px solid var(--line);white-space:nowrap}
    .salary-table th:first-child,.salary-table td:first-child{text-align:left}
    .source-note{font-size:.86rem;color:var(--muted)}
    .ai-summary{margin-top:14px;padding:16px;background:#f5f7f3;border:1px solid var(--line);border-radius:10px}
    .ai-summary h3{margin:0 0 6px;font-size:1rem}.ai-summary[hidden]{display:none}
    .ai-summary pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;color:var(--ink);margin:12px 0}
    .empty{border:1px dashed #b9c9c0;padding:18px;border-radius:10px;color:var(--muted)}
    details{margin-top:22px}summary{cursor:pointer;font-weight:700}
    footer{margin-top:24px;color:var(--muted);font-size:.85rem}
    @media(max-width:620px){.brand{align-items:flex-start;flex-direction:column}nav{margin-left:-8px}.toolbar{align-items:flex-start;flex-direction:column}main{margin-top:18px}.search-form button{width:100%}}
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div><h1>OpenPactum</h1><p>Convenios colectivos para RR. HH. y nóminas</p></div>
      <nav aria-label="Navegación principal">
        <a href="#catalogo">Catálogo</a><a href="#guardados">Mis convenios</a><a href="#actualizaciones">Actualizaciones</a>
      </nav>
    </div>
  </header>
  <main>
    <div class="toolbar"><p id="updated" aria-live="polite">Comprobando servicios…</p><button id="refresh" type="button">Actualizar estado</button></div>
    <section class="hero">
      <span class="eyebrow">Biblioteca laboral · España</span>
      <h2>Encuentra el convenio. Consulta lo que necesitas aplicar.</h2>
      <p>Busca convenios por sector o territorio, sigue los documentos que utilizas y abre siempre la fuente oficial. Empieza con estos sectores y añade otros cuando los necesites.</p>
      <div class="focus-grid" id="focus-sectors" aria-label="Sectores destacados"></div>
      <details class="add-sector">
        <summary>Añadir otro sector</summary>
        <form class="sector-form" id="sector-form">
          <label>Nombre del sector<input id="sector-name" maxlength="60" required placeholder="Ej.: Dependencia"></label>
          <label>Texto para buscar en REGCON<input id="sector-query" maxlength="100" required placeholder="Ej.: atención a la dependencia"></label>
          <label>Descripción breve<input id="sector-description" maxlength="140" placeholder="Opcional"></label>
          <button type="submit">Añadir sector</button>
          <p id="sector-message" class="sector-message" role="status" aria-live="polite"></p>
        </form>
      </details>
    </section>
    <section class="search-panel" id="catalogo">
      <h2>Buscar en el catálogo nacional</h2>
      <p>Consulta los registros públicos estatales, autonómicos y provinciales de REGCON.</p>
      <form class="search-form" id="regcon-search">
        <label class="visually-hidden" for="regcon-mode">Buscar por</label>
        <select id="regcon-mode"><option value="query">Denominación</option><option value="code">Código o localizador</option></select>
        <label class="visually-hidden" for="regcon-authority">Buscar en una autoridad</label>
        <select id="regcon-authority"><option value="">Todas las autoridades</option></select>
        <label class="visually-hidden" for="regcon-term">Texto de búsqueda</label>
        <input id="regcon-term" type="search" maxlength="100" required placeholder="Ej.: intervención social, educación…">
        <button type="submit">Buscar convenios</button>
      </form>
      <div class="filters">
        <label class="field" for="filter-authority">Territorio en esta página<select id="filter-authority" disabled><option value="">Todos los territorios</option></select></label>
        <label class="field" for="filter-procedure">Tipo de trámite en esta página<select id="filter-procedure" disabled><option value="">Todos los trámites</option></select></label>
      </div>
      <p id="regcon-message" class="result-count" role="status" aria-live="polite"></p>
      <div id="regcon-results" class="results-wrap"></div>
      <p id="paperless-import-message" class="search-note" role="status" aria-live="polite"></p>
      <details class="coverage-panel">
        <summary>Cobertura territorial e histórica de REGCON</summary>
        <p id="coverage-message" class="search-note" role="status" aria-live="polite">Consultando las autoridades disponibles…</p>
        <div id="coverage-list" class="results-wrap"></div>
        <p id="historical-link" class="search-note"></p>
      </details>
      <section id="regcon-summary" class="ai-summary" aria-live="polite" hidden>
        <h3 id="summary-title">Resumen asistido por IA</h3>
        <p id="summary-status" role="status"></p>
        <pre id="summary-content"></pre>
        <p id="summary-source" class="source-note"></p>
        <p class="source-note">El modelo se ejecuta localmente con Ollama. Comprueba cada cita y dato en el texto oficial antes de aplicarlo; el resumen puede omitir información y no sustituye asesoramiento jurídico.</p>
      </section>
      <div id="regcon-pagination" class="pagination"></div>
      <p class="search-note">Puedes archivar las publicaciones oficiales en Paperless: se conservan los PDF originales, incluidos los enlazados desde una página HTML; si no hay PDF directo, la página se guarda como texto con su URL de origen. Se descargan bajo demanda al directorio de entrada compartido; Paperless las procesa después. También puedes generar resúmenes bajo demanda con IA local. Los resultados son trámites y pueden incluir revisiones, no un inventario de convenios únicos. La consulta histórica anterior al 1 de octubre de 2010 se mantiene aparte.</p>
    </section>
    <section class="section" id="convenios-detectados">
      <h2>Catálogo de convenios consultados</h2>
      <p>Agrupa cada convenio por código y autoridad y mantiene relacionados los trámites y versiones que han aparecido en tus búsquedas. Solo incluye registros consultados desde este panel; no representa el inventario nacional completo.</p>
      <p id="catalog-message" class="search-note" role="status" aria-live="polite">Cargando catálogo local…</p>
      <div id="catalog-list" class="saved-list"></div>
      <div id="catalog-pagination" class="pagination"></div>
    </section>
    <section class="section" id="guardados">
      <h2>Mis convenios</h2>
      <p>Guarda aquí los convenios que utilizas con más frecuencia. La lista y tus sectores añadidos se conservan en este navegador.</p>
      <div id="saved-message" class="search-note" role="status" aria-live="polite"></div>
      <div id="saved-list" class="saved-list"></div>
    </section>
    <section class="section" id="actualizaciones">
      <h2>Actualizaciones y archivo</h2>
      <p id="scan">Leyendo el estado de la vigilancia…</p>
      <p id="documents"></p>
      <div class="notice">Las fichas disponibles enlazan el texto oficial y muestran las referencias de cada dato. Comprueba siempre el ámbito y los documentos posteriores antes de aplicar un convenio: esta ficha informativa no sustituye el asesoramiento laboral.</div>
    </section>
    <details>
      <summary>Estado técnico de los servicios</summary>
      <section class="grid" id="services" aria-label="Estado de los servicios"></section>
      <p><a class="open" href="http://localhost:5000">Vigilancia de fuentes ↗</a> · <a class="open" href="http://localhost:8000">Archivo documental ↗</a> · <a class="open" href="http://localhost:3001">Asistente ↗</a></p>
    </section>
    </details>
    <footer>Panel accesible solo desde este equipo. Las búsquedas se consultan en REGCON. Las fichas y tablas disponibles enlazan su fuente oficial; para los demás convenios, contrasta siempre el documento antes de aplicar condiciones.</footer>
  </main>
  <script>
    const services=document.querySelector("#services");
    const updated=document.querySelector("#updated");
    const scan=document.querySelector("#scan");
    const documents=document.querySelector("#documents");
    const regconForm=document.querySelector("#regcon-search");
    const regconTerm=document.querySelector("#regcon-term");
    const regconMode=document.querySelector("#regcon-mode");
    const regconAuthority=document.querySelector("#regcon-authority");
    const regconMessage=document.querySelector("#regcon-message");
    const regconResults=document.querySelector("#regcon-results");
    const regconPagination=document.querySelector("#regcon-pagination");
    const regconSummary=document.querySelector("#regcon-summary");
    const summaryTitle=document.querySelector("#summary-title");
    const summaryStatus=document.querySelector("#summary-status");
    const summaryContent=document.querySelector("#summary-content");
    const summarySource=document.querySelector("#summary-source");
    const filterAuthority=document.querySelector("#filter-authority");
    const filterProcedure=document.querySelector("#filter-procedure");
    const catalogMessage=document.querySelector("#catalog-message");
    const catalogList=document.querySelector("#catalog-list");
    const catalogPagination=document.querySelector("#catalog-pagination");
    const coverageMessage=document.querySelector("#coverage-message");
    const coverageList=document.querySelector("#coverage-list");
    const historicalLink=document.querySelector("#historical-link");
    const savedList=document.querySelector("#saved-list");
    const savedMessage=document.querySelector("#saved-message");
    const savedKey="openpactum-convenios-guardados-v1";
    const sectorKey="openpactum-sectores-v1";
    const defaultSectors=__SECTOR_DATA__;
    const verifiedFacts=__VERIFIED_FACTS__;
    const focusSectors=document.querySelector("#focus-sectors");
    const sectorForm=document.querySelector("#sector-form");
    const sectorMessage=document.querySelector("#sector-message");
    let currentRegconResults=null;
    let catalogOffset=0;
    const catalogLimit=50;
    let summaryRequestId=0;
    let savedConventions=[];
    let sectors=[...defaultSectors];
    const paperlessImportMessage=document.querySelector("#paperless-import-message");
    const escapeText=value=>String(value).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
    function paperlessImportAction(mode,query,page,record,authority,title,code){
      return `<button type="button" class="import-action" data-import-mode="${escapeText(mode)}" data-import-query="${escapeText(query)}" data-import-page="${page}" data-import-record="${escapeText(record)}" data-import-authority="${escapeText(authority||"")}" data-import-title="${escapeText(title)}" data-import-code="${escapeText(code)}">Archivar en Paperless</button>`;
    }
    function loadSectors(){
      try{
        const saved=JSON.parse(localStorage.getItem(sectorKey)||"[]");
        const defaults=new Set(defaultSectors.map(item=>item.name.toLocaleLowerCase("es")));
        const custom=Array.isArray(saved)?saved.filter(item=>
          item&&typeof item.id==="string"&&item.id.startsWith("custom-")&&
          typeof item.name==="string"&&item.name.trim().length>0&&item.name.length<=60&&
          typeof item.query==="string"&&item.query.trim().length>0&&item.query.length<=100&&
          typeof item.description==="string"&&item.description.length<=140&&
          !defaults.has(item.name.trim().toLocaleLowerCase("es"))
        ).slice(0,40):[];
        sectors=[...defaultSectors,...custom];
        renderSectors();
      }catch(error){
        sectors=[...defaultSectors];
        renderSectors();
        sectorMessage.textContent=`No se pudieron leer los sectores guardados: ${error.message}`;
      }
    }
    function persistSectors(custom){
      try{
        localStorage.setItem(sectorKey,JSON.stringify(custom));
        sectors=[...defaultSectors,...custom];
        renderSectors();
        return true;
      }catch(error){
        sectorMessage.textContent=`No se pudieron guardar los sectores en este navegador: ${error.message}`;
        return false;
      }
    }
    function renderSectors(){
      focusSectors.innerHTML=sectors.map(item=>{
        const remove=defaultSectors.some(defaultSector=>defaultSector.id===item.id)
          ?""
          :`<button class="remove-sector" type="button" data-remove-sector="${escapeText(item.id)}">Quitar sector</button>`;
        return `<article class="focus-card"><strong>${escapeText(item.name)}</strong><p>${escapeText(item.description||"Busca convenios de este sector en REGCON.")}</p><button type="button" data-search="${escapeText(item.query)}">Ver convenios</button>${remove}</article>`;
      }).join("");
      focusSectors.querySelectorAll("[data-search]").forEach(button=>{
        button.addEventListener("click",()=>searchSector(button.dataset.search));
      });
      focusSectors.querySelectorAll("[data-remove-sector]").forEach(button=>{
        button.addEventListener("click",()=>{
          const custom=sectors.filter(item=>!defaultSectors.some(base=>base.id===item.id));
          persistSectors(custom.filter(item=>item.id!==button.dataset.removeSector));
        });
      });
    }
    function searchSector(query){
      regconMode.value="query";
      regconTerm.value=query;
      document.querySelector("#catalogo").scrollIntoView({behavior:"smooth"});
      searchRegcon(1);
    }
    sectorForm.addEventListener("submit",event=>{
      event.preventDefault();
      const name=document.querySelector("#sector-name").value.trim();
      const query=document.querySelector("#sector-query").value.trim();
      const description=document.querySelector("#sector-description").value.trim();
      if(name.length<2||query.length<2){
        sectorMessage.textContent="Indica un nombre y un texto de búsqueda de al menos 2 caracteres.";
        return;
      }
      if(sectors.some(item=>item.name.toLocaleLowerCase("es")===name.toLocaleLowerCase("es"))){
        sectorMessage.textContent="Ya existe un sector con ese nombre.";
        return;
      }
      const custom=sectors.filter(item=>!defaultSectors.some(base=>base.id===item.id));
      if(custom.length>=40){
        sectorMessage.textContent="Has alcanzado el máximo de 40 sectores añadidos.";
        return;
      }
      const next=[...custom,{id:`custom-${Date.now()}-${Math.random().toString(16).slice(2)}`,name,query,description}];
      if(persistSectors(next)){
        sectorForm.reset();
        sectorMessage.textContent=`Sector «${name}» añadido.`;
      }
    });
    function loadSavedConventions(){
      try{
        const saved=JSON.parse(localStorage.getItem(savedKey)||"[]");
        savedConventions=Array.isArray(saved)?saved.map(item=>
          item&&typeof item==="object"
            ?{...item,authority_filter:typeof item.authority_filter==="string"?item.authority_filter:""}
            :item
        ).filter(item=>
          item&&typeof item.code==="string"&&typeof item.denomination==="string"&&
          typeof item.authority==="string"&&typeof item.procedure==="string"&&
          typeof item.record_id==="string"&&typeof item.query==="string"&&
          Number.isInteger(item.page)&&item.page>0&&
          ["query","code"].includes(item.mode)&&typeof item.publication_available==="boolean"
        ):[];
        renderSavedConventions();
      }catch(error){
        savedMessage.textContent=`No se pudo leer la lista guardada de este navegador: ${error.message}`;
      }
    }
    function persistSavedConventions(){
      try{
        localStorage.setItem(savedKey,JSON.stringify(savedConventions));
        renderSavedConventions();
        return true;
      }catch(error){
        savedMessage.textContent=`No se pudieron guardar los cambios en este navegador: ${error.message}`;
        return false;
      }
    }
    function renderSavedConventions(){
      savedMessage.textContent=savedConventions.length
        ?`${savedConventions.length} convenio(s) guardado(s) en este navegador.`
        :"Todavía no has guardado convenios.";
      if(!savedConventions.length){
        savedList.innerHTML='<div class="empty">Busca un convenio y pulsa «Guardar» para tenerlo a mano aquí.</div>';
        return;
      }
      savedList.innerHTML=savedConventions.map(item=>{
        const params=new URLSearchParams({mode:item.mode,q:item.query,page:String(item.page),record:item.record_id,authority:item.authority_filter||""});
        const publication=item.publication_available
          ?`<a class="open" href="/api/regcon/publication?${params}" target="_blank" rel="noopener noreferrer">Publicación oficial ↗</a>`
          :'<span class="search-note">Sin enlace directo</span>';
        const fiche=renderConventionFacts(item.code);
        const summaryAction=item.publication_available
          ?`<button type="button" class="summary-action" data-summary-mode="${escapeText(item.mode)}" data-summary-query="${escapeText(item.query)}" data-summary-page="${item.page}" data-summary-record="${escapeText(item.record_id)}" data-summary-authority="${escapeText(item.authority_filter||"")}">Resumen IA</button>`
          :'<span class="search-note">Este trámite no tiene texto oficial directo para resumir.</span>';
        const importAction=item.publication_available
          ?paperlessImportAction(item.mode,item.query,item.page,item.record_id,item.authority_filter,item.denomination,item.code)
          :"";
        return `<article class="saved-item"><h3>${escapeText(item.denomination)}</h3><p><strong>${escapeText(item.code)}</strong> · ${escapeText(item.authority)}</p><p>${escapeText(item.procedure)}</p><div class="saved-actions">${publication}${summaryAction}${importAction}<button type="button" data-remove-code="${escapeText(item.code)}">Quitar</button></div>${fiche}</article>`;
      }).join("");
      savedList.querySelectorAll("[data-remove-code]").forEach(button=>{
        button.addEventListener("click",()=>{
          savedConventions=savedConventions.filter(item=>item.code!==button.dataset.removeCode);
          persistSavedConventions();
          if(currentRegconResults)renderRegconRows();
        });
      });
      bindSummaryButtons(savedList);
      bindImportButtons(savedList);
    }
    function renderCatalog(data){
      catalogMessage.textContent=data.total
        ?`${data.total.toLocaleString("es-ES")} convenios únicos detectados; se muestran ${data.conventions.length} en esta página.`
        :"El catálogo se irá completando al consultar resultados de REGCON.";
      catalogList.innerHTML=data.conventions.length?data.conventions.map(item=>{
        const publications=item.publications.map(publication=>{
          const params=new URLSearchParams({
            mode:publication.mode,
            q:publication.query,
            page:String(publication.page),
            record:publication.record_id||"",
            authority:publication.authority_code||""
          });
          const source=publication.publication_available&&publication.record_id
            ?`<a class="open" href="/api/regcon/publication?${params}" target="_blank" rel="noopener noreferrer">Abrir publicación ↗</a>`
            :'<span class="search-note">Sin enlace directo</span>';
          const summary=publication.publication_available&&publication.record_id
            ?`<button type="button" class="summary-action" data-summary-mode="${escapeText(publication.mode)}" data-summary-query="${escapeText(publication.query)}" data-summary-page="${publication.page}" data-summary-record="${escapeText(publication.record_id)}" data-summary-authority="${escapeText(publication.authority_code||"")}">Resumen IA</button>`
            :"";
          const importAction=publication.publication_available&&publication.record_id
            ?paperlessImportAction(publication.mode,publication.query,publication.page,publication.record_id,publication.authority_code,item.denomination,item.code)
            :"";
          return `<article class="fiche-fact"><strong>${escapeText(publication.procedure||"Trámite REGCON")}</strong><p>Publicación: ${escapeText(publication.publication_date||"fecha no indicada")} · Vigencia registrada: ${escapeText(publication.valid_from||"sin inicio")} – ${escapeText(publication.valid_until||"sin fin")}</p><p>Detectado en búsqueda «${escapeText(publication.query)}» el ${new Date(publication.last_seen_at).toLocaleDateString("es-ES")}.</p><div class="saved-actions">${source}${summary}${importAction}</div></article>`;
        }).join("");
        return `<article class="saved-item"><h3>${escapeText(item.denomination)}</h3><p><strong>${escapeText(item.code||"Sin código")}</strong> · ${escapeText(item.authority)}</p><p>${item.publication_count} trámite(s) relacionado(s). Vigencia registrada: ${escapeText(item.valid_from||"sin inicio")} – ${escapeText(item.valid_until||"sin fin")}.</p><details><summary>Ver trámites y versiones</summary><div class="fiche-facts">${publications}</div></details></article>`;
      }).join(""):'<div class="empty">Todavía no hay convenios detectados. Haz una búsqueda para empezar a construir el catálogo local.</div>';
      bindSummaryButtons(catalogList);
      bindImportButtons(catalogList);
      catalogPagination.replaceChildren();
      if(data.total>data.offset+data.limit||data.offset>0){
        const previous=document.createElement("button");
        previous.type="button";
        previous.textContent="Anterior";
        previous.disabled=data.offset===0;
        previous.addEventListener("click",()=>loadCatalog(Math.max(0,data.offset-data.limit)));
        const page=document.createElement("span");
        page.textContent=`Convenios ${data.total?data.offset+1:0}–${Math.min(data.offset+data.limit,data.total)} de ${data.total}`;
        const next=document.createElement("button");
        next.type="button";
        next.textContent="Siguiente";
        next.disabled=data.offset+data.limit>=data.total;
        next.addEventListener("click",()=>loadCatalog(data.offset+data.limit));
        catalogPagination.append(previous,page,next);
      }
    }
    async function loadCoverage(){
      coverageMessage.textContent="Consultando las autoridades disponibles en REGCON…";
      try{
        const response=await fetch("/api/regcon/coverage",{cache:"no-store"});
        const data=await response.json();
        if(!response.ok)throw new Error(data.error||`Respuesta HTTP ${response.status}`);
        regconAuthority.replaceChildren(new Option("Todas las autoridades",""));
        for(const authority of data.authorities){
          regconAuthority.add(new Option(authority.name,authority.code));
        }
        coverageMessage.textContent=`REGCON ofrece ${data.authorities.length} autoridades para delimitar la búsqueda. El catálogo local ha observado convenios en ${data.observed_authorities} de ellas; las demás aún no tienen resultados guardados por este panel. Comprobado ${new Date(data.checked_at).toLocaleString("es-ES")}.`;
        const rows=data.authorities.map(authority=>{
          const observed=data.observed[authority.name];
          return `<tr><td>${escapeText(authority.name)}</td><td>${observed?observed.conventions.toLocaleString("es-ES"):"—"}</td><td>${observed?`Consultado ${new Date(observed.last_seen_at).toLocaleDateString("es-ES")}`:"Pendiente de consulta"}</td></tr>`;
        });
        coverageList.innerHTML=`<table class="results"><thead><tr><th>Autoridad laboral</th><th>Convenios detectados localmente</th><th>Estado</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
        const historical=document.createElement("a");
        historical.className="open";
        historical.href=data.historical_url;
        historical.target="_blank";
        historical.rel="noopener noreferrer";
        historical.textContent="Consultar en REGCON los convenios anteriores al 1/10/2010 ↗";
        historicalLink.replaceChildren(historical,document.createTextNode(" · Consulta histórica separada; no se integra todavía en el catálogo local."));
      }catch(error){
        coverageMessage.textContent=`No se pudo comprobar la cobertura de REGCON: ${error.message}`;
      }
    }
    async function loadCatalog(offset=0){
      catalogOffset=offset;
      catalogMessage.textContent="Leyendo el catálogo local…";
      try{
        const params=new URLSearchParams({limit:String(catalogLimit),offset:String(offset)});
        const response=await fetch(`/api/catalog?${params}`,{cache:"no-store"});
        const data=await response.json();
        if(!response.ok)throw new Error(data.error||`Respuesta HTTP ${response.status}`);
        renderCatalog(data);
      }catch(error){
        catalogMessage.textContent=`No se pudo leer el catálogo local: ${error.message}`;
      }
    }
    function renderConventionFacts(code){
      const fiche=verifiedFacts[code];
      if(!fiche){
        return '<p class="source-note">La ficha con resumen y tabla salarial verificados todavía no está disponible para este convenio.</p>';
      }
      const facts=fiche.facts.map(fact=>
        `<article class="fiche-fact"><strong>${escapeText(fact.label)}</strong><p>${escapeText(fact.text)}</p><span class="source-note">${escapeText(fact.reference)}</span></article>`
      ).join("");
      const years=fiche.salary_years;
      const headers=years.map(item=>`<th scope="col">${item.year}</th>`).join("");
      const rows=years[0].values.map((value,index)=>
        `<tr><th scope="row">Grupo ${index}</th>${years.map(item=>`<td>${escapeText(item.values[index])} €</td>`).join("")}</tr>`
      ).join("");
      return `<details class="convention-fiche"><summary>Resumen y tablas salariales</summary><h4>${escapeText(fiche.name)}</h4><div class="fiche-facts">${facts}</div><h4>Salario base bruto anual</h4><p>Importes oficiales por grupo profesional. No incluyen complementos ni otras percepciones.</p><div class="salary-wrap"><table class="salary-table"><thead><tr><th scope="col">Grupo</th>${headers}</tr></thead><tbody>${rows}</tbody></table></div><p class="source-note">Fuente: <a class="open" href="${escapeText(fiche.source)}" target="_blank" rel="noopener noreferrer">${escapeText(fiche.source_label)} · anexo II y artículos indicados ↗</a>. Importes en euros brutos anuales a jornada completa.</p></details>`;
    }
    function fillFilter(select,values,label){
      const selected=select.value;
      select.replaceChildren(new Option(label,""));
      [...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b,"es")).forEach(value=>{
        select.add(new Option(value,value));
      });
      select.disabled=values.length===0;
      select.value=[...select.options].some(option=>option.value===selected)?selected:"";
    }
    function renderRegconRows(){
      if(!currentRegconResults)return;
      const data=currentRegconResults;
      const filtered=data.results.filter(item=>
        (!filterAuthority.value||item.authority===filterAuthority.value)&&
        (!filterProcedure.value||item.procedure===filterProcedure.value)
      );
      const savedCodes=new Set(savedConventions.map(item=>item.code));
      if(filtered.length){
        const rows=filtered.map(item=>{
          const params=new URLSearchParams({mode:data.mode,q:data.query,page:String(data.page),record:item.record_id,authority:data.authority_filter||""});
          const source=item.publication_available
            ?`<a href="/api/regcon/publication?${params}" target="_blank" rel="noopener noreferrer">Publicación oficial ↗</a>`
            :"<span>Sin enlace directo</span>";
          const saveAction=savedCodes.has(item.code)
            ?'<button type="button" class="saved-action" disabled>Guardado</button>'
            :`<button type="button" data-save-code="${escapeText(item.code)}">Guardar</button>`;
          const summaryAction=item.publication_available
            ?`<button type="button" class="summary-action" data-summary-mode="${escapeText(data.mode)}" data-summary-query="${escapeText(data.query)}" data-summary-page="${data.page}" data-summary-record="${escapeText(item.record_id)}" data-summary-authority="${escapeText(data.authority_filter||"")}">Resumen IA</button>`
            :'<span class="search-note">No disponible</span>';
          const importAction=item.publication_available
            ?paperlessImportAction(data.mode,data.query,data.page,item.record_id,data.authority_filter,item.denomination,item.code)
            :'<span class="search-note">No disponible</span>';
          return `<tr><td>${escapeText(item.code)}</td><td>${escapeText(item.denomination)}</td><td>${escapeText(item.procedure)}</td><td>${escapeText(item.authority)}</td><td>${escapeText(item.publication_date)}</td><td>${escapeText(item.valid_from)} – ${escapeText(item.valid_until)}</td><td>${source}</td><td>${saveAction}</td><td>${summaryAction}</td><td>${importAction}</td></tr>`;
        });
        regconResults.innerHTML=`<table class="results"><thead><tr><th>Código</th><th>Denominación</th><th>Trámite</th><th>Autoridad</th><th>Inscripción</th><th>Vigencia</th><th>Fuente</th><th>Mi lista</th><th>Resumen</th><th>Paperless</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
      }else{
        regconResults.innerHTML=filterAuthority.value||filterProcedure.value
          ?'<div class="empty">No hay resultados en esta página con esos filtros.</div>'
          :"";
      }
      regconResults.querySelectorAll("[data-save-code]").forEach(button=>{
        button.addEventListener("click",()=>{
          const matches=data.results.filter(result=>result.code===button.dataset.saveCode);
          const item=matches.find(result=>result.procedure.includes("CONVENIO COLECTIVO (TEXTO NUEVO)"))||
            matches.find(result=>result.procedure.includes("CONVENIO COLECTIVO"))||
            matches[0];
          if(!item)return;
          if(savedConventions.some(saved=>saved.code===item.code)){
            renderRegconRows();
            return;
          }
          savedConventions.push({
            ...item,
            mode:data.mode,
            query:data.query,
            page:data.page,
            authority_filter:data.authority_filter||""
          });
          if(persistSavedConventions())renderRegconRows();
        });
      });
      bindSummaryButtons(regconResults);
      bindImportButtons(regconResults);
    }
    function bindSummaryButtons(container){
      container.querySelectorAll("[data-summary-record]").forEach(button=>{
        button.addEventListener("click",()=>requestSummary(button));
      });
    }
    function bindImportButtons(container){
      container.querySelectorAll("[data-import-record]").forEach(button=>{
        button.addEventListener("click",()=>requestPaperlessImport(button));
      });
    }
    async function requestPaperlessImport(button){
      paperlessImportMessage.textContent="Descargando la publicación oficial y enviándola a Paperless…";
      document.querySelectorAll("[data-import-record]").forEach(importButton=>{
        importButton.disabled=true;
      });
      try{
        const response=await fetch("/api/regcon/import",{
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({
            mode:button.dataset.importMode,
            query:button.dataset.importQuery,
            page:Number(button.dataset.importPage),
            record:button.dataset.importRecord,
            authority:button.dataset.importAuthority||"",
            title:button.dataset.importTitle,
            code:button.dataset.importCode
          })
        });
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||`Respuesta HTTP ${response.status}`);
        paperlessImportMessage.textContent=result.status==="already_queued"
          ?"Esta publicación ya está pendiente de procesamiento en Paperless."
          :"Publicación enviada a Paperless; aparecerá cuando termine de procesarla.";
      }catch(error){
        paperlessImportMessage.textContent=`No se pudo archivar la publicación: ${error.message}`;
      }finally{
        document.querySelectorAll("[data-import-record]").forEach(importButton=>{
          importButton.disabled=false;
        });
      }
    }
    const delay=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));
    async function requestSummary(button){
      const requestId=++summaryRequestId;
      const params=new URLSearchParams({
        mode:button.dataset.summaryMode,
        q:button.dataset.summaryQuery,
        page:button.dataset.summaryPage,
        record:button.dataset.summaryRecord,
        authority:button.dataset.summaryAuthority||""
      });
      regconSummary.hidden=false;
      summaryTitle.textContent="Resumen asistido por IA";
      summaryStatus.textContent="Descargando y analizando el texto oficial con Ollama local. Puede tardar unos minutos; el resultado se guardará en caché.";
      summaryContent.textContent="";
      summarySource.textContent="";
      document.querySelectorAll("[data-summary-record]").forEach(summaryButton=>{
        summaryButton.disabled=true;
      });
      try{
        const response=await fetch(`/api/regcon/summary?${params}`,{cache:"no-store"});
        let job=await response.json();
        if(!response.ok)throw new Error(job.error||`Respuesta HTTP ${response.status}`);
        while(job.status==="pending"){
          if(requestId!==summaryRequestId)return;
          summaryStatus.textContent="El modelo local está analizando el documento oficial. Puedes dejar esta página abierta; el resumen se guardará para futuras consultas.";
          await delay(1500);
          const poll=await fetch(`/api/regcon/summary/status?id=${encodeURIComponent(job.job_id)}`,{cache:"no-store"});
          job=await poll.json();
          if(!poll.ok)throw new Error(job.error||`Respuesta HTTP ${poll.status}`);
        }
        if(job.status!=="done")throw new Error(job.error||"El trabajo de resumen no se completó.");
        const data=job.result;
        if(requestId!==summaryRequestId)return;
        const documentLocation=data.pages
          ?`${data.pages} páginas`
          :"texto web sin paginación";
        summaryStatus.textContent=data.cached
          ?`Resumen reutilizado de la caché local · ${documentLocation} · modelo ${data.model}.`
          :`Resumen generado y guardado en caché local · ${documentLocation} · modelo ${data.model}.`;
        summaryContent.textContent=data.summary;
        const sourceLink=document.createElement("a");
        sourceLink.className="open";
        sourceLink.href=data.source_url;
        sourceLink.target="_blank";
        sourceLink.rel="noopener noreferrer";
        sourceLink.textContent="Abrir documento oficial ↗";
        summarySource.replaceChildren(document.createTextNode("Fuente: "),sourceLink);
        regconSummary.scrollIntoView({behavior:"smooth",block:"nearest"});
      }catch(error){
        if(requestId===summaryRequestId)summaryStatus.textContent=`No se pudo generar el resumen: ${error.message}`;
      }finally{
        document.querySelectorAll("[data-summary-record]").forEach(summaryButton=>{
          summaryButton.disabled=false;
        });
      }
    }
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
    function showRegconResults(data){
      currentRegconResults=data;
      regconMessage.textContent=data.total
        ?`${data.total.toLocaleString("es-ES")} trámites en REGCON · página ${data.page} · ${data.results.length} resultados en esta página.`
        :"No se han encontrado trámites.";
      fillFilter(filterAuthority,data.results.map(item=>item.authority),"Todos los territorios");
      fillFilter(filterProcedure,data.results.map(item=>item.procedure),"Todos los trámites");
      renderRegconRows();
      regconPagination.replaceChildren();
      if(data.pages>1){
        const previous=document.createElement("button");
        previous.type="button";
        previous.textContent="Anterior";
        previous.disabled=data.page<=1;
        previous.addEventListener("click",()=>searchRegcon(data.page-1));
        const summary=document.createElement("span");
        summary.textContent=`Página ${data.page.toLocaleString("es-ES")} de ${data.pages.toLocaleString("es-ES")}`;
        const next=document.createElement("button");
        next.type="button";
        next.textContent="Siguiente";
        next.disabled=data.page>=data.pages;
        next.addEventListener("click",()=>searchRegcon(data.page+1));
        regconPagination.append(previous,summary,next);
      }
    }
    async function searchRegcon(page=1){
      const term=regconTerm.value.trim();
      if(!term)return;
      regconMessage.textContent="Consultando REGCON…";
      regconResults.replaceChildren();
      regconPagination.replaceChildren();
      const params=new URLSearchParams({
        mode:regconMode.value,
        q:term,
        page:String(page),
        authority:regconAuthority.value
      });
      try{
        const response=await fetch(`/api/regcon/search?${params}`,{cache:"no-store"});
        const data=await response.json();
        if(!response.ok)throw new Error(data.error||`Respuesta HTTP ${response.status}`);
        showRegconResults(data);
        loadCatalog(catalogOffset);
      }catch(error){
        regconMessage.textContent=`No se pudo consultar REGCON: ${error.message}`;
      }
    }
    regconForm.addEventListener("submit",event=>{
      event.preventDefault();
      searchRegcon(1);
    });
    filterAuthority.addEventListener("change",renderRegconRows);
    filterProcedure.addEventListener("change",renderRegconRows);
    loadSectors();
    loadSavedConventions();
    loadCatalog();
    loadCoverage();
    refresh();
    setInterval(refresh,30000);
  </script>
</body>
</html>
""".replace(
    '__SECTOR_DATA__', json.dumps(SECTORS, ensure_ascii=False)
).replace(
    '__VERIFIED_FACTS__', json.dumps(VERIFIED_FACTS, ensure_ascii=False)
).encode('utf-8')


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

    def _redirect(self, url):
        self.send_response(302)
        self.send_header('Location', url)
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == '/':
            self._respond('text/html; charset=utf-8', PAGE)
        elif parsed.path == '/api/status':
            content = json.dumps(status(), ensure_ascii=False).encode('utf-8')
            self._respond('application/json; charset=utf-8', content)
        elif parsed.path == '/api/regcon/coverage':
            try:
                coverage = authorities()
                observed = AGREEMENT_CATALOG.coverage_by_authority()
                coverage['observed'] = observed
                coverage['observed_authorities'] = sum(
                    authority['name'] in observed
                    for authority in coverage['authorities']
                )
                self._respond(
                    'application/json; charset=utf-8',
                    json.dumps(coverage, ensure_ascii=False).encode('utf-8'),
                )
            except RegconError as exc:
                self._respond(
                    'application/json; charset=utf-8',
                    json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8'),
                    502,
                )
            except CatalogError as exc:
                self._respond(
                    'application/json; charset=utf-8',
                    json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8'),
                    500,
                )
        elif parsed.path == '/api/catalog':
            params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            try:
                limit = int(params.get('limit', ['50'])[0])
                offset = int(params.get('offset', ['0'])[0])
                result = AGREEMENT_CATALOG.list_conventions(limit, offset)
                self._respond(
                    'application/json; charset=utf-8',
                    json.dumps(result, ensure_ascii=False).encode('utf-8'),
                )
            except ValueError as exc:
                self._respond(
                    'application/json; charset=utf-8',
                    json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8'),
                    400,
                )
            except CatalogError as exc:
                self._respond(
                    'application/json; charset=utf-8',
                    json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8'),
                    500,
                )
        elif parsed.path in (
            '/api/regcon/search',
            '/api/regcon/publication',
            '/api/regcon/summary',
            '/api/regcon/summary/status',
        ):
            params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            try:
                if parsed.path == '/api/regcon/summary/status':
                    result = SUMMARY_JOBS.get(params.get('id', [''])[0])
                    if result is None:
                        self._respond(
                            'application/json; charset=utf-8',
                            json.dumps({'error': 'No se encontró el trabajo de resumen.'}).encode('utf-8'),
                            404,
                        )
                    else:
                        self._respond(
                            'application/json; charset=utf-8',
                            json.dumps(result, ensure_ascii=False).encode('utf-8'),
                        )
                else:
                    mode = params.get('mode', ['query'])[0]
                    term = params.get('q', [''])[0]
                    page = int(params.get('page', ['1'])[0])
                    authority = params.get('authority', [''])[0]
                    if parsed.path == '/api/regcon/search':
                        result = search(mode, term, page, authority)
                        AGREEMENT_CATALOG.record_search(result)
                        content = json.dumps(result, ensure_ascii=False).encode('utf-8')
                        self._respond('application/json; charset=utf-8', content)
                    elif parsed.path == '/api/regcon/summary':
                        record = params.get('record', [''])[0]
                        source = publication_url(mode, term, page, record, authority)
                        result = SUMMARY_JOBS.start(
                            source,
                            SUMMARY_CACHE,
                            OLLAMA_URL,
                            OLLAMA_MODEL,
                        )
                        content = json.dumps(result, ensure_ascii=False).encode('utf-8')
                        self._respond(
                            'application/json; charset=utf-8',
                            content,
                            200 if result['status'] == 'done' else 202,
                        )
                    else:
                        record = params.get('record', [''])[0]
                        self._redirect(publication_url(mode, term, page, record, authority))
            except ValueError as exc:
                content = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                self._respond('application/json; charset=utf-8', content, 400)
            except RegconError as exc:
                content = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                self._respond('application/json; charset=utf-8', content, 502)
            except SummaryError as exc:
                content = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                self._respond('application/json; charset=utf-8', content, 502)
            except SummaryBusyError as exc:
                content = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                self._respond('application/json; charset=utf-8', content, 429)
            except CatalogError as exc:
                content = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                self._respond('application/json; charset=utf-8', content, 500)
        else:
            self._respond('text/plain; charset=utf-8', b'No encontrado', 404)

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != '/api/regcon/import':
            self._respond('text/plain; charset=utf-8', b'No encontrado', 404)
            return
        try:
            origin = urllib.parse.urlsplit(self.headers.get('Origin', ''))
        except ValueError:
            origin = urllib.parse.urlsplit('')
        if (
            not self.headers.get('Origin')
            or origin.scheme not in ('http', 'https')
            or origin.netloc != self.headers.get('Host')
        ):
            self._respond('application/json; charset=utf-8', b'{"error":"Origen no permitido."}', 403)
            return
        if self.headers.get_content_type() != 'application/json':
            self._respond('application/json; charset=utf-8', b'{"error":"Se requiere JSON."}', 415)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 8192:
                raise ValueError('El tamaño de la solicitud no es válido.')
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError('El contenido de la solicitud no es válido.')
            mode = request.get('mode')
            query = request.get('query')
            page = request.get('page')
            record = request.get('record')
            authority = request.get('authority', '')
            title = request.get('title')
            code = request.get('code')
            if (
                not isinstance(query, str)
                or type(page) is not int
                or not isinstance(record, str)
                or not isinstance(authority, str)
                or not isinstance(title, str)
                or len(title) > 500
                or not isinstance(code, str)
                or len(code) > 100
            ):
                raise ValueError('Faltan datos válidos del trámite para importarlo.')
            source = publication_url(mode, query, page, record, authority)
            result = import_official_publication(
                source,
                title,
                code,
                PAPERLESS_CONSUME,
            )
            status = 200 if result['status'] == 'already_queued' else 202
            self._respond(
                'application/json; charset=utf-8',
                json.dumps(result, ensure_ascii=False).encode('utf-8'),
                status,
            )
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._respond(
                'application/json; charset=utf-8',
                json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8'),
                400,
            )
        except RegconError as exc:
            self._respond(
                'application/json; charset=utf-8',
                json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8'),
                502,
            )
        except PaperlessImportError as exc:
            self._respond(
                'application/json; charset=utf-8',
                json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf-8'),
                502,
            )

def main():
    host = os.environ.get('OPENPACTUM_PANEL_HOST', '127.0.0.1')
    port = int(os.environ.get('OPENPACTUM_PANEL_PORT', '8080'))
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f'Panel OpenPactum disponible en http://{host}:{port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
