"""jsat.mcp._dashboard_app — the static client app for the JSAT dashboard.

Standalone vanilla-JS single-page app (no framework, no network). Rendered by
jsat.mcp.dashboard into live-session, replay, and compare pages. The JS is kept
as one static string in its own module so it can be format/lint-agnostic and
syntax-checked independently (``node --check``) without polluting dashboard.py.
"""
from __future__ import annotations

APP_JS = """
'use strict';
/* Window.DASH is injected by the server before this script runs. */
window.DASH = window.DASH || { mode: 'live' };
var DASH = window.DASH;
var BASE = '/jsat/dashboard';

/* ── app state ─────────────────────────────────────────────────────────── */
var state = {
  mode: DASH.mode,            // 'live' | 'replay' | 'compare'
  slug: DASH.slug || '',
  file: DASH.file || null,    // archive file for replay
  cmpA: DASH.a || null,       // archive files for compare
  cmpB: DASH.b || null,
  session: null,
  calls: new Map(),           // call_id -> call
  events: [],
  maxSeq: 0,
  status: 'running',          // 'running' | 'done'
  view: 'waterfall',          // 'waterfall' | 'tree' | 'stats'
  q: '',
  statusFilter: 'all',
  expanded: null,             // Set of call_ids (tree)
  drawerId: null,
  done: false,
  now: Date.now(),
  scrub: null,                // absolute wall-ms scrub position (replay)
  play: false,
  playSpeed: 12,
  globalStats: null,
  compare: null,              // {a: docs, b: docs, keys: [...]} for compare
  sse: null
};

function $(id) { return document.getElementById(id); }
function esc(s) {
  s = (s == null) ? '' : String(s);
  return s.replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}
function fmtDur(ms) {
  if (ms == null || ms < 0) return '';
  var s = ms / 1000;
  if (s < 60) { return (s < 10 ? s.toFixed(1) : Math.round(s)) + 's'; }
  var m = Math.floor(s / 60); s = Math.round(s - m * 60);
  return m + 'm ' + s + 's';
}
function fmtClock(ms) {
  if (ms == null) return '';
  var d = new Date(ms), p = function (n) { return (n < 10 ? '0' : '') + n; };
  return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
}
function pretty(text) {
  if (text == null) return '';
  try { return JSON.stringify(JSON.parse(text), null, 2); }
  catch (e) { return String(text); }
}
function pctl(arr, p) {
  if (!arr.length) return null;
  var a = arr.slice().sort(function (x, y) { return x - y; });
  return a[Math.floor((a.length - 1) * p)];
}

/* ── data plumbing ─────────────────────────────────────────────────────── */
function setSessionMeta(meta) {
  state.session = meta || null;
  if (meta) {
    state.status = meta.status || 'running';
    if (meta.status === 'done') { state.done = true; }
  }
}
function applyDocument(doc) {
  if (!doc) return;
  setSessionMeta(doc.session || null);
  state.calls.clear();
  var calls = doc.calls || {};
  Object.keys(calls).forEach(function (id) { state.calls.set(id, calls[id]); });
  state.events = doc.events || [];
  state.maxSeq = 0;
  state.events.forEach(function (e) { if (e.seq && e.seq > state.maxSeq) state.maxSeq = e.seq; });
  if (state.expanded === null) {
    state.expanded = new Set();
    state.calls.forEach(function (c) { if ((c.depth || 0) < 2) state.expanded.add(c.call_id); });
  }
  document.title = (doc.session && doc.session.session_name) ? ('JSAT — ' + doc.session.session_name) : 'JSAT Dashboard';
  render();
}
function applyEvent(ev) {
  if (!ev) return;
  if (ev.seq && ev.seq <= state.maxSeq) return;
  if (ev.seq) state.maxSeq = ev.seq;
  state.events.push(ev);
  var c;
  if (ev.type === 'call_start') {
    c = {
      call_id: ev.call_id, name: ev.name, parent_id: ev.parent_id,
      depth: ev.depth || 0, status: 'running',
      start_wall_ms: ev.wall_ms, end_wall_ms: null,
      budget_s: ev.budget_s || null, mode: ev.mode || 'default',
      args: ev.args || null, payload: null, error: null, elapsed_s: null
    };
    state.calls.set(ev.call_id, c);
  } else if (ev.type === 'call_done') {
    c = state.calls.get(ev.call_id);
    if (c) { c.status = ev.status || 'done'; c.elapsed_s = ev.elapsed_s; c.end_wall_ms = ev.wall_ms; }
  } else if (ev.type === 'session_done') {
    state.done = true; state.status = 'done';
    stopSSE(); refreshFinal();
    return;
  } else {
    c = state.calls.get(ev.call_id);
    if (ev.payload && c) c.payload = ev.payload;
    if (ev.type === 'error' && c && !c.error) c.error = ev.msg;
  }
  render();
}
function fetchJSON(url) {
  return fetch(url).then(function (r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  });
}
function fetchData() { return fetchJSON(BASE + '/' + encodeURIComponent(state.slug) + '/data'); }
function refreshFinal() { fetchData().then(applyDocument).catch(function () { /* best effort */ }); }
function startSSE() {
  if (!state.live) return;
  var src = new EventSource(BASE + '/' + encodeURIComponent(state.slug) + '/events');
  src.onmessage = function (e) {
    var ev; try { ev = JSON.parse(e.data); } catch (err) { return; }
    applyEvent(ev);
  };
  src.onerror = function () {
    var pill = $('status-pill');
    if (pill && !state.done) { pill.className = 'pill warn'; pill.textContent = '⚠ reconnect'; }
  };
  state.sse = src;
}
function stopSSE() { if (state.sse) { state.sse.close(); state.sse = null; } }

/* ── derived data ───────────────────────────────────────────────────────── */
function childrenOf(id) {
  var out = [], ids = [];
  state.calls.forEach(function (c, cid) { if (c.parent_id === id) ids.push(cid); });
  ids.sort(function (a, b) {
    return (state.calls.get(a).start_wall_ms || 0) - (state.calls.get(b).start_wall_ms || 0);
  });
  ids.forEach(function (cid) { out.push(cid); });
  return out;
}
function roots() {
  var out = [];
  state.calls.forEach(function (c, id) {
    if (!c.parent_id || !state.calls.has(c.parent_id) || c.parent_id === c.call_id) out.push(id);
  });
  out.sort(function (a, b) {
    return (state.calls.get(a).start_wall_ms || 0) - (state.calls.get(b).start_wall_ms || 0);
  });
  return out;
}
function orderedCalls() {
  var out = [];
  function walk(id) {
    var c = state.calls.get(id);
    if (c) { out.push(c); childrenOf(id).forEach(walk); }
  }
  roots().forEach(walk);
  return out;
}
function wallWindow() {
  var a = state.now, b = 0;
  state.calls.forEach(function (c) {
    var s = c.start_wall_ms || 0, e = c.end_wall_ms;
    if (!e && c.status === 'running') e = state.scrub || state.now;
    else if (!e) e = s;
    if (s && s < a) a = s;
    if (e && e > b) b = e;
  });
  if (state.session && state.session.started_wall_ms && state.session.started_wall_ms < a) a = state.session.started_wall_ms;
  if (!b) b = state.now;
  if (b - a < 1500) b = a + 1500;
  if (state.scrub != null && state.scrub > b) b = state.scrub;
  return { a: a, b: b };
}
function callElapsed(c) {
  var e = c.elapsed_s;
  if (e == null && c.end_wall_ms && c.start_wall_ms) e = (c.end_wall_ms - c.start_wall_ms) / 1000;
  if (e == null && c.status === 'running' && c.start_wall_ms) e = ((state.scrub || state.now) - c.start_wall_ms) / 1000;
  return e;
}
function overBudget(c) {
  if (!c.budget_s) return false;
  var e = callElapsed(c);
  return e != null && e * 1000 > c.budget_s * 1000 + 50;
}
function matchesFilter(c) {
  if (state.statusFilter !== 'all') {
    var want = state.statusFilter;
    if (want === 'error' && c.status !== 'error') return false;
    if (want === 'running' && c.status !== 'running') return false;
    if (want === 'done' && (c.status !== 'done' && c.status !== 'error')) return false;
  }
  if (!state.q) return true;
  var hay = (c.name || '') + ' ' + (c.args || '') + ' ' + (c.payload || '') + ' ' + (c.error || '');
  var evs = state.events.filter(function (e) { return e.call_id === c.call_id; })
    .map(function (e) { return e.msg; }).join(' ');
  hay += ' ' + evs;
  return hay.toLowerCase().indexOf(state.q.toLowerCase()) !== -1;
}
function modeLabel(m) { return m === 'beast' ? ' 🐄' : (m === 'plan' ? ' 📋' : ''); }

function toolStats(callsIter) {
  var map = new Map();
  function up(c) {
    if (!map.has(c.name)) map.set(c.name, { calls: 0, elapsed: [], errors: 0, over: 0 });
    var t = map.get(c.name);
    t.calls++;
    var e = callElapsed(c);
    if (e != null) t.elapsed.push(e * 1000);
    if (c.status === 'error') t.errors++;
    if (overBudget(c)) t.over++;
  }
  callsIter.forEach(up);
  var rows = [];
  map.forEach(function (t, name) {
    rows.push({
      tool: name, calls: t.calls,
      total: t.elapsed.length ? t.elapsed.reduce(function (a, b) { return a + b; }, 0) : 0,
      avg: t.elapsed.length ? t.elapsed.reduce(function (a, b) { return a + b; }, 0) / t.elapsed.length : null,
      p95: pctl(t.elapsed, 0.95), max: t.elapsed.length ? Math.max.apply(null, t.elapsed) : 0,
      errors: t.errors, over: t.over
    });
  });
  rows.sort(function (a, b) { return (b.total + b.calls) - (a.total + a.calls); });
  return rows;
}

/* ── header / toolbar ───────────────────────────────────────────────────── */
function bindToolbar() {
  var views = ['waterfall', 'tree', 'stats'];
  views.forEach(function (v) {
    var b = $('tab-' + v);
    if (b) b.addEventListener('click', function () {
      state.view = v; $('views').children.forEach(function (el) { el.classList.remove('on'); });
      b.classList.add('on'); render();
    });
  });
  var f = $('filter-q');
  if (f) f.addEventListener('input', function () { state.q = f.value.trim(); render(); });
  var st = $('filter-status');
  if (st) st.addEventListener('change', function () { state.statusFilter = st.value; render(); });
  var ex = $('btn-expand'); if (ex) ex.addEventListener('click', function () { expandAll(true); });
  var co = $('btn-collapse'); if (co) co.addEventListener('click', function () { expandAll(false); });
  var hl = $('btn-help'); if (hl) hl.addEventListener('click', function () { toggleHelp(); });
  var dv = $('drawer-close'); if (dv) dv.addEventListener('click', function () { closeDrawer(); });
  document.body.addEventListener('keydown', function (e) {
    if (e.target && e.target.tagName === 'INPUT') {
      if (e.key === 'Escape') { e.target.blur(); return; }
      return;
    }
    if (e.key === '1') switchView('waterfall');
    else if (e.key === '2') switchView('tree');
    else if (e.key === '3') switchView('stats');
    else if (e.key === '/') { var fi = $('filter-q'); if (fi) { fi.focus(); e.preventDefault(); } }
    else if (e.key === 'e') expandAll(true);
    else if (e.key === 'c') expandAll(false);
    else if (e.key === 'Escape') closeDrawer();
    else if (e.key === '?') toggleHelp();
  });
  function switchView(v) {
    state.view = v;
    ['waterfall', 'tree', 'stats'].forEach(function (x) {
      var el = $('tab-' + x); if (el) el.classList.toggle('on', x === v);
    });
    render();
  }
}
function expandAll(on) {
  if (!state.expanded) state.expanded = new Set();
  if (on) state.calls.forEach(function (c, id) { state.expanded.add(id); });
  else state.calls.forEach(function (c, id) { state.expanded.delete(id); });
  render();
}

/* ── waterfall view ─────────────────────────────────────────────────────── */
var STEPS = [100, 250, 500, 1000, 2500, 5000, 10000, 15000, 30000, 60000, 120000, 300000, 600000, 900000];
var LABEL_W = 170;

function pickStep(span, areaW) {
  for (var i = 0; i < STEPS.length; i++) {
    if (span / STEPS[i] <= Math.max(areaW / 90, 3)) return STEPS[i];
  }
  return STEPS[STEPS.length - 1];
}
function xt(pos, win, span, areaW) { return LABEL_W + ((pos - win.a) / span) * areaW; }

function renderRuler(win, span, areaW) {
  var el = $('wf-ruler');
  var step = pickStep(span, areaW);
  var html = '<div class="ruler-kicker"></div>';
  for (var t = Math.ceil(win.a / step) * step; t <= win.b + 1; t += step) {
    if (t < win.a) continue;
    html += '<div class="ruler-tick" style="left:' + xt(t, win, span, areaW) + 'px">' + smmss(t - win.a) + '</div>';
  }
  el.innerHTML = html;
}
function smmss(ms) {
  var s = Math.round(ms / 1000), m = Math.floor(s / 60);
  s = s - m * 60;
  return (m ? m + 'm ' : '') + s + 's';
}

function renderWaterfall(ticking) {
  var wf = $('wf');
  if (!wf) return;
  if (!state.calls.size) {
    $('wf-ruler').innerHTML = '';
    $('wf-bars').innerHTML = '<div class="wf-empty">Waiting for the first tool call…</div>';
    return;
  }
  var win = wallWindow(), span = win.b - win.a;
  var area = $('wf-area');
  var areaW = Math.max(area.clientWidth - LABEL_W, 120);
  renderRuler(win, span, areaW);

  var rows = orderedCalls().filter(matchesFilter);
  if (!rows.length && (state.q || state.statusFilter !== 'all')) {
    $('wf-bars').innerHTML = '<div class="wf-empty">No calls match the filter.</div>';
    return;
  }
  var m = rows.length, rowH = 26;
  var bars = '', labels = '';
  for (var i = 0; i < m; i++) {
    var c = rows[i];
    var s = c.start_wall_ms || win.a, e = c.end_wall_ms;
    if (!e && c.status === 'running') e = state.scrub || state.now;
    if (!e) e = s;
    if (state.scrub != null && e > state.scrub) e = state.scrub;
    var x0 = xt(s, win, span, areaW), x1 = xt(e, win, span, areaW);
    var w = Math.max(x1 - x0, 3);
    var elapsed = callElapsed(c);
    var cls = 'bar s-' + c.status;
    if (overBudget(c)) cls += ' over';
    if (c.mode === 'beast') cls += ' beast';
    if (c.mode === 'plan') cls += ' plan';
    var mark = '';
    if (c.budget_s) {
      var bx = xt(s + c.budget_s * 1000, win, span, areaW) - x0;
      if (bx > 2 && bx < w + 6) mark = '<div class="budget-mark" style="left:' + bx + 'px"></div>';
    }
    bars += '<div class="wf-row" style="top:' + (i * rowH) + 'px" data-id="' + c.call_id + '">'
      + '<div class="wf-label" style="padding-left:' + (8 + (c.depth || 0) * 16) + 'px">'
      + '<span class="st-ic st-' + c.status + '">' + (c.status === 'error' ? '✗' : (c.status === 'done' ? '✓' : '●')) + '</span>'
      + esc(c.name) + modeLabel(c.mode) + '</div>'
      + '<div class="track" style="left:' + LABEL_W + 'px">'
      + '<div class="' + cls + '" style="left:' + (x0 - LABEL_W) + 'px;width:' + w + 'px">'
      + mark + '<span class="bar-time">' + fmtDur(elapsed * 1000) + '</span></div></div></div>';
  }
  $('wf-bars').style.height = (m * rowH) + 'px';
  $('wf-bars').innerHTML = bars;
  $('wf-count').textContent = m + '/' + state.calls.size;

  var nowX = xt(state.scrub != null ? state.scrub : state.now, win, span, areaW);
  var cur = $('wf-cursor');
  cur.style.left = nowX + 'px';
  cur.style.display = (state.status === 'running' && ticking) || state.scrub != null ? 'block' : 'none';
}

/* ── tree view ──────────────────────────────────────────────────────────── */
function renderTree() {
  var el = $('tree');
  if (!el) return;
  var hits = 0;
  function walk(id) {
    var c = state.calls.get(id);
    if (!c) return '';
    var kids = childrenOf(id);
    var matched = matchesFilter(c);
    var kidHtml = '';
    if (state.expanded.has(id)) {
      kids.forEach(function (kid) { kidHtml += walk(kid); });
    }
    if (!matched && !kidHtml) return '';
    if (matched) hits++;
    return '<div class="trow" data-id="' + c.call_id + '" style="padding-left:' + (10 + (c.depth || 0) * 18) + 'px">'
      + '<span class="tog' + (kids.length ? '' : ' leaf') + '" data-id="' + c.call_id + '">'
      + (kids.length ? (state.expanded.has(id) ? '▾' : '▸') : '·') + '</span>'
      + '<span class="st-ic st-' + c.status + '">' + (c.status === 'error' ? '✗' : (c.status === 'done' ? '✓' : '●')) + '</span>'
      + '<span class="tname">' + esc(c.name) + modeLabel(c.mode) + '</span>'
      + '<span class="tdur">' + fmtDur(callElapsed(c) * 1000) + '</span>'
      + (overBudget(c) ? '<span class="tob">⏱ over</span>' : '')
      + (c.error ? '<span class="terr">' + esc(c.error) + '</span>' : '')
      + kidHtml + '</div>';
  }
  var html = '';
  roots().forEach(function (id) { html += walk(id); });
  el.innerHTML = html || '<div class="wf-empty">No calls yet.</div>';
  $('wf-count').textContent = hits + '/' + state.calls.size;
}

/* ── stats view ─────────────────────────────────────────────────────────── */
function statTable(rows) {
  if (!rows.length) return '<div class="wf-empty">No calls recorded.</div>';
  var h = '<table class="stat"><tr><th>Tool</th><th>#</th><th>Total</th><th>Avg</th>'
    + '<th>p95</th><th>Max</th><th>Err</th><th>Over budget</th></tr>';
  rows.forEach(function (r) {
    h += '<tr><td>' + esc(r.tool) + '</td><td>' + r.calls + '</td><td>' + fmtDur(r.total) + '</td>'
      + '<td>' + fmtDur(r.avg) + '</td><td>' + fmtDur(r.p95) + '</td><td>' + fmtDur(r.max) + '</td>'
      + '<td class="' + (r.errors ? 'num-err' : '') + '">' + r.errors + '</td>'
      + '<td class="' + (r.over ? 'num-err' : '') + '">' + r.over + '</td></tr>';
  });
  return h + '</table>';
}
function renderStats() {
  var el = $('stats');
  if (!el) return;
  var rows = toolStats(state.calls);
  var totalMs = 0, errs = 0, over = 0, running = 0;
  state.calls.forEach(function (c) {
    var e = callElapsed(c);
    if (e != null) totalMs += e * 1000;
    if (c.status === 'error') errs++;
    if (c.status === 'running') running++;
    if (overBudget(c)) over++;
  });
  $('stat-calls').textContent = state.calls.size;
  $('stat-running').textContent = running;
  $('stat-errors').textContent = errs;
  $('stat-over').textContent = over;
  $('stat-total').textContent = fmtDur(totalMs);
  $('sess-stats').innerHTML = statTable(rows);
  var g = $('global-stats');
  if (g) {
    g.innerHTML = '<div class="section-title">All sessions (live + archived)</div>';
    if (state.globalStats && state.globalStats.per_tool) {
      g.innerHTML += statTable(state.globalStats.per_tool);
      var t = state.globalStats.totals || {};
      g.innerHTML += '<div class="muted">' + state.globalStats.sessions + ' sessions · '
        + t.calls + ' calls · ' + t.errors + ' errors · ' + t.over_budget + ' over budget</div>';
    } else {
      g.innerHTML += '<div class="wf-empty">Global stats will appear as the server accumulates sessions.</div>';
    }
  }
}

/* ── drawer (request/response) ──────────────────────────────────────────── */
function renderDrawer(c) {
  var d = $('drawer');
  if (!d) return;
  if (!c) { d.classList.remove('open'); return; }
  var log = state.events.filter(function (e) { return e.call_id === c.call_id; })
    .map(function (e) {
      return '<div class="d-ev d-ev-' + e.type + '"><span class="d-ts">' + fmtClock(e.wall_ms) + '</span>'
        + esc(e.msg) + '</div>';
    }).join('');
  d.querySelector('.d-name').textContent = c.name;
  d.querySelector('.d-name').style.color = c.status === 'error' ? '#f85149' : '#79c0ff';
  d.querySelector('.d-status').textContent = c.status;
  d.querySelector('.d-status').className = 'd-status st-' + c.status;
  d.querySelector('.d-elapsed').textContent = callElapsed(c) != null ? fmtDur(callElapsed(c) * 1000) : '—';
  d.querySelector('.d-budget').textContent = c.budget_s ? c.budget_s + 's' : '—';
  d.querySelector('.d-wall').textContent = fmtClock(c.start_wall_ms) + ' → ' + fmtClock(c.end_wall_ms);
  d.querySelector('.d-args').textContent = pretty(c.args);
  d.querySelector('.d-payload').textContent = pretty(c.payload || c.error || '(no payload)');
  d.querySelector('.d-log').innerHTML = log || '<div class="wf-empty">no events</div>';
  d.classList.add('open');
}
function closeDrawer() { state.drawerId = null; renderDrawer(null); }

/* ── main render ────────────────────────────────────────────────────────── */
function render() {
  var pill = $('status-pill');
  var timer = $('timer-el');
  function head() {
    if (pill) {
      if (state.mode === 'replay') { pill.className = 'pill done'; pill.textContent = (state.play ? '▶ REPLAYING' : '‖ REPLAY'); }
      else if (state.mode === 'compare') { pill.className = 'pill done'; pill.textContent = '⇄ COMPARE'; }
      else if (state.done) { pill.className = 'pill done'; pill.textContent = '✓ DONE'; }
      else { pill.className = 'pill running'; pill.textContent = '● LIVE'; }
    }
    if (timer) {
      var base = state.session && state.session.started_wall_ms ? state.session.started_wall_ms : (wallWindow().a);
      timer.textContent = fmtDur(state.scrub != null ? state.scrub - base : state.now - base);
    }
  }
  if (state.mode === 'compare') {
    head();
    ['wf', 'tree', 'stats'].forEach(function (p) { var el = $(p); if (el) el.classList.add('hidden'); });
    var cmp = $('cmp'); if (cmp) cmp.classList.remove('hidden');
    return;
  }
  head();
  $('wf').classList.toggle('hidden', state.view !== 'waterfall');
  $('tree').classList.toggle('hidden', state.view !== 'tree');
  $('stats').classList.toggle('hidden', state.view !== 'stats');
  if (state.view === 'waterfall') renderWaterfall(false);
  else if (state.view === 'tree') renderTree();
  else renderStats();
  renderDrawer(state.drawerId ? state.calls.get(state.drawerId) : null);
  $('filter-q').value = state.q;
  $('filter-status').value = state.statusFilter;
}

/* ── live animation loop ────────────────────────────────────────────────── */
function tick() {
  var old = state.now;
  state.now = Date.now();
  if ((state.live && !state.done && document.visibilityState !== 'hidden') || state.play) {
    if (state.play && state.scrub != null && state.scrub < wallWindow().b) {
      state.scrub += (state.now - old) * state.playSpeed;
      if (state.scrub >= wallWindow().b) { state.scrub = wallWindow().b; state.play = false; }
    }
    if (state.view === 'waterfall') renderWaterfall(true);
  }
  requestAnimationFrame(tick);
}

/* ── replay mode ────────────────────────────────────────────────────────── */
function buildReplayControls() {
  var h = $('replay-bar');
  if (!h) return;
  state.scrub = state.endedWall || Date.now();
  h.innerHTML =
    '<div class="rp-ctl"><button id="rp-play">▶</button>'
    + '<input id="rp-range" type="range" min="0" max="1000" value="1000">'
    + '<select id="rp-speed"><option value="4">4×</option><option value="12" selected>12×</option>'
    + '<option value="30">30×</option><option value="100">100×</option></select></div>';
  var range = $('rp-range');
  var win = wallWindow();
  function sync() {
    var v = (state.scrub - win.a) / (win.b - win.a);
    range.value = Math.max(0, Math.min(1000, Math.round(v * 1000)));
  }
  range.addEventListener('input', function () {
    state.scrub = win.a + (range.value / 1000) * (win.b - win.a); render();
  });
  $('rp-play').addEventListener('click', function () {
    state.play = !state.play;
    $('rp-play').textContent = state.play ? '⏸' : '▶';
  });
  $('rp-speed').addEventListener('change', function () {
    state.playSpeed = parseFloat($('rp-speed').value) || 12;
  });
  sync();
}

/* ── compare mode ───────────────────────────────────────────────────────── */
function alignKey(c, callsById) {
  if (!c.parent_id || !callsById.has(c.parent_id)) return c.name;
  var parent = callsById.get(c.parent_id);
  var sibs = childrenOfKey(parent, callsById).filter(function (k) { return k.name === c.name; });
  var idx = sibs.indexOf(c);
  return alignKey(parent, callsById) + ' › ' + c.name + '#' + (idx + 1);
}
function childrenOfKey(c, callsById) {
  var out = [];
  callsById.forEach(function (x) { if (x.parent_id === c.call_id) out.push(x); });
  out.sort(function (a, b) { return (a.start_wall_ms || 0) - (b.start_wall_ms || 0); });
  return out;
}
function docByID(doc) {
  var m = new Map();
  Object.keys(doc.calls || {}).forEach(function (id) { m.set(id, doc.calls[id]); });
  return m;
}
function compareInit() {
  return Promise.all([fetchJSON(BASE + '/archive/' + encodeURIComponent(state.cmpA)),
    fetchJSON(BASE + '/archive/' + encodeURIComponent(state.cmpB))])
    .then(function (docs) {
      state.compare = { a: docs[0], b: docs[1], win: null, rows: null };
      buildCompare();
    })
    .catch(function () { $('wf-bars').innerHTML = '<div class="wf-empty">compare failed to load archives</div>'; });
}
function buildCompare() {
  var ca = docByID(state.compare.a), cb = docByID(state.compare.b);
  var ka = {}, kb = {};
  ca.forEach(function (c) { ka[alignKey(c, ca)] = c; });
  cb.forEach(function (c) { kb[alignKey(c, cb)] = c; });
  var keys = Object.keys(ka).filter(function (k) { return kb[k]; });
  var rows = keys.map(function (k) {
    var ea = callElapsedDoc(ka[k]), eb = callElapsedDoc(kb[k]);
    return { key: k, a: ka[k], b: kb[k], ea: ea, eb: eb,
      d: (ea != null && eb != null) ? eb - ea : null };
  });
  rows.sort(function (x, y) { return ((y.d == null ? 0 : Math.abs(y.d)) - (x.d == null ? 0 : Math.abs(x.d))); });
  state.compare.win = spanOfBoth(ca, cb);
  state.compare.rows = rows;

  var h = '<div class="cmp-head"><div><b>A</b>: ' + esc(state.compare.a.session.session_name)
    + ' <span class="muted">' + ca.size + ' calls</span></div>'
    + '<div><b>B</b>: ' + esc(state.compare.b.session.session_name)
    + ' <span class="muted">' + cb.size + ' calls</span></div><div class="muted">'
    + rows.length + ' aligned calls</div></div>';
  h += cmpHdr(rows);
  $('cmp').innerHTML = h;
  $('cmp').classList.remove('hidden');
  $('wf').classList.add('hidden');
  $('tree').classList.add('hidden');
  $('stats').classList.add('hidden');
}
function callElapsedDoc(c) {
  var e = c.elapsed_s;
  if (e == null && c.end_wall_ms && c.start_wall_ms) e = (c.end_wall_ms - c.start_wall_ms) / 1000;
  return e;
}
function spanOfBoth(a, b) {
  var lo = Infinity, hi = 0;
  function span(map) {
    map.forEach(function (c) {
      var s = c.start_wall_ms || 0, e = c.end_wall_ms || s;
      if (s && s < lo) lo = s;
      if (e && e > hi) hi = e;
    });
  }
  span(a); span(b);
  if (hi - lo < 1000) hi = lo + 1000;
  return { a: lo, b: hi };
}
function cmpHdr(rows) {
  var h = '<table class="stat"><tr><th>Call</th><th>A</th><th>B</th><th>Δ (B−A)</th><th>A status</th><th>B status</th></tr>';
  rows.forEach(function (r) {
    var cls = r.d == null ? '' : (r.d > 0 ? 'num-err' : 'num-ok');
    var dtx = r.d == null ? '—' : ((r.d > 0 ? '+' : '') + fmtDur(r.d * 1000));
    h += '<tr><td class="diffkey">' + esc(r.key) + '</td><td>' + fmtDur(r.ea * 1000) + '</td>'
      + '<td>' + fmtDur(r.eb * 1000) + '</td><td class="' + cls + '">' + dtx + '</td>'
      + '<td>' + (r.a.status === 'error' ? '✗' : r.a.status) + '</td>'
      + '<td>' + (r.b.status === 'error' ? '✗' : r.b.status) + '</td></tr>';
  });
  return h + '</table>';
}

/* ── help modal ─────────────────────────────────────────────────────────── */
function toggleHelp() {
  var m = $('help');
  if (m.classList.contains('open')) { m.classList.remove('open'); return; }
  m.innerHTML = '<div class="help-card"><h2>Keyboard</h2>'
    + '<div>1·2·3 — waterfall / tree / stats</div><div>/ — focus filter</div>'
    + '<div>e / c — expand / collapse all</div><div>Esc — close detail</div>'
    + '<div>? — this help</div>'
    + '<div class="muted">🐄 beast mode · 📋 plan mode</div>'
    + '<button id="help-close">Close</button></div>';
  m.classList.add('open');
  $('help-close').addEventListener('click', toggleHelp);
}
function bindDelegates() {
  var wf = $('wf');
  wf.addEventListener('click', function (e) {
    var row = e.target.closest('.wf-row');
    if (row) { state.drawerId = row.getAttribute('data-id'); render(); }
  });
  var tree = $('tree');
  tree.addEventListener('click', function (e) {
    var tog = e.target.closest('.tog[data-id]');
    if (tog) {
      var id = tog.getAttribute('data-id');
      if (state.expanded.has(id)) state.expanded.delete(id); else state.expanded.add(id);
      render(); return;
    }
    var row = e.target.closest('.trow[data-id]');
    if (row) { state.drawerId = row.getAttribute('data-id'); render(); }
  });
}

/* ── init ────────────────────────────────────────────────────────────────── */
function init() {
  document.addEventListener('visibilitychange', function () {});
  bindToolbar();
  bindDelegates();
  $('help').classList.add('help-root');
  if (state.mode === 'compare') { compareInit(); return; }
  if (state.mode === 'replay') {
    fetchJSON(BASE + '/archive/' + encodeURIComponent(state.file)).then(function (doc) {
      setSessionMeta(doc.session || null);
      state.endedWall = doc.session ? doc.session.ended_wall_ms : 0;
      applyDocument(doc);
      buildReplayControls();
    });
    return;
  }
  /* live */
  fetchData().then(applyDocument).catch(function () { /* server may be mid-start */ });
  fetchJSON(BASE + '/stats').then(function (s) { state.globalStats = s; }).catch(function () {});
  startSSE();
  requestAnimationFrame(tick);
}

document.addEventListener('DOMContentLoaded', init);
"""