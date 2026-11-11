/* AuraSort - Storage Analysis: overview, All extensions table, Review folders (include/exclude). */
'use strict';
const storageTabs = cur => `<div class="seg" role="tablist" data-css="margin-bottom:18px">${[['storage', 'Overview', 'storage'], ['extensions', 'All extensions', 'tag'], ['folders', 'Folders', 'folder']]
  .map(([v, l, i]) => `<button class="${cur === v ? 'on' : ''}" data-a="nav" data-v="${v}" role="tab" aria-selected="${cur === v}">${ic(i)} ${l}</button>`).join('')}</div>`;

function viewStorage(v) {
  const s = S.summary, tot = s.total_size, rows = CATS.map(c => ({ c, x: s.by_cat[c.key] || { n: 0, size: 0, ready: 0 } })).sort((a, b) => b.x.size - a.x.size);
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Storage Analysis</p><h1>Where your space goes</h1><p>${fmt(s.total)} files · ${sz(s.total_size)} scanned. All 14 file types are listed, including the ones you have none of.</p></div></div>
    ${storageTabs('storage')}
    <section class="card"><div class="card-h"><h2>Space by file type</h2><small>select a row to see those files</small></div>
      <div class="segbar">${barSegs(rows).map(x => `<button class="sg" data-css="--c:${x.c};flex-grow:${(pct(x.size, tot) / 100).toFixed(5)}" ${x.key ? `data-a="nav-type" data-k="${esc(x.key)}"` : ''} data-tip="${esc(x.label)}" aria-label="${esc(x.label)}: ${sz(x.size)}, ${fmt(x.n)} files"></button>`).join('')}</div>
      <div class="tbl-wrap" data-css="margin-top:16px"><table class="tbl"><thead><tr><th>Type</th><th class="r">Files</th><th class="r">Size</th><th>Share</th><th class="r">Ready to sort</th></tr></thead><tbody>
      ${rows.map(r => `<tr class="${r.x.n ? '' : 'dim'}"><td><button class="link" data-a="nav-type" data-k="${esc(r.c.key)}" data-css="color:inherit;text-decoration:none;display:inline-flex;gap:10px;align-items:center"><span class="sw" data-css="--c:${r.c.c}"></span><span class="ficon" data-css="width:34px;height:34px">${ic(r.c.ic)}</span><b>${esc(r.c.key)}</b></button> ${r.c.vo ? '<span class="badge b-vo">view-only</span>' : ''}</td>
        <td class="r num">${fmt(r.x.n)}</td><td class="r">${sizeHtml(r.x.size)}</td><td><div class="row" data-css="flex-wrap:nowrap"><span class="mini" data-css="flex:1;min-width:80px"><i data-css="width:${pct(r.x.size, tot).toFixed(1)}%;background:${r.c.c}"></i></span><span class="num">${pctTxt(share(r.x.size, tot))}</span></div></td><td class="r num">${r.c.vo ? '—' : fmt(r.x.ready)}</td></tr>`).join('')}
      </tbody></table></div></section>`;
}

/* ---------------- All extensions ---------------- */
function viewExtensions(v) {
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Storage Analysis</p><h1>All extensions</h1><p>Every extension found, with file count, size, share of the disk and category. Select one to list its files.</p></div></div>
    ${storageTabs('extensions')}<div class="toolbar"><label class="fld">${ic('search')}<input type="search" data-c="extq" placeholder="Filter extensions…" value="${esc(S.extQ || '')}" aria-label="Filter extensions"></label>
    <select data-c="extsort" aria-label="Sort">${[['size', 'Biggest first'], ['n', 'Most files'], ['ext', 'Extension A–Z'], ['cat', 'Category']].map(([k, l]) => `<option value="${k}" ${(S.extSort || 'size') === k ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
    <div class="card list-card" id="extbox">${'<div class="skel row"></div>'.repeat(6)}</div>`;
  loadExtensions();
}
async function loadExtensions() {
  if (!S.extData) { try { S.extData = await API.extensions() } catch (e) { $('#extbox').innerHTML = empty('alert', 'Could not load extensions', esc(friendly(e))); return } }
  drawExtensions();
}
function drawExtensions() {
  const box = $('#extbox'); if (!box) return;
  const q = (S.extQ || '').toLowerCase().replace(/^\./, ''), k = S.extSort || 'size', disk = S.extData.disk_total || 0, totalSize = S.extData.rows.reduce((a, r) => a + r.size, 0);
  let rows = S.extData.rows.filter(r => !q || r.ext.includes(q) || r.cat.toLowerCase().includes(q));
  rows.sort(k === 'n' ? (a, b) => b.n - a.n : k === 'ext' ? (a, b) => a.ext.localeCompare(b.ext) : k === 'cat' ? (a, b) => a.cat.localeCompare(b.cat) || b.size - a.size : (a, b) => b.size - a.size);
  const shareOf = r => disk ? share(r.disk_size ?? r.size, disk) : share(r.size, totalSize);   // Why: online-only files take no disk space
  box.innerHTML = `<div class="vhead ext-row"><span>Extension</span><span>Files</span><span>Size</span><span>${disk ? '% of disk' : '% of scanned'}</span><span>Category</span></div><div class="vlist" id="extlist"></div>
    <p class="mut" data-css="margin:10px 12px">${fmt(rows.length)} extensions · ${sz(rows.reduce((a, r) => a + r.size, 0))}</p>`;
  applyCss(box);
  virtualList($('#extlist'), rows, 52, r => `<button class="link" data-a="extopen" data-x="${esc(r.ext)}" data-css="text-align:left"><span class="ext">.${esc(r.ext || 'none')}</span></button><span class="num">${fmt(r.n)}</span>${sizeHtml(r.size)}
    <span class="row" data-css="flex-wrap:nowrap"><span class="mini" data-css="flex:1"><i data-css="width:${Math.max(1, Math.min(100, (shareOf(r) ?? 0) * (disk ? 20 : 1))).toFixed(1)}%"></i></span><span class="num">${shareOf(r) == null ? 'n/a' : shareOf(r) < .01 && shareOf(r) > 0 ? '<0.01%' : shareOf(r).toFixed(2) + '%'}</span></span>
    <span class="row" data-css="flex-wrap:nowrap;--c:${(CAT[r.cat] || CAT.Other).c}"><span data-css="color:var(--c)">${ic((CAT[r.cat] || CAT.Other).ic)}</span>${esc(r.cat)}</span>`, 'ext-row');
}
CH.extq = t => { S.extQ = t.value; drawExtensions() };
CH.extsort = t => { S.extSort = t.value; drawExtensions() };
ACT.extopen = t => { S.F = Object.assign({}, S.F, { type: '', formats: new Set([t.dataset.x]), folder: '', q: '' }); go('media') };

/* ---------------- Review folders ---------------- */
function viewFolders(v) {
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Storage Analysis</p><h1>Review folders</h1><p>Ticked folders are included when you sort. Project, asset-like and already-sorted folders start unticked so nothing breaks.</p></div>
      <div class="actions"><button class="btn sm" data-a="inc-preset" data-p="safe">${ic('check')} Select all safe</button><button class="btn sm ghost" data-a="inc-preset" data-p="none">Deselect all</button><button class="btn sm danger" data-a="inc-preset" data-p="all">Select all (incl. projects)</button></div></div>
    ${storageTabs('folders')}
    <div class="toolbar"><label class="fld">${ic('search')}<input type="search" data-c="folder" placeholder="Search folders…" value="${esc(S.F.folder)}" aria-label="Search folders"></label>
      <select data-c="ftype" aria-label="Type"><option value="">All types</option>${CATS.map(c => `<option value="${esc(c.key)}" ${S.F.type === c.key ? 'selected' : ''}>${esc(c.key)}</option>`).join('')}</select>
      <select data-c="fkind" aria-label="Folder kind"><option value="all">All folders</option><option value="warn" ${S.fkind === 'warn' ? 'selected' : ''}>Only projects / assets / sorted</option></select></div>
    <div class="card list-card"><div class="vhead"><span></span><span>Folder</span><span>Files</span><span>Size</span><span>Types</span><span></span></div><div class="vlist" id="flist">${'<div class="skel row"></div>'.repeat(5)}</div><p class="mut" id="fcount" data-css="margin:10px 12px"></p></div>`;
  S.refresh = loadFolders; loadFolders();
}
async function loadFolders() {
  let rows;
  try { rows = await API.folders({ q: S.F.folder.trim(), type: S.F.type, kind: S.fkind || 'all' }) } catch (e) { $('#flist').innerHTML = empty('alert', 'Could not load folders', esc(friendly(e))); return }
  if (!$('#flist')) return;
  S.folderRows = rows;
  $('#fcount').innerHTML = `${fmt(rows.length)} folders · ${fmt(rows.filter(r => r.included).length)} ticked · ${sz(rows.reduce((a, r) => a + r.size, 0))}`;
  if (!rows.length) { $('#flist').innerHTML = empty('folder', 'No folders match', 'Try another search or type.'); return }
  S.vfolders = virtualList($('#flist'), rows, 64, r => {
    const b = r.kind === 'project' ? `<span class="badge b-proj">${ic('lock')} project${r.project_path ? ': ' + esc(base(r.project_path)) : ''}</span>` : r.kind === 'assets' ? '<span class="badge b-asset">looks like app/site assets</span>' : r.kind === 'sorted' ? '<span class="badge b-sorted">already sorted</span>' : '<span class="badge b-ok">safe</span>';
    return `<input type="checkbox" data-c="inc" data-id="${r.id}" ${r.included ? 'checked' : ''} aria-label="Include ${esc(r.path)}"><span data-css="min-width:0"><span class="fpath" title="${esc(r.path)}">${esc(parentOf(r.path))}${r.path.includes('\\') ? '\\' : '/'}<b>${esc(base(r.path))}</b></span> ${b}</span>
      <span class="num">${fmt(r.n)}</span>${sizeHtml(r.size)}<span class="row" data-css="gap:6px;flex-wrap:nowrap;overflow:hidden">${CATS.filter(c => r.by[c.key]).slice(0, 5).map(c => `<span title="${esc(c.key)}: ${fmt(r.by[c.key])}" data-css="color:var(--mut)">${ic(c.ic)}</span>`).join('')}</span>
      <button class="btn sm ghost" data-a="folderf" data-f="${esc(base(r.path))}" data-dir="${r.id}" data-p="${esc(r.path)}" title="Show the files in this folder">${ic('explore')} Show files</button>`;
  });
}
CH.ftype = t => { S.F.type = t.value; loadFolders(); syncURL('replace') };
CH.fkind = t => { S.fkind = t.value; loadFolders() };
CH.inc = async t => { // Why: ticking a project or asset folder needs an explicit warning confirmation
  const id = +t.dataset.id, row = (S.folderRows || []).find(r => r.id === id), on = t.checked;
  if (on && row && row.kind !== 'ok') {
    const ok = await confirmDialog({ title: row.kind === 'project' ? 'Include a project folder?' : 'Include this folder?', danger: true, ok: 'Include it',
      body: `<p><b>${esc(row.path)}</b></p><p>${row.kind === 'project' ? 'Files inside a project (website, app, video edit…) belong to it. Moving them can break the project.' : row.kind === 'sorted' ? 'These files were already sorted by ' + esc(APP.name) + '.' : 'This looks like app or website assets. Moving them can break that app or site.'}</p>`, check: 'I understand the risk' });
    if (!ok) { t.checked = false; return }
  }
  try { await API.include({ ids: [id], included: on }); if (row) row.included = on; await refreshIndex() } catch (e) { t.checked = !on; toastError(e) }
};
ACT['inc-preset'] = async t => {
  const p = t.dataset.p;
  if (p === 'all' && !await confirmDialog({ title: 'Include every folder, projects too?', danger: true, ok: 'Include all', body: 'Moving files out of projects can break websites, apps and video edits.', check: 'I understand the risk' })) return;
  try { await API.include({ preset: p }); await refreshIndex(); loadFolders(); toast(p === 'safe' ? 'Safe folders selected' : p === 'none' ? 'All folders unticked' : 'All folders selected', 'ok') } catch (e) { toastError(e) }
};
