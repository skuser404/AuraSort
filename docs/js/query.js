/* AuraSort - shared filter/sort/page engine over a column table (no DOM). Used by the search worker and the demo backend.
   Semantics mirror core/index_db.py so demo, search and server lists behave the same. */
'use strict';
const Q_CATS = ['Images', 'Videos', 'Audio', 'Documents', 'PDFs', 'Sheets & Slides', 'Archives', 'Installers & Apps', 'Disk images', 'Code & Scripts', 'Text & Logs', 'Fonts', 'Databases', 'Other'];
const Q_VIEW_ONLY = new Set(Q_CATS.slice(7));
const Q_DATE_COL = { modified: 'mtime', created: 'ctime', accessed: 'atime' };

function qTable(src) { // Why: precompute lowercase NFC names, base names and letter masks once (fast search on 200k files)
  const T = Object.assign({}, src), n = T.id.length;
  T.ln = new Array(n); T.lb = new Array(n); T.mask = new Int32Array(n);
  for (let i = 0; i < n; i++) {
    const ln = String(T.name[i]).normalize('NFC').toLowerCase(), dot = ln.lastIndexOf('.'), lb = dot > 0 ? ln.slice(0, dot) : ln;
    T.ln[i] = ln; T.lb[i] = lb; T.mask[i] = charMask(lb);
  }
  T.dirL = T.dirs.map(d => String(d.path).normalize('NFC').toLowerCase());
  T.pos = new Map(T.id.map((id, i) => [id, i]));
  return T;
}

function qDateRange(mode, a, b, now) { // Why: same date modes as core/dates.py, in the local time zone
  if (!mode) return null;
  const today = now ? new Date(now * 1000) : new Date(); today.setHours(0, 0, 0, 0);
  const day = (y, m, d) => new Date(y, m, d).getTime() / 1000, Y = today.getFullYear(), M = today.getMonth(), D = today.getDate();
  const parse = s => { const p = String(s || '').split('-').map(Number); if (p.length < 3 || p.some(isNaN)) throw new Error('Bad date'); return p };
  if (mode === 'today') return [day(Y, M, D), day(Y, M, D + 1)];
  if (mode === 'yesterday') return [day(Y, M, D - 1), day(Y, M, D)];
  if (mode === '7d') return [day(Y, M, D - 6), day(Y, M, D + 1)];
  if (mode === '30d') return [day(Y, M, D - 29), day(Y, M, D + 1)];
  if (mode === 'month') return [day(Y, M, 1), day(Y, M + 1, 1)];
  if (mode === 'on') { const [y, m, d] = parse(a); return [day(y, m - 1, d), day(y, m - 1, d + 1)] }
  if (mode === 'between') { let [s, e] = [parse(a), parse(b || a)].map(([y, m, d]) => day(y, m - 1, d)); if (e < s) [s, e] = [e, s]; return [s, e + DAY_S_Q(e)] }
  if (mode === 'ym') { const [y, m] = String(a).split('-').map(Number); return [day(y, m - 1, 1), day(y, m, 1)] }
  if (mode === 'year') { const y = Number(a); return [day(y, 0, 1), day(y + 1, 0, 1)] }
  throw new Error('Unknown date filter');
}
function DAY_S_Q(t) { const d = new Date(t * 1000); return (new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1).getTime() / 1000) - t } // DST-safe day length

function qPass(T, i, f, skip) { // Why: one row against the filter (skip = filter keys to ignore, used for facet counts)
  if (f.cat && skip !== 'cat' && T.cat[i] !== f.cat) return false;
  if (f.exts && f.exts.size && skip !== 'ext' && !f.exts.has(T.ext[i])) return false;
  if (f.folder && T.dirL[T.dir[i]].indexOf(f.folder) < 0) return false;
  if (f.dirId && T.dirs[T.dir[i]].id !== f.dirId) return false;
  if (f.range) { const v = T[f.dcol][i]; if (!(v >= f.range[0] && v < f.range[1])) return false }
  if (f.scope === 'ready' && (!T.dirs[T.dir[i]].included || Q_VIEW_ONLY.has(T.cat[i]))) return false;
  if (f.scope === 'included' && !T.dirs[T.dir[i]].included) return false;
  if (f.subq && f.subq.some(tok => T.ln[i].indexOf(tok) < 0)) return false;
  return true;
}
function qNorm(p) { // Why: URL-style params -> a compiled filter
  const f = { cat: p.type && p.type !== 'all' ? p.type : '', exts: new Set((Array.isArray(p.format) ? p.format : String(p.format || '').split(',')).filter(Boolean)),
    folder: String(p.folder || '').normalize('NFC').toLowerCase(), dirId: Number(p.dir) || 0, scope: p.scope || 'all', dcol: Q_DATE_COL[p.datefield] || 'mtime',
    subq: p.q && !p.fuzzy ? String(p.q).normalize('NFC').toLowerCase().split(/\s+/).filter(Boolean) : null };
  if (p.date) f.range = qDateRange(p.date, p.from, p.to);
  else if (p.dfrom != null && p.dto != null && p.dfrom !== '') f.range = [Number(p.dfrom), Number(p.dto)];
  return f;
}
function qSort(T, idx, sort, dcol, score) { // Why: same orders as the server (ties broken by id)
  const by = sort === 'rel' ? (a, b) => (score[b] - score[a]) || (T.name[a].length - T.name[b].length)
    : sort === 'name' ? (a, b) => (T.ln[a] < T.ln[b] ? -1 : T.ln[a] > T.ln[b] ? 1 : T.id[a] - T.id[b])
    : sort === 'date' ? (a, b) => (T[dcol][b] - T[dcol][a]) || (T.id[b] - T.id[a])
    : sort === 'oldest' ? (a, b) => (T[dcol][a] - T[dcol][b]) || (T.id[a] - T.id[b])
    : sort === 'smallest' ? (a, b) => (T.size[a] - T.size[b]) || (T.id[a] - T.id[b])
    : (a, b) => (T.size[b] - T.size[a]) || (T.id[b] - T.id[a]);   // same tie-breaks as the server (index order)
  return idx.sort(by);
}
function qFacets(T, idxAll, f) { // Why: format chips count everything except the format filter; category tabs everything except the type
  const ext = new Map(), cat = {};
  for (const i of idxAll) {
    if (qPass(T, i, f, 'ext')) ext.set(T.ext[i], (ext.get(T.ext[i]) || 0) + 1);
    if (qPass(T, i, f, 'cat')) { const c = cat[T.cat[i]] || (cat[T.cat[i]] = { n: 0, size: 0 }); c.n++; c.size += T.size[i] }
  }
  return { ext: [...ext].sort((a, b) => b[1] - a[1]), cat };
}
function qRow(T, i) { // Why: same JSON shape as the server's file rows
  const d = T.dirs[T.dir[i]];
  return { id: T.id[i], name: T.name[i], ext: T.ext[i], cat: T.cat[i], sub: T.sub ? T.sub[i] : '', size: T.size[i], mtime: T.mtime[i], ctime: T.ctime[i] || null,
    atime: T.atime[i] || null, flags: 0, dir: d.id, path: d.path, kind: d.kind, project: d.project ?? -1, included: !!d.included, viewonly: Q_VIEW_ONLY.has(T.cat[i]) };
}
function qList(T, p) { // Why: filter + facets + sort + page in one call (demo backend's /api/files)
  const f = qNorm(p), all = [], base = [];
  for (let i = 0; i < T.id.length; i++) { if (qPass(T, i, Object.assign({}, f, { cat: '', exts: null }))) base.push(i) }
  for (const i of base) if (qPass(T, i, f)) all.push(i);
  qSort(T, all, p.sort || 'size', f.dcol);
  const per = Math.min(500, Number(p.per) || 100), pages = Math.max(1, Math.ceil(all.length / per)), page = clampQ(Number(p.page) || 1, 1, pages);
  let size = 0; for (const i of all) size += T.size[i];
  return { total: all.length, size, page, pages, per, rows: all.slice((page - 1) * per, page * per).map(i => qRow(T, i)), facets: qFacets(T, base, f), _idx: all };
}
const clampQ = (v, a, b) => Math.min(b, Math.max(a, v));
