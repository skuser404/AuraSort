/* AuraSort - Media Explorer (every file, by category, 100 per page, clear sizes) and Large Files. */
'use strict';
const AGES = [['', 'Any age'], ['30d', 'Changed in the last 30 days'], ['180', 'Not changed for 6 months'], ['365', 'Not changed for 1 year'], ['730', 'Not changed for 2 years']];

function listToolbar(extra = '') { // Why: same filter bar on every list (folder, date, sort, layout)
  const F = S.F, isImg = F.type === 'Images';
  return `<div class="toolbar"><label class="fld">${ic('folder')}<input type="search" data-c="folder" placeholder="Only folders containing…" value="${esc(F.dir ? F.dirPath || F.folder : F.folder)}" maxlength="120" aria-label="Folder contains"></label>
    ${dateBtn()}<select data-c="sort" aria-label="Sort">${SORTS.map(([k, l]) => `<option value="${k}" ${(F.sort || 'size') === k ? 'selected' : ''}>${l}</option>`).join('')}</select>${extra}
    ${isImg ? `<div class="seg" role="group" aria-label="Layout"><button class="${S.layout === 'grid' ? 'on' : ''}" data-a="layout" data-l="grid">${ic('grid')} Grid</button><button class="${S.layout !== 'grid' ? 'on' : ''}" data-a="layout" data-l="list">${ic('list')} List</button></div>` : ''}</div>`;
}
function listBody(r, opts = {}) { // Why: images as a thumbnail grid (if chosen), everything else as a table
  if (!r.rows.length) return '';
  return S.F.type === 'Images' && S.layout === 'grid' && !opts.table ? fileGrid(r.rows) : `<div class="card list-card">${fileTable(r.rows, opts)}</div>`;
}
function listHead(r, label, extra = '') { // Why: count + total size + a "select this page" box above every list
  return `<span class="row nowrap">${r.rows.length ? `<label class="lh-sel" title="Select every file on this page">${pageBox(r.rows, 'Select every file on this page')}</label>` : ''}<span><b class="num">${fmt(r.total)}</b> <span class="mut">${r.total === 1 ? 'file' : 'files'}${label ? ' in ' + esc(label) : ''}</span></span></span>
    <span class="mut">Total ${sizeHtml(r.size)}${extra}</span>`;
}
function dateEmpty(r, what) { // Why: an empty date filter explains itself and offers the nearest days with files
  const near = nearestHtml(r.nearest);
  return empty('calendar', `No ${esc(what)} on ${esc(dateLabel())}`, near ? 'These are the closest days that do have files:' : 'Try another date, or clear the date filter.',
    near + '<button class="btn" data-a="rmf" data-k="date">Clear date</button>');
}

function viewMedia(v) {
  const F = S.F;
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Media Explorer</p><h1>${esc(F.type || 'All files')}</h1><p>Every file ${esc(APP.name)} found, with its size and full folder. Select a name to preview it; tick files to act on them.</p></div>
      <div class="actions"><button class="btn ghost" data-a="nav" data-v="extensions">${ic('tag')} All extensions</button><button class="btn ghost" data-a="nav" data-v="folders">${ic('folder')} Review folders</button></div></div>
    ${mediaTabs('media')}<div id="tabs"><div class="skel" data-css="height:58px"></div></div>${listToolbar()}<div class="fmt-row" id="fmts"></div>
    <div class="list-head" id="lhead"></div><div id="list">${skeletonRows(6)}</div><div id="pager"></div>`;
  S.refresh = loadMedia; loadMedia();
}
async function loadMedia() { // Why: one server request per page: filtered rows + category/format counts
  const token = (loadMedia.n = (loadMedia.n || 0) + 1), params = listParams();
  let r;
  try { r = await API.files(params) } catch (e) { if ($('#list')) $('#list').innerHTML = empty('alert', 'Could not load files', esc(friendly(e)), '<button class="btn" data-a="retry">Try again</button>'); return }
  if (token !== loadMedia.n || !$('#list')) return;
  S.page = r.page; Sel.remember(r.rows, { kind: 'server', params, total: r.total });
  $('#tabs').innerHTML = catTabs(r.facets.cat, S.F.type); applyCss($('#tabs'));
  $('#fmts').innerHTML = fmtChips(r.facets.ext, S.F.formats);
  const label = S.F.type || 'All files';
  $('#lhead').innerHTML = listHead(r, label, S.F.type && VIEW_ONLY.has(S.F.type) ? ' · <span class="badge b-vo">view-only category</span>' : '');
  $('#list').innerHTML = listBody(r) || (S.F.date ? dateEmpty(r, label === 'All files' ? 'files' : label) : empty('search', 'No files match these filters', S.F.formats.size || S.F.folder || S.F.dir ? 'Try clearing the format or folder filter.' : `No ${esc(label)} were found in the scanned folders.`, (S.F.formats.size || S.F.folder || S.F.dir) ? '<button class="btn" data-a="clearf">Clear filters</button>' : ''));
  $('#pager').innerHTML = r.total ? pagerHtml(r) : '';
  renderFilters(); Sel.paint();
}

function viewLarge(v) {
  S.F.sort = S.F.sort || 'size';
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Large Files</p><h1>Biggest files first</h1><p>Every file sorted by size. Filter by type or age to find what is taking space.</p></div></div>
    <div class="toolbar"><select data-c="ltype" aria-label="Type"><option value="">All types</option>${CATS.map(c => `<option value="${esc(c.key)}" ${S.F.type === c.key ? 'selected' : ''}>${esc(c.key)}</option>`).join('')}</select>
      <select data-c="age" aria-label="Age">${AGES.map(([k, l]) => `<option value="${k}" ${(S.age || '') === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <label class="fld">${ic('folder')}<input type="search" data-c="folder" placeholder="Only folders containing…" value="${esc(S.F.folder)}" maxlength="120" aria-label="Folder contains"></label></div>
    <div class="fmt-row" id="fmts"></div><div class="list-head" id="lhead"></div><div id="list">${skeletonRows(6)}</div><div id="pager"></div>`;
  S.refresh = loadLarge; loadLarge();
}
async function loadLarge() {
  const token = (loadLarge.n = (loadLarge.n || 0) + 1), now = Date.now() / 1000, extra = { sort: 'size' };
  if (S.age === '30d') Object.assign(extra, { date: '30d' });
  else if (S.age) Object.assign(extra, { date: '', dfrom: 0, dto: Math.floor(now - Number(S.age) * DAY_S) });
  const params = listParams(extra);
  let r;
  try { r = await API.files(params) } catch (e) { if ($('#list')) $('#list').innerHTML = empty('alert', 'Could not load files', esc(friendly(e))); return }
  if (token !== loadLarge.n || !$('#list')) return;
  S.page = r.page; Sel.remember(r.rows, { kind: 'server', params, total: r.total });
  $('#fmts').innerHTML = fmtChips(r.facets.ext, S.F.formats);
  $('#lhead').innerHTML = listHead(r, '');
  $('#list').innerHTML = r.rows.length ? `<div class="card list-card">${fileTable(r.rows)}</div>` : empty('large', 'No files match', 'Try another type or age.');
  $('#pager').innerHTML = r.total ? pagerHtml(r) : '';
  renderFilters(); Sel.paint();
}
CH.ltype = t => { S.F.type = t.value; S.page = 1; loadLarge(); syncURL('replace') };
CH.age = t => { S.age = t.value; S.page = 1; loadLarge() };
ACT.tab = t => { const k = t.dataset.k; S.F.type = k; S.F.formats = new Set(); S.page = 1; S.fmtAll = false; render(false); syncURL('replace') };
ACT.layout = t => { S.layout = t.dataset.l; try { localStorage.setItem(LAYOUT_KEY, S.layout) } catch (e) { /* ignore */ } render(false) };
ACT.retry = () => S.refresh && S.refresh();
