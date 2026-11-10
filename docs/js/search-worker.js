/* AuraSort - search worker: fuzzy name search + filters off the main thread, so typing stays instant on 200k+ files.
   Real mode: fetches /api/search-index once per index version. Demo mode: receives the fake table by postMessage. */
'use strict';
const DAY_S = 86400; // eslint-disable-line no-unused-vars
importScripts('match.js', 'query.js');
let T = null, version = null;

async function loadReal(token, want) { // Why: one compact index per index version; columns, not full records
  const r = await fetch('/api/search-index', { headers: { 'X-AuraSort-Token': token } });
  if (!r.ok) throw new Error('index ' + r.status);
  const j = await r.json();
  const cats = j.cats, exts = j.exts, n = j.id.length;
  const src = { id: j.id, name: j.name, cat: new Array(n), ext: new Array(n), dir: j.dir, size: j.size, mtime: j.mtime, ctime: j.ctime, atime: j.atime,
    dirs: j.dirs.map((p, i) => ({ id: j.dir_id ? j.dir_id[i] : i, path: p, kind: j.dir_kind[i], included: j.dir_inc[i] })) };
  for (let i = 0; i < n; i++) { src.cat[i] = cats[j.cat[i]]; src.ext[i] = exts[j.ext[i]] }
  T = qTable(src); version = want ?? j.version;
}

function search(p) { // Why: exact/partial matches first; the typo pass runs only when they are scarce
  const toks = tokens(p.q || ''), f = qNorm(Object.assign({}, p, { q: '' })), noCat = Object.assign({}, f, { cat: '', exts: null }), base = [], score = new Float64Array(T.id.length);
  for (let i = 0; i < T.id.length; i++) {
    if (!qPass(T, i, noCat)) continue;
    if (toks.length) { const s = scoreName(T.ln[i], T.lb[i], T.mask[i], toks, false); if (!s) continue; score[i] = s }
    base.push(i);
  }
  if (toks.length && base.length < 100 && toks.some(t => t.t.length >= 4)) {
    const have = new Set(base);
    for (let i = 0; i < T.id.length; i++) {
      if (have.has(i) || !qPass(T, i, noCat)) continue;
      const s = scoreName(T.ln[i], T.lb[i], T.mask[i], toks, true); if (s) { score[i] = s; base.push(i) }
    }
  }
  const hits = base.filter(i => qPass(T, i, f));
  qSort(T, hits, p.sort || (toks.length ? 'rel' : 'size'), f.dcol, score);
  const per = Math.min(500, Number(p.per) || 100), pages = Math.max(1, Math.ceil(hits.length / per)), page = Math.min(Math.max(1, Number(p.page) || 1), pages);
  let size = 0; for (const i of hits) size += T.size[i];
  const out = { total: hits.length, size, page, pages, per, ids: hits.slice((page - 1) * per, page * per).map(i => T.id[i]), facets: qFacets(T, base, f) };
  if (p.allIds) { out.all = hits.map(i => T.id[i]); out.allSizes = hits.map(i => T.size[i]) }
  return out;
}

onmessage = async e => {
  const m = e.data;
  try {
    if (m.type === 'demo') { T = qTable(m.table); version = m.version; postMessage({ id: m.id, ok: true }); return }
    if (m.type === 'ensure') { if (version !== m.version || !T) await loadReal(m.token, m.version); postMessage({ id: m.id, ok: true, n: T.id.length }); return }
    if (m.type === 'search') { if (!T) throw new Error('index not loaded'); const t0 = performance.now(); const r = search(m.params); r.ms = Math.round(performance.now() - t0); postMessage(Object.assign({ id: m.id }, r)) }
  } catch (err) { postMessage({ id: m.id, error: String(err && err.message || err) }) }
};
