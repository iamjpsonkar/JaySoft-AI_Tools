"""jsat.ui._app — the Studio single-page app as static strings.

Zero dependencies, vanilla JS, one file: CSS, HTML shell, and the app script.
The server injects nothing into the shell; the app talks to ``/api`` endpoints
and to the real MCP tool registry behind them. E501 is per-file ignored
(pyproject.toml), like ``dashboard.py``.
"""
from __future__ import annotations

APP_CSS = r"""
*{box-sizing:border-box}
:root{--bg:#0d1117;--bg2:#010409;--panel:#161b22;--line:#30363d;--line2:#21262d;
--fg:#c9d1d9;--muted:#8b949e;--acc:#58a6ff;--ok:#3fb950;--warn:#d29922;--err:#f85149;
--purple:#bc8cff;--cyan:#39c5cf}
html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--fg);font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
a{color:var(--acc);cursor:pointer}
hdr{position:sticky;top:0;z-index:9;background:#161b22cc;backdrop-filter:blur(6px);
border-bottom:1px solid var(--line);display:flex;align-items:center;gap:14px;padding:8px 16px;flex-wrap:wrap}
.brand{font-weight:bold;color:#fff;letter-spacing:.03em;cursor:pointer}
.brand b{color:var(--acc)}
nav{display:flex;gap:4px;flex-wrap:wrap}
.navbtn{background:transparent;border:1px solid transparent;color:var(--muted);padding:4px 10px;
border-radius:5px;cursor:pointer;font:inherit}
.navbtn:hover{color:var(--fg)}
.navbtn.on{color:#fff;border-color:var(--acc);background:#1f2630}
.ask{flex:1;min-width:220px;display:flex;gap:6px}
.ask input{flex:1;background:var(--bg2);border:1px solid var(--line);color:var(--fg);
padding:6px 12px;border-radius:6px;font:inherit;outline:none}
.ask input:focus{border-color:var(--acc)}
button.pill{background:var(--panel);border:1px solid var(--line);color:var(--fg);
padding:5px 14px;border-radius:6px;cursor:pointer;font:inherit}
button.pill:hover{border-color:var(--acc)}
button.pill.primary{background:#1f6feb;border-color:#1f6feb;color:#fff}
main{max-width:1180px;margin:0 auto;padding:18px 16px 60px}
h2{margin:4px 0 12px;font-size:16px;color:#fff}
h3{font-size:13px;color:var(--acc);margin:18px 0 6px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:14px 16px;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.cta{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;
cursor:pointer;display:block;text-decoration:none;color:var(--fg)}
.cta:hover{border-color:var(--acc);transform:translateY(-1px)}
.cta .t{color:#fff;font-weight:bold;margin-bottom:2px}
.cta .d{color:var(--muted);font-size:11px;min-height:30px}
.kbd{color:var(--muted);font-size:10px;border:1px solid var(--line2);border-radius:3px;padding:0 4px}
.stat{display:flex;gap:22px;flex-wrap:wrap}
.stat .s{min-width:120px}
.stat .v{font-size:22px;font-weight:bold;color:#fff}
.stat .k{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.06em}
table{border-collapse:collapse;width:100%;font-size:12px}
th{color:var(--muted);text-align:left;font-size:10px;text-transform:uppercase;
border-bottom:1px solid var(--line);padding:6px 8px}
td{padding:5px 8px;border-bottom:1px solid var(--line2);color:var(--fg);vertical-align:top;word-break:break-word}
tr:hover td{background:#1d242d}
.status{display:inline-block;padding:1px 7px;border-radius:3px;font-size:11px}
.st-run{background:#1c3d6e;color:var(--acc)}
.st-ok{background:#1c4828;color:var(--ok)}
.st-err{background:#3d1d1d;color:var(--err)}
.out{background:var(--bg2);border:1px solid var(--line);border-radius:6px;
padding:10px 12px;font-size:12px;white-space:pre-wrap;word-break:break-word;overflow:auto;max-height:60vh}
.muted{color:var(--muted)}
.tag{display:inline-block;color:var(--purple);font-size:10px;border:1px solid var(--line);
border-radius:3px;padding:0 5px;margin-left:6px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.tab{background:var(--panel);border:1px solid var(--line);color:var(--muted);padding:4px 12px;
border-radius:5px;cursor:pointer;font:inherit}
.tab.on{color:#fff;border-color:var(--acc)}
input,select,textarea{background:var(--bg2);border:1px solid var(--line);color:var(--fg);
padding:6px 10px;border-radius:6px;font:inherit;outline:none}
input:focus,select:focus,textarea:focus{border-color:var(--acc)}
.row{display:flex;gap:10px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
.fld label{display:block;color:var(--muted);font-size:11px;margin:8px 0 2px}
.toollist{display:flex;flex-direction:column;gap:0}
.toolrow{padding:7px 10px;border-bottom:1px solid var(--line2);cursor:pointer;display:block}
.toolrow:hover{background:#1d242d}
.toolrow .n{color:var(--acc);font-weight:bold}
.msg{padding:8px 12px;border-radius:6px;margin-bottom:8px}
.msg.info{background:#10233f;color:#a5d6ff;border:1px solid #203b5f}
.msg.err{background:#2d1414;color:#ffb4ad;border:1px solid #4d2020}
#palette{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:20;display:none;align-items:flex-start;justify-content:center;padding-top:12vh}
#palette.open{display:flex}
#palette .box{background:var(--panel);border:1px solid var(--line);border-radius:10px;width:560px;max-width:92vw;
box-shadow:0 20px 60px rgba(0,0,0,.6)}
#palette input{width:100%;border:none;border-bottom:1px solid var(--line);border-radius:0;padding:14px 16px;font-size:14px}
#palette .list{max-height:50vh;overflow:auto}
#palette .pe{padding:9px 16px;cursor:pointer;color:var(--fg)}
#palette .pe.on{background:#1f2630;color:#fff}
#palette .pe .d{color:var(--muted);font-size:11px}
kbd{background:var(--panel);border:1px solid var(--line2);border-bottom-width:2px;border-radius:3px;padding:0 4px;font-size:10px}
@media(max-width:720px){.stat{flex-direction:column}}
"""

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JSAT Studio</title>
<link rel="icon" href="data:,">
<link rel="stylesheet" href="/app.css">
</head>
<body>
<header>
  <span class="brand" onclick="go('home')">JSAT<b>Studio</b></span>
  <nav id="nav"></nav>
  <div class="ask">
    <input id="askbox" placeholder="Ask JSAT anything — “what breaks if I change refund()”, “security review”, “COUNT tokens of …”  ( / )">
    <button class="pill primary" onclick="askNow()">Ask</button>
  </div>
  <button class="pill" onclick="openPalette()" title="Command palette (Ctrl+P)">⌘&nbsp;Palette</button>
</header>
<main id="main"></main>
<div id="palette">
  <div class="box">
    <input id="palq" placeholder="Jump to a screen or prompt…">
    <div class="list" id="pallist"></div>
  </div>
</div>
<script src="/app.js"></script>
</body>
</html>
"""

APP_JS = r"""
/* ── JSAT Studio app ─────────────────────────────────────────────────────── */
var API = '/api';
var SCREENS = [
  {id:'home',   label:'Overview',      d:'Index stats, environment, quick actions'},
  {id:'ask',    label:'Ask',           d:'Natural-language prompt with intent routing'},
  {id:'graph',  label:'Graph',         d:'Functions, classes, services, endpoints, tables'},
  {id:'blast',  label:'Blast Radius',  d:'Downstream impact of a change'},
  {id:'security',label:'Security',     d:'OWASP scan + secrets on a path'},
  {id:'gaps',   label:'Test Gaps',     d:'Untested functions and endpoints'},
  {id:'apidiff',label:'API Diff',      d:'Breaking contract changes between refs'},
  {id:'consumers',label:'Consumers',   d:'Who consumes a function, endpoint or topic'},
  {id:'dataflow',label:'Data Flow',    d:'Reads/writes/produces/consumes per service'},
  {id:'incident',label:'Incident',     d:'Root-cause hypotheses for an outage'},
  {id:'review', label:'Review',        d:'Multi-model code review of a diff'},
  {id:'knowledge',label:'Knowledge',   d:'ADR / runbook search'},
  {id:'improve',label:'Improve',       d:'Friction JSAT recorded in itself'},
  {id:'plab',  label:'Prompt Lab',     d:'Optimize, count, compress, budget tokens'},
  {id:'tools', label:'Tools',          d:'Every MCP tool, with forms'},
  {id:'sessions',label:'Sessions',     d:'Resumable skill sessions'},
  {id:'plans', label:'Plans',          d:'Stored plan proposals'},
];

var state = {view:'home', tools:[], index:null, status:null,
             graphLabel:'function', ask:[]};

function $(id){return document.getElementById(id);}
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}

function http(path, opts){
  opts = opts||{};
  var ctl;
  var p = new Promise(function(resolve,reject){
    var x = new XMLHttpRequest();
    x.open((opts.method||'GET'), path, true);
    if (opts.ct !== false) x.setRequestHeader('Content-Type','application/json');
    x.onload = function(){
      var body = x.responseText;
      var data = body;
      try { data = JSON.parse(body); } catch(e){}
      if (x.status >= 200 && x.status < 300) resolve(data);
      else reject({status:x.status, data:data});
    };
    x.onerror = function(){reject({status:0, data:'network error'});};
    if (opts.body !== undefined) x.send(JSON.stringify(opts.body));
    else x.send();
  });
  p.cancel = function(){ if(ctl) ctl.abort(); };
  return p;
}
function qs(map){ var k=Object.keys(map||{}), out=[];
  for(var i=0;i<k.length;i++) if(map[k[i]]!=null && map[k[i]]!=='')
    out.push(encodeURIComponent(k[i])+'='+encodeURIComponent(map[k[i]]));
  return out.length?'?'+out.join('&'):''; }

/* ── markdown-lite + pretty result rendering ────────────────────────────── */
function pretty(text){
  if (text == null) return '<span class="muted">—</span>';
  var s = String(text);
  if (s.length > 2 && (s[0]==='{' || s[0]==='[')) {
    try { s = JSON.stringify(JSON.parse(s), null, 2); } catch(e){}
  }
  return md(s);
}
function md(s){
  s = esc(s);
  s = s.replace(/```(\w*)\n([\s\S]*?)```/g, function(m, lang, code){ return '<pre class="out">'+code+'</pre>'; })
       .replace(/`([^`\n]+)`/g, '<code>$1</code>')
       .replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>')
       .replace(/^###[ \t]+(.+)$/gm, '</p><h3>$1</h3><p style="margin:0">')
       .replace(/^##[ \t]+(.+)$/gm, '<b>$1</b>')
       .replace(/^- \[ \] (.*)$/gm, '☐ $1').replace(/^- \[x\] (.*)$/gm, '☑ $1')
       .replace(/^([-*]) (.*)$/gm, '• $2')
       .replace(/\n(?=[A-Za-z0-9\[\/])/g, '\n');
  return '<pre class="out">'+s+'</pre>';
}

/* ── nav + palette ──────────────────────────────────────────────────────── */
function renderNav(){
  var h = '';
  for (var i=0;i<SCREENS.length;i++) {
    h += '<button class="navbtn'+(state.view===SCREENS[i].id?' on':'')+'" onclick="go(\''+
         SCREENS[i].id+'\')">'+SCREENS[i].label+'</button>';
  }
  $('nav').innerHTML = h;
}
function go(view){ state.view = view; renderNav(); renderView(); window.scrollTo(0,0); }
function onHash(){ var h=location.hash.replace(/^#\//,''); if(h) go(h); }

function openPalette(){ $('palette').classList.add('open'); $('palq').value=''; palFilter(''); $('palq').focus(); }
function closePalette(){ $('palette').classList.remove('open'); }
function palFilter(q){
  q = q.toLowerCase();
  var items = [];
  for (var i=0;i<SCREENS.length;i++)
    if (SCREENS[i].label.toLowerCase().indexOf(q)>=0 ||
        SCREENS[i].d.toLowerCase().indexOf(q)>=0)
      items.push({k:SCREENS[i].label, s:'screen', d:SCREENS[i].d, go:SCREENS[i].id});
  var prompts = SUGGESTIONS;
  for (var j=0;j<prompts.length;j++)
    if (prompts[j].toLowerCase().indexOf(q)>=0)
      items.push({k:prompts[j].slice(0,46), s:'prompt', d:'run in Ask', go:'ask'});
  var html='', sel=0;
  for (var n=0;n<items.length;n++){
    html += '<div class="pe'+(n===0?' on':'')+'" data-i="'+n+'" onclick="palPick('+n+')">'
          + esc(items[n].k) + ' <span class="tag">'+items[n].s+'</span>'
          + '<div class="d">'+esc(items[n].d)+'</div></div>';
  }
  $('pallist').innerHTML = html || '<div class="pe muted">no matches</div>';
  $('pallist').dataset.items = JSON.stringify(items);
  if (q==='') $('pallist').dataset.items = JSON.stringify(items);
}
function palPick(i){
  var items = JSON.parse($('pallist').dataset.items||'[]');
  var it = items[i]; if(!it) return;
  closePalette();
  if (it.s==='screen') go(it.go);
  else { go('ask'); askNow(it.k); }
}
$('palq').addEventListener('input', function(){ palFilter(this.value); });
$('palq').addEventListener('keydown', function(ev){
  if (ev.key==='Enter' || ev.key==='Tab') palPick(0);
  if (ev.key==='Escape') closePalette();
});
document.body.addEventListener('keydown', function(ev){
  if ((ev.ctrlKey||ev.metaKey) && ev.key==='p') { ev.preventDefault(); ev.stopPropagation(); openPalette(); return; }
  if (ev.key==='Escape') { closePalette(); return; }
  if (ev.key==='/' && document.activeElement!==$('askbox')) { ev.preventDefault(); $('askbox').focus(); }
});
function debounce(fn, ms){ var t; return function(){ clearTimeout(t); t=setTimeout(fn, ms); }; }

/* ── ask / prompt ───────────────────────────────────────────────────────── */
var ASKED = [];
function askNow(explicit){
  var box = $('askbox');
  var text = (explicit||box.value||'').trim();
  if (!text) return;
  if (!explicit) box.value='';
  var key = state.ask.length;
  state.ask.push({q:text, r:'running…', intent:null});
  renderAskList();
  http(API+'/prompt', {method:'POST', body:{text:text}})
    .then(function(res){
      state.ask[key].r = 'r:' + (res.result||res.error||'done');
      state.ask[key].intent = res.intent;
      state.ask[key].conf = res.confidence;
      if (!explicit) state.ask[key].r = pretty(res.result||res.error||'done');
      renderAskList();
    })
    .catch(function(err){
      state.ask[key].r = 'error: ' + (err.data&&err.data.error||err.status||'request failed');
      renderAskList();
    });
  ASKED.push(text); if (ASKED.length>50) ASKED.shift();
}

/* ── views ──────────────────────────────────────────────────────────────── */
function renderView(){
  var m = $('main');
  var fns = {home:vHome, ask:vAsk, graph:vGraph, blast:vTool, security:vTool,
             gaps:vTool, apidiff:vTool, consumers:vTool, dataflow:vTool,
             incident:vTool, review:vTool, knowledge:vTool, improve:vTool,
             plab:vTool, tools:vTools, sessions:vList, plans:vList};
  (fns[state.view]||vHome)();
}
function vHome(){
  var main = $('main');
  main.innerHTML = '<h2>Overview</h2><div id="ov" class="card stat"><span class="muted">loading…</span></div>'
    + '<h3>Launch pad</h3><div id="ctas"></div>';
  Promise.all([http(API+'/status'), http(API+'/index')]).then(function(d){
    var s=d[0], i=d[1];
    $('ov').innerHTML = [
      ['JSAT', s.jsat_version].join(' '),
      stat('AI provider', s.provider),
      stat('Graph backend', s.graph_backend),
      stat('Nodes', i.nodes),
      stat('Edges', i.edges),
      stat('Index fresh', i.is_fresh ? 'yes' : 'no'),
      stat('MCP tools', i.tools),
    ].join('');
  }).catch(function(e){ $('ov').innerHTML = '<span class="muted">' + esc(e.data||e) + '</span>'; });
  var c='';
  for (var i=0;i<SCREENS.length;i++){
    var s2=SCREENS[i];
    c += '<a class="cta" onclick="go(\''+s2.id+'\')"><div class="t">'+s2.label+'</div>'
       + '<div class="d">'+s2.d+'</div></a>';
  }
  $('ctas').innerHTML = '<div class="grid">'+c+'</div>';
  if (state.index && state.index.is_fresh===false)
    showMsg('index fresh: ' + (state.index.is_fresh ? 'yes' : 'NO — run <code>jsat index .</code>'), 'info');
}
function stat(k,v){ return '<div class="s"><div class="v">'+esc(v)+'</div><div class="k">'+esc(k)+'</div></div>'; }

function vAsk(){
  var main = $('main');
  main.innerHTML = '<h2>Ask JSAT</h2>'
    + '<div class="msg info">Prompts are routed to a real JSAT tool by offline intent matching — '
    + 'nothing leaves the machine. If no rule matches, the question goes to <b>query</b>.</div>'
    + '<div id="asklist"></div>';
  state.ask.length = 0;
  renderAskList();
}
function renderAskList(){
  var el = $('asklist'); if (!el) return;
  var h='';
  for (var i=0;i<state.ask.length;i++){
    var a = state.ask[i];
    h += '<div class="card"><div class="row"><b>Q:</b> '+esc(a.q)
       + (a.intent?'<span class="tag">→ '+esc(a.intent)+'</span>':'')+'</div>'
       + '<div class="row"><b>A:</b> '+ (a.r.indexOf('r:')===0 ? pretty(a.r.slice(2)) : a.r) + '</div></div>';
  }
  el.innerHTML = h || '<div class="muted">No prompts yet — try one below or type in the top bar.</div>';
}

/* ── graph explorer ─────────────────────────────────────────────────────── */
var LABELS = ['function','class','endpoint','service','table','topic','file'];
function vGraph(){
  var main = $('main');
  main.innerHTML = '<h2>Graph explorer</h2><div class="tabs" id="gtabs"></div>'
    + '<div class="row"><input id="gq" placeholder="filter rows…" style="width:260px"></div>'
    + '<div class="card" style="overflow:auto"><table><thead id="ghead"></thead><tbody id="gbody"></tbody></table></div>';
  var t=''; for (var i=0;i<LABELS.length;i++) t+='<button class="tab'+(LABELS[i]===state.graphLabel?' on':'')+'" onclick="gLabel(\''+LABELS[i]+'\')">'+LABELS[i]+'</button>';
  $('gtabs').innerHTML=t;
  loadGraph();
  $('gq').addEventListener('input', debounce(loadGraph, 250));
}
function gLabel(l){ state.graphLabel=l; go('graph'); }
function loadGraph(){
  var q = ($('gq')&&$('gq').value||'').trim().toLowerCase();
  http(API+'/nodes'+qs({label:state.graphLabel, limit:400})).then(function(d){
    var rows = (d.rows||[]).filter(function(r){
      if (!q) return true;
      return JSON.stringify(r).toLowerCase().indexOf(q)>=0;
    });
    var keys = ['name','id','file','language','line'];
    var hh = keys.map(function(k){return '<th>'+k+'</th>';}).join('')
      + '<th>detail</th>';
    var hb='';
    for (var i=0;i<rows.length;i++){
      var r=rows[i];
      hb += '<tr><td>'+esc(r.name||r.id||'')+'</td><td>'+esc(r.id||'')+'</td>'
        + '<td>'+esc(r.file||'')+'</td><td>'+esc(r.language||'')+'</td>'
        + '<td>'+(r.line!=null?r.line:'')+'</td>'
        + '<td><button class="pill" onclick="gDetail(\''+esc(r.name||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'")+'\')">open</button></td></tr>';
    }
    $('ghead').innerHTML='<tr>'+hh+'</tr>';
    $('gbody').innerHTML = hb || '<tr><td class="muted" colspan="6">no '+state.graphLabel+' nodes'+(q?' matching “'+esc(q)+'”':'')+'</td></tr>';
  }).catch(function(e){ $('gbody').innerHTML='<tr><td class="muted">'+esc(e.data||e)+'</td></tr>'; });
}
function gDetail(name){
  if (!name) return;
  var tool = state.graphLabel==='function' ? 'get_function'
           : state.graphLabel==='class' ? 'get_class' : 'query';
  var args = (state.graphLabel==='function'||state.graphLabel==='class') ? {name:name} : {question:name};
  openTool(tool, args);
}

/* ── generic tool pages ─────────────────────────────────────────────────── */
var TOOL_BY_VIEW = {
  blast:{t:'blast_radius', inp:[{k:'target', label:'Target (symbol or file path)', ph:'e.g. refund or src/services/payments.py'}],
         d:'Finds every downstream caller of a file or symbol and ranks impact: <b>breaking / degraded / warning / safe</b>. Run this before editing shared code.'},
  security:{t:'security_review', inp:[{k:'path', label:'Path to scan', ph:'.'}],
         d:'OWASP + secret scan with severity grouping. Values are never stored; secret findings are reported, not persisted.'},
  gaps:{t:'get_test_gaps', inp:[{k:'path', label:'Path', ph:''}],
         d:'Functions and endpoints with no test coverage, pulled from the index.'},
  apidiff:{t:'get_api_diff', inp:[{k:'base',label:'Base ref',ph:'main'},{k:'head',label:'Head ref',ph:'HEAD'}],
         d:'Diff OpenAPI/AsyncAPI specs between two git refs.'},
  consumers:{t:'get_consumers', inp:[{k:'target',label:'Target',ph:'symbol / endpoint / topic'}],
         d:'Every node that consumes or calls a target.'},
  dataflow:{t:'get_data_flow', inp:[{k:'service',label:'Service',ph:''}],
         d:'READS_FROM / WRITES_TO / PRODUCES / CONSUMES edges.'},
  incident:{t:'investigate_incident', inp:[{k:'description',label:'Symptom / error',ph:''}],
         d:'Scores recent commits as root-cause hypotheses by recency + blast radius.'},
  review:{t:'submit_for_review', inp:[{k:'base',label:'Base',ph:'main'},{k:'head',label:'Head',ph:'HEAD'}],
         d:'Multi-model parallel code review of a diff.'},
  knowledge:{t:'knowledge_query', inp:[{k:'question',label:'Question',ph:''}],
         d:'Search the project knowledge base (ADRs, runbooks, gotchas).'},
  improve:{t:'improve_status', inp:[],
         d:'Friction JSAT recorded in itself — crashes, gaps, UX friction. Read-only, no AI.'},
};
function vTool(){
  var cfg = TOOL_BY_VIEW[state.view] || {t:'query', inp:[]};
  var main = $('main');
  var inp = '';
  for (var i=0;i<cfg.inp.length;i++){
    inp += '<div class="fld" style="flex:1"><label>'+esc(cfg.inp[i].label)+'</label>'
         + '<input id="tin-'+i+'" placeholder="'+esc(cfg.inp[i].ph||'')+'" style="width:100%"></div>';
  }
  main.innerHTML = '<h2>'+cap(state.view)+' <span class="tag">'+esc(cfg.t)+'</span></h2>'
    + '<div class="msg info">'+cfg.d+'</div>'
    + '<div class="card"><div class="row">'+inp+'<button class="pill primary" style="align-self:flex-end" onclick="runThisView()">Run</button></div></div>'
    + '<div id="toolout"></div>';
  setTimeout(function(){ var f=$('tin-0'); if(f) f.focus(); }, 30);
}
function runThisView(){
  var cfg = TOOL_BY_VIEW[state.view] || {t:'query', inp:[]};
  var args = {};
  for (var i=0;i<cfg.inp.length;i++){
    var el = $('tin-'+i);
    if (el && el.value.trim()) args[cfg.inp[i].k] = el.value.trim();
  }
  openTool(cfg.t, args);
}
function cap(s){ return s.charAt(0).toUpperCase()+s.slice(1).replace(/([A-Z])/g,' $1'); }

/* ── shared tool output drawer ──────────────────────────────────────────── */
function openTool(tool, args){
  go('tools');
  state.toolsFocus = tool; state.toolsArgs = args||{};
  setTimeout(function(){ runToolFromState(); }, 40);
}

/* ── tools catalog + form ───────────────────────────────────────────────── */
function vTools(){
  var main = $('main');
  main.innerHTML = '<h2>All tools <span class="tag">'+state.tools.length+'</span></h2>'
    + '<div class="row"><input id="tq" placeholder="filter tools…" style="width:280px">'
    + ' <button class="pill" onclick="loadCatalog(true)">refresh catalog</button></div>'
    + '<div class="card"><div id="tside" style="float:left;width:320px;max-width:40vw"><div class="toollist" id="tlist"></div></div>'
    + '<div id="tform" style="margin-left:336px"></div><div style="clear:both"></div></div>'
    + '<div id="toolout"></div>';
  loadCatalog(false);
  $('tq').addEventListener('input', debounce(function(){ renderToolList(); }, 200));
}
function loadCatalog(hard){
  if (state.tools.length && !hard) { renderToolList(); return; }
  http(API+'/tools').then(function(d){
    state.tools = d.tools||[];
    renderToolList();
    if (state.toolsFocus) renderToolForm(state.toolsFocus);
  }).catch(function(e){ $('tlist').innerHTML='<div class="muted">'+esc(e.data||e)+'</div>'; });
}
function renderToolList(){
  var el=$('tlist'); if(!el) return;
  var q=($('tq')&&$('tq').value||'').toLowerCase();
  var items = state.tools.filter(function(t){ return !q || t.name.indexOf(q)>=0 || t.description.toLowerCase().indexOf(q)>=0; });
  var h='';
  for (var i=0;i<items.length;i++)
    h += '<span class="toolrow" onclick="renderToolForm(\''+items[i].name+'\')"><span class="n">'+esc(items[i].name)+'</span>'
       + '<div class="muted" style="font-size:11px">'+esc((items[i].description||'').slice(0,90))+'</div></span>';
  el.innerHTML = h;
  if (items.length===0) el.innerHTML='<div class="muted">no tools match</div>';
}
function renderToolForm(name){
  state.toolsFocus = name; state.toolsArgs = state.toolsArgs||{};
  var t = null;
  for (var i=0;i<state.tools.length;i++) if (state.tools[i].name===name) { t=state.tools[i]; break; }
  var tf = $('tform');
  if (!t) { tf.innerHTML='<div class="muted">tool not found</div>'; return; }
  var h='<h3 style="margin-top:0">'+esc(t.name)+' <span class="tag">'+t.properties.length+' args</span></h3>'
     + '<div class="muted" style="font-size:11px;margin-bottom:8px">'+esc(t.description)+'</div>';
  if (t.properties.length===0){
    h += '<button class="pill primary" onclick="runToolForm(\''+name+'\',{})">Run</button>';
  } else {
    for (var j=0;j<t.properties.length;j++){
      var p = t.properties[j], req = t.required.indexOf(p)>=0;
      h += '<div class="fld"><label>'+esc(p)+(req?' <b style="color:var(--err)">*</b>':'')+'</label>'
         + '<input id="tf-'+j+'" style="width:100%" placeholder="'+esc(p)+'"></div>';
    }
    h += '<button class="pill primary" onclick="runToolForm(\''+name+'\')">Run</button>';
  }
  tf.innerHTML = h;
  for (var k=0;k<t.properties.length;k++){
    var el = $('tf-'+k);
    if (el && state.toolsArgs && state.toolsArgs[t.properties[k]]!=null) el.value = state.toolsArgs[t.properties[k]];
  }
}
function runToolForm(name){
  var t = null;
  for (var i=0;i<state.tools.length;i++) if (state.tools[i].name===name) { t=state.tools[i]; break; }
  var args = {};
  if (t) for (var j=0;j<t.properties.length;j++){
    var el = $('tf-'+j);
    if (el && el.value.trim()) args[t.properties[j]] = el.value.trim();
  }
  state.toolsArgs = args;
  runToolFromState();
}
function runToolFromState(){
  var name = state.toolsFocus, args = state.toolsArgs||{};
  var out = $('toolout');
  if (!out) return;
  out.innerHTML = '<div class="msg info">running <b>'+esc(name)+'</b>…</div>';
  http(API+'/tools/'+encodeURIComponent(name), {method:'POST', body:{args:args}})
    .then(function(r){
      if (r.ok) out.innerHTML = '<div class="row"><span class="status st-ok">done</span> '
          + '<span class="muted">'+r.elapsed_ms+' ms</span></div>' + pretty(r.result);
      else out.innerHTML = '<div class="msg err">' + esc(r.error||'tool failed') + '</div>';
    })
    .catch(function(err){
      out.innerHTML = '<div class="msg err">HTTP ' + (err.status||'?') + ' ' + esc(err.data&&err.data.error||err.data||'') + '</div>';
    });
}

/* ── sessions / plans ───────────────────────────────────────────────────── */
function vList(){
  var kind = state.view; /* sessions | plans */
  var main = $('main');
  main.innerHTML = '<h2>'+cap(kind)+'</h2><div class="card"><table><thead><tr>'
    + '<th>id</th><th>skill</th><th>task</th><th>status</th><th>path</th></tr></thead>'
    + '<tbody id="lb"><tr><td class="muted" colspan="5">loading…</td></tr></tbody></table></div>';
  http(API+'/'+kind).then(function(d){
    var rows = d[kind]||d.sessions||[];
    var h='';
    for (var i=0;i<rows.length;i++){
      var r = rows[i]; if (r.error) continue;
      h += '<tr><td>'+esc(r.id)+'</td><td>'+esc(r.skill)+'</td><td>'+esc(r.task)
         + '</td><td><span class="status st-'+(r.status==='completed'?'ok':r.status==='error'?'err':'run')+'">'
         + esc(r.status)+'</span></td><td class="muted">'+esc(r.path)+'</td></tr>';
    }
    $('lb').innerHTML = h || '<tr><td class="muted" colspan="5">none yet</td></tr>';
  }).catch(function(e){ $('lb').innerHTML='<tr><td class="muted">'+esc(e.data||e)+'</td></tr>'; });
}

var SUGGESTIONS = [
  'What does this project do?',
  'Where is the refund logic?',
  'What breaks if I change refund()?',
  'Security review of .',
  'Which functions and endpoints are untested?',
  'Who consumes the orders topic?',
  'Trace make_payment to notify_shipper',
  'API diff between main and HEAD',
  'Investigate: orders failing during peak',
  'What changed in the last 72h?',
  'Find hardcoded secrets',
  'List dependency CVEs',
  'Estimate lock duration for ALTER TABLE orders ADD COLUMN x',
];

/* ── boot ──────────────────────────────────────────────────────────────── */
renderNav();
window.addEventListener('hashchange', onHash);
onHash();
if (!location.hash) go('home');
"""

__all__ = ["APP_CSS", "APP_JS", "PAGE_HTML"]