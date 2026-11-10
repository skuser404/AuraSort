/* AuraSort - Search: fuzzy name search in a Web Worker (fast on 200k+ files), results grouped by type, 100 per page. */
'use strict';
function viewSearch(v) {
  const F = S.F;
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Search</p><h1>${F.q.trim() ? `Results for “${esc(F.q.trim())}”` : 'Search every file'}</h1><p>Matches file names only: partial words, any case, small typos. Type “.png” to match an extension.</p></div></div>
    <div class="toolbar"><select data-c="stype" aria-label="Type"><option value="">All types</option>${CATS.map(c => `<option value="${esc(c.key)}" ${F.type === c.key ? 'selected' : ''}>${esc(c.key)}</option>`).join('')}</select>
      <select data-c="sort" aria-label="Sort"><option value="" ${!F.sort ? 'selected' : ''}>Best match</option>${SORTS.map(([k, l]) => `<option value="${k}" ${F.sort === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
      ${dateBtn()}<label class="fld">${ic('folder')}<input type="search" data-c="folder" placeholder="Only folders containing…" value="${esc(F.folder)}" maxlength="120" aria-label="Folder contains"></label></div>
    <div class="fmt-row" id="fmts"></div><div class="list-head" id="lhead"></div><div id="sres">${skeletonRows(4)}</div><div id="pager"></div>`;
  S.refresh = runSearch; runSearch();
}
async function runSearch() { // Why: the worker ranks ids; the page's rows (paths, flags) come from the server
  const token = (runSearch.n = (runSearch.n || 0) + 1), F = S.F, q = F.q.trim();
  if (S.view !== 'search' || !$('#sres')) return;   // a delayed search (typing debounce) after you left the page: nothing to update
  if (!q &&!F.type && !F.formats.size && !F.folder.trim() && !F.date && !F.dir) {
    $('#fmts').innerHTML = ''; $('#lhead').innerHTML = ''; $('#pager').innerHTML = ''; Sel.remember([], null); Sel.paint();
    $('#sres').innerHTML = empty('search', `Search ${fmt(S.summary ? S.summary.total : 0)} files`, 'Start typing in the search bar (Ctrl+K). “light” finds lighthouse_sunset.jpg, Spotlight.png and light-mode.pdf.',
      ['light', 'invoice', 'IMG_20', 'screenshot'].map(x => `<button class="chip" data-a="tryq" data-q="${esc(x)}">${esc(x)}</button>`).join(''));
    return;
  }
  let r, rows;
  const params = Object.assign(listParams({ sort: F.sort || '' }), { q, fuzzy: true });
  try { r = await Search.query(params, S.summary ? S.summary.version : 0); rows = await API.rows(r.ids) }
  catch (e) { if ($('#sres')) $('#sres').innerHTML = empty('alert', 'Search is unavailable', esc(friendly(e)), '<button class="btn" data-a="retry">Try again</button>'); return }
  if (token !== runSearch.n || !$('#sres')) return;
  S.page = r.page; Sel.remember(rows, { kind: 'search', params, total: r.total });
  $('#fmts').innerHTML = fmtChips(r.facets.ext, F.formats);
  $('#lhead').innerHTML = r.total ? `<span class="row nowrap"><label class="lh-sel" title="Select every file on this page">${pageBox(rows, 'Select every file on this page')}</label><span><b class="num">${fmt(r.total)}</b> <span class="mut">${r.total === 1 ? 'match' : 'matches'}${q ? ` for “${esc(q)}”` : ''} · grouped by type · ${r.ms} ms</span></span></span><span class="mut">Total ${sizeHtml(r.size)}</span>` : '';
  if (!r.total) {
    $('#sres').innerHTML = empty('search', q ? `No files match “${esc(q)}”` : 'No files match these filters', 'Check the spelling, try fewer letters, or remove a filter.',
      `${F.formats.size ? '<button class="btn ghost" data-a="fmt-clear">Clear formats</button>' : ''}${F.type ? '<button class="btn ghost" data-a="rmf" data-k="type">All types</button>' : ''}<button class="btn" data-a="clearf">Clear everything</button>`);
    $('#pager').innerHTML = ''; return;
  }
  const groups = new Map(); for (const row of rows) { if (!groups.has(row.cat)) groups.set(row.cat, []); groups.get(row.cat).push(row) }
  $('#sres').innerHTML = [...groups].map(([cat, list]) => `<section class="res-group" data-css="--c:${CAT[cat].c}"><h3>${ic(CAT[cat].ic)} ${esc(cat)} <span class="num dim">${fmt(list.length)}</span></h3><div class="card list-card">${fileTable(list, { q })}</div></section>`).join('');
  $('#pager').innerHTML = pagerHtml(r);
  renderFilters(); Sel.paint();
}
let sqT;
function onSearchInput(val) { // Why: typing anywhere jumps to Search; the URL is replaced (not pushed) while typing
  S.F.q = val.slice(0, 100);
  if (!S.hasIndex) { S.pending = { view: 'search', q: S.F.q, formats: [], has: true }; return }
  if (S.view !== 'search') { const keepType = S.view === 'media' ? S.F.type : ''; S.F = Object.assign({}, S.F, { type: keepType, formats: S.view === 'media' ? S.F.formats : new Set(), folder: '', dir: 0, dirPath: '', sort: '' }); S.view = 'search'; S.page = 1; render(); syncURL('push'); return }
  clearTimeout(sqT); sqT = setTimeout(() => { S.page = 1; runSearch(); syncURL('replace') }, SEARCH_DEBOUNCE_MS);
}
CH.stype = t => { S.F.type = t.value; S.page = 1; runSearch(); syncURL('replace') };
ACT.tryq = t => { $('#gq').value = t.dataset.q; S.F.q = t.dataset.q; S.page = 1; runSearch(); syncURL('replace'); $('#gq').focus() };
