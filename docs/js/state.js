/* AuraSort - app state and URL (deep link) state. Never puts file paths or the token in the URL. */
'use strict';
const ACT = {};   // click actions: data-a="name"  -> ACT.name(el, event)
const CH = {};    // change/input handlers: data-c="name" -> CH.name(el, event)
// Why: every place that resets the list filters starts from the same blank filter set.
// dir/dirPath = one exact folder ("Show files in this folder"); only its short name goes into the URL (as folder=).
const blankF = (over = {}) => Object.assign({ q: '', type: '', formats: new Set(), folder: '', dir: 0, dirPath: '', sort: '', date: '', from: '', to: '', datefield: '', sens: '' }, over);
const S = {
  view: 'dashboard', info: null, settings: null, drives: [], summary: null, offline: false, hasIndex: false,
  F: blankF(), page: 1, layout: 'list', scan: null, pending: null, notes: [], selectedDrive: '', mv: null,
  sel: new Map(), selAnchor: null, rowsById: new Map(), listCtx: null, tlYear: 0
};

/* ---------------- URL params ---------------- */
const SORT_KEYS = new Set(SORTS.map(s => s[0]));
const DATE_MODES = new Set(['on', 'between', 'today', 'yesterday', '7d', '30d', 'month', 'ym', 'year']);
const DATE_FIELDS = new Set(['modified', 'created', 'accessed']);
const DAY_RX = /^\d{4}-\d{2}-\d{2}$/, MONTH_RX = /^\d{4}-\d{2}$/, YEAR_RX = /^\d{4}$/;
const cleanTxt = (s, n) => String(s || '').replace(/[\u0000-\u001f\u007f<>"`\\]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, n);

function parseParams(search) { // Why: only known params, each validated; anything else is dropped
  const u = new URLSearchParams(search), o = { formats: [] };
  const v = (u.get('view') || '').toLowerCase(); if (VIEWS.includes(v)) o.view = v;
  const q = cleanTxt(u.get('q'), 100); if (q) o.q = q;
  const t = (u.get('type') || '').trim().toLowerCase(), c = CATS.find(c => c.key.toLowerCase() === t); if (c) o.type = c.key;
  o.formats = [...new Set((u.get('format') || '').toLowerCase().split(',').map(s => s.trim().replace(/^\./, '')).filter(s => /^[a-z0-9]{1,10}$/.test(s)))].slice(0, 30);
  const fo = cleanTxt(u.get('folder'), 120); if (fo) o.folder = fo;
  const so = (u.get('sort') || '').toLowerCase(); if (SORT_KEYS.has(so)) o.sort = so;
  const dm = (u.get('date') || '').toLowerCase(); if (DATE_MODES.has(dm)) o.date = dm;
  for (const k of ['from', 'to']) { const val = (u.get(k) || '').trim(); if (/^\d{4}(-\d{2}(-\d{2})?)?$/.test(val)) o[k] = val }
  if (o.date && !dateArgsOk(o.date, o.from, o.to)) { delete o.date; delete o.from; delete o.to }
  const df = (u.get('datefield') || '').toLowerCase(); if (DATE_FIELDS.has(df)) o.datefield = df;
  const se = (u.get('sens') || '').toLowerCase(); if (['confidential', 'sensitive', 'normal'].includes(se)) o.sens = se;
  o.has = !!(o.view || o.q || o.type || o.formats.length || o.folder || o.sort || o.date || o.sens);
  return o;
}
function dateArgsOk(mode, from, to) { // Why: a date mode is only kept when its arguments have the right shape
  if (mode === 'on') return DAY_RX.test(from || '');
  if (mode === 'between') return DAY_RX.test(from || '') && (!to || DAY_RX.test(to));
  if (mode === 'ym') return MONTH_RX.test(from || '');
  if (mode === 'year') return YEAR_RX.test(from || '') && +from >= YEAR_MIN && +from <= YEAR_MAX;
  return true;
}
function stateParams() { // Why: the URL reflects the current view and its filters
  const v = S.view, F = S.F, o = { view: v === 'dashboard' ? '' : v };
  if (['media', 'search', 'large'].includes(v)) Object.assign(o, { q: v === 'search' ? F.q.trim() : '', type: F.type, formats: [...F.formats], folder: F.folder.trim(), sort: F.sort, date: F.date, from: F.from, to: F.to, datefield: F.datefield });
  if (v === 'timeline') Object.assign(o, { type: F.type, datefield: F.datefield, date: F.date === 'year' ? 'year' : '', from: F.date === 'year' ? F.from : '' });
  if (v === 'folders') Object.assign(o, { folder: F.folder.trim(), type: F.type });
  if (v === 'insights' && S.insTab === 'documents') Object.assign(o, { sens: F.sens });
  return o;
}
function buildQuery(o) { // Why: stable order; commas kept readable in format=png,jpg
  const parts = [];
  if (DEMO_Q) parts.push('demo');
  const add = (k, val) => { if (val) parts.push(k + '=' + encodeURIComponent(val).replace(/%2C/gi, ',')) };
  add('view', o.view); add('q', cleanTxt(o.q, 100)); add('type', o.type); add('format', (o.formats || []).join(','));
  add('folder', cleanTxt(o.folder, 120)); add('sort', o.sort); add('date', o.date); add('from', o.from); add('to', o.to); add('datefield', o.datefield); add('sens', o.sens);
  return parts.length ? '?' + parts.join('&') : '';
}
function syncURL(mode = 'push') { // Why: replaceState while typing, pushState on view changes
  if (S.pending && !S.hasIndex) return;
  const url = location.pathname + buildQuery(stateParams()) + location.hash;
  if (url === location.pathname + location.search + location.hash) return;
  try { history[mode === 'replace' ? 'replaceState' : 'pushState']({ app: 1 }, '', url) } catch (e) { /* sandboxed */ }
}
function applyParams(o) { // Why: deep links and Back/Forward restore the same view and filters
  const v = o.view || (o.q ? 'search' : o.type || o.formats.length ? 'media' : 'dashboard');
  S.view = v; S.page = 1;
  S.F = blankF({ q: o.q || '', type: o.type || '', formats: new Set(o.formats || []), folder: o.folder || '', sort: o.sort || '', date: o.date || '', from: o.from || '', to: o.to || '', datefield: o.datefield || '', sens: o.sens || '' });
  if (o.sens) S.insTab = 'documents';
}
function listParams(extra = {}) { // Why: the same filters go to the server (lists) and the worker (search)
  const F = S.F;
  return Object.assign({ type: F.type, format: [...F.formats], folder: F.folder.trim(), dir: F.dir || '', sort: F.sort || 'size', date: F.date, from: F.from, to: F.to, datefield: F.datefield, page: S.page, per: PAGE_SIZE }, extra);
}
