/* AuraSort - shell and shared UI components (sidebar, top bar, toasts, modals, tooltips, pager, chips, file lists). */
'use strict';

/* ---------------- shell ---------------- */
function renderNav() { // Why: the sidebar mirrors the current view (glowing pill) and the index state
  const on = id => S.view === id || (NAV.find(n => n.id === id)?.also || []).includes(S.view);
  $('#nav').innerHTML = `<div class="brand">${LOGO}<div><b>${esc(APP.name)}</b><small>${esc(APP.tagline)}</small></div></div>
    <button class="btn pri scan-cta" data-a="nav" data-v="scan">${ic('scan')} ${S.hasIndex ? 'Scan again' : 'Scan my PC'}</button><nav aria-label="Pages">`
    + NAV.map(n => n.h ? `<div class="nav-h">${esc(n.h)}</div>` : `<button class="nav-i ${on(n.id) ? 'on' : ''}" data-a="nav" data-v="${n.id}" ${on(n.id) ? 'aria-current="page"' : ''}
        ${NEEDS_INDEX.has(n.id) && !S.hasIndex ? 'disabled title="Scan first"' : ''}>${ic(n.icon)}<span class="l">${esc(n.label)}</span>${n.id === 'media' && S.summary ? `<span class="c num">${fmt(S.summary.total)}</span>` : ''}</button>`).join('')
    + `</nav><div class="nav-foot">${ic('shield')}<span>Local only · never permanently deletes. Nothing leaves this computer.</span></div>`;
  if (typeof renderTabs === 'function') renderTabs();
}
function renderUser() { // Why: the OS user name is read locally and shown only here
  const name = (S.info && S.info.user) || '', first = name.split(/[\s.]+/)[0] || 'You';
  const initials = name.split(/[\s.]+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') || 'U';
  $('#user-chip').innerHTML = `<span class="avatar">${esc(initials)}</span><b>${esc(first)}</b>${DEMO ? ' <span class="badge b-demo">Demo</span>' : ''}`;
  if (DEMO && !$('#demo-strip')) {   // Why: the demo must never be mistaken for your real files (also on a phone, where the chip is small)
    const d = document.createElement('div'); d.id = 'demo-strip'; d.setAttribute('role', 'note');
    d.textContent = 'Demo mode, sample data only. Nothing on your computer is read. Install AuraSort to scan your own files.';
    $('#top').prepend(d);
  }
}

/* ---------------- feedback ---------------- */
function toast(m, kind = '', actions = '') {
  const t = $('#toast'); t.className = kind;
  t.innerHTML = ic(kind === 'err' ? 'alert' : kind === 'ok' ? 'check' : 'info') + `<span>${esc(m)}</span>` + (actions ? `<span class="t-acts">${actions}<button class="t-x" data-a="toast-close" aria-label="Close">${ic('x')}</button></span>` : '');
  t.hidden = false; clearTimeout(toast.h);
  const hide = () => { toast.h = setTimeout(() => t.hidden = true, actions ? TOAST_ACTION_MS : kind === 'err' ? TOAST_ERR_MS : TOAST_MS) };
  t.onmouseenter = () => clearTimeout(toast.h); t.onmouseleave = hide; hide();
}
ACT['toast-close'] = () => { $('#toast').hidden = true };

/* ---------------- errors: a short human message, "Try again", and a safe "Copy details" report ---------------- */
function toastError(e, { retry = null, what = '', paths = [] } = {}) { // Why: never a bare exception name; always a way forward
  if (e && (e.code === 'pin_cancelled' || e.code === 'locked' || e.code === 'pin_not_set')) return;   // you cancelled, or the unlock screen is already showing
  ERR.last = { e, what, paths };
  ERR.retry = retry;
  toast(friendly(e) + (e && e.hint && !ERROR_TEXT[e.code] ? ' ' + e.hint : ''), 'err',
    `${retry ? '<button class="btn sm" data-a="err-retry">Try again</button>' : ''}<button class="btn sm ghost" data-a="err-details">Copy details</button>`);
}
const ERR = { last: null, retry: null };
function errorReport({ e, what = '', paths = [] }, withPaths = false) { // Why: what a bug report needs, nothing from your disk unless you tick it
  const f = (e && e.failure) || {}, info = S.info || {};
  const lines = [`${APP.name} error report`, `App version: ${info.version || '?'}`, `System: ${info.os_name || info.os || '?'}${info.python ? ', Python ' + info.python : ''}`,
    `Browser: ${(navigator.userAgent.match(/(Edg|Chrome|Firefox|Version)\/[\d.]+/g) || ['?']).join(' ')}`,
    `What: ${what || f.kind || 'request'}${f.step || (e && e.step) ? ' (step: ' + (f.step || e.step) + ')' : ''}`,
    `Error: ${f.type || (e && e.status ? 'HTTP ' + e.status : 'Error')}${f.code || (e && e.code) ? ', code ' + (f.code || e.code) : ''}`,
    `Message: ${f.message || (e && e.message) || ''}`, `Time: ${new Date().toISOString()}`, `Log file: ${info.log_file || '~/.aurasort/logs/server.log'}`];
  if (withPaths && paths.length) lines.push('Folders chosen:', ...paths.map(p => '  ' + p));
  return lines.join('\n');
}
function showErrorDetails(ctx) {
  const box = modal(`<h2>Error details</h2><p class="mut">Paste this into a GitHub issue or a message. It has no file names or folders from your PC unless you tick the box. Full details are in the log file shown below.</p>
    <pre class="pv-text err-report" id="err-text"></pre>
    ${ctx.paths && ctx.paths.length ? '<label class="row" data-css="margin-top:10px"><input type="checkbox" id="err-paths"> <span>Include the folders I chose</span></label>' : ''}
    <div class="row" data-css="margin-top:16px;justify-content:flex-end"><button class="btn ghost" data-a="err-close">Close</button><button class="btn pri" data-a="err-copy">Copy details</button></div>`, 'err-box');
  applyCss(box);
  const fill = () => { $('#err-text').textContent = errorReport(ctx, !!($('#err-paths') && $('#err-paths').checked)) };
  fill(); const c = $('#err-paths'); if (c) c.onchange = fill;
}
ACT['err-retry'] = () => { $('#toast').hidden = true; const r = ERR.retry; ERR.retry = null; if (r) r() };
ACT['err-details'] = () => { $('#toast').hidden = true; if (ERR.last) showErrorDetails(ERR.last) };
ACT['err-close'] = () => closeModal();
ACT['err-copy'] = async () => { const ok = await copyText($('#err-text').textContent); toast(ok ? 'Details copied.' : 'Select the text and copy it with Ctrl+C.', ok ? 'ok' : '') };
function loadNotes() { try { S.notes = JSON.parse(localStorage.getItem(NOTES_KEY) || '[]').slice(0, NOTES_MAX) } catch (e) { S.notes = [] } renderBell() }
function notify(title, body = '', icon = 'bell') { // Why: the bell lists events such as "Scan finished"
  S.notes.unshift({ title, body, icon, time: Date.now() / 1000, unread: true }); S.notes = S.notes.slice(0, NOTES_MAX);
  try { localStorage.setItem(NOTES_KEY, JSON.stringify(S.notes)) } catch (e) { /* in-memory only */ }
  renderBell();
}
function renderBell() { const d = $('#bell .dot'); if (d) d.hidden = !S.notes.some(n => n.unread) }
function toggleDrawer() {
  const d = $('#drawer');
  if (!d.hidden) { d.hidden = true; return }
  d.innerHTML = `<div class="card-h"><h3>Notifications</h3>${S.notes.length ? '<button class="link" data-a="notes-clear">Clear</button>' : ''}</div>`
    + (S.notes.length ? S.notes.map(n => `<div class="note-item">${ic(n.icon)}<span><b>${esc(n.title)}</b><small>${esc(n.body)} · ${ago(n.time)}</small></span></div>`).join('')
      : '<p class="mut">No notifications yet. Finished scans and moves show up here.</p>');
  d.hidden = false;
  S.notes.forEach(n => n.unread = false); try { localStorage.setItem(NOTES_KEY, JSON.stringify(S.notes)) } catch (e) { /* ignore */ }
  renderBell();
}

/* ---------------- modal & confirm ---------------- */
function modal(html, cls = '') {
  const m = $('#modal'); m.innerHTML = `<div class="card mbox ${cls}" role="dialog" aria-modal="true">${html}</div>`; m.hidden = false;
  setTimeout(() => { const f = m.querySelector('[autofocus], input:not([type=checkbox]), .btn.pri, button:not(:disabled)'); f && f.focus() }, 30);
  return m.firstElementChild;
}
function pathFallback(r) { // Why: no file manager to open (Android/Termux): show the path with Copy, or AuraSort's own trash
  if (!r || r.ok !== false) return false;
  if (r.fallback === 'apptrash') { go('settings'); setTimeout(() => { const s = $('#set-apptrash'); if (s) { s.hidden = false; s.scrollIntoView() } }, 300); return true }
  modal(`<h2>Where it is</h2><p class="mut">This system cannot open a file manager from ${esc(APP.name)}. The full path:</p>
    <pre class="path-box">${esc(r.path || '')}</pre><div class="row" data-css="justify-content:flex-end;margin-top:12px"><button class="btn ghost" data-a="cf-no">Close</button><button class="btn pri" data-a="path-copy">${ic('copy')} Copy path</button></div>`);
  ACT['cf-no'] = () => closeModal();
  ACT['path-copy'] = async () => { await copyText(r.path || ''); toast('Path copied', 'ok') };
  return true;
}
function closeModal() { const m = $('#modal'); m.hidden = true; m.innerHTML = ''; if (closeModal.done) { const d = closeModal.done; closeModal.done = null; d(false) } }
function confirmDialog({ title, body, ok = 'Continue', danger = false, check = '', typed = '' }) { // Why: every risky step asks first (with an optional "I understand" tick)
  return new Promise(res => {
    closeModal.done = res;
    modal(`<h2>${esc(title)}</h2><div class="mut">${body}</div>${check ? `<label class="row" data-css="margin-top:14px"><input type="checkbox" id="cf-check"> <span>${esc(check)}</span></label>` : ''}${typed ? `<label class="ad-typed">Type <b>${esc(typed)}</b> to confirm<input type="text" id="cf-typed" autocomplete="off" spellcheck="false" aria-label="Type ${esc(typed)} to confirm"></label>` : ''}
      <div class="row" data-css="margin-top:20px;justify-content:flex-end"><button class="btn ghost" data-a="cf-no">Cancel</button><button class="btn ${danger ? 'danger' : 'pri'}" data-a="cf-yes" ${check || typed ? 'disabled id="cf-ok"' : ''}>${esc(ok)}</button></div>`);
    const c = $('#cf-check'), ty = $('#cf-typed'), okNow = () => (!c || c.checked) && (!ty || ty.value.trim() === typed);
    if (c) c.onchange = () => { $('#cf-ok').disabled = !okNow() };
    if (ty) { ty.oninput = () => { $('#cf-ok').disabled = !okNow() }; setTimeout(() => ty.focus(), 30) }
    ACT['cf-yes'] = () => { closeModal.done = null; closeModal(); res(true) };
    ACT['cf-no'] = () => closeModal();
  });
}

/* ---------------- tooltip (category segments & tiles) ---------------- */
function tipHtml(key) {
  const x = S.summary && S.summary.by_cat[key]; if (!x) return '';
  return `<b>${esc(key)}</b><div class="tr"><span>Size</span><span class="num">${sz(x.size)}</span></div><div class="tr"><span>Files</span><span class="num">${fmt(x.n)}</span></div>
    <div class="tr"><span>Share of scanned</span><span class="num">${pctTxt(share(x.size, S.summary.total_size))}</span></div>${VIEW_ONLY.has(key) ? '<div class="tr"><span>View-only</span><span>yes</span></div>' : `<div class="tr"><span>Ready to sort</span><span class="num">${fmt(x.ready)}</span></div>`}`;
}
function tipText(s) { // Why: simple "title|line|line" tooltips (calendar days, timeline months)
  const [head, ...rest] = String(s).split('|');
  return `<b>${esc(head)}</b>` + rest.map(l => `<div class="mut">${esc(l)}</div>`).join('');
}
function showTip(el, x, y) {
  const t = $('#tip'), h = el.dataset.tipt != null ? tipText(el.dataset.tipt) : tipHtml(el.dataset.tip); if (!h) return;
  t.innerHTML = h; t.hidden = false;
  if (x == null) { const r = el.getBoundingClientRect(); x = r.left + r.width / 2; y = r.bottom }
  const w = t.offsetWidth, hh = t.offsetHeight;
  t.style.left = clamp(x - w / 2, 8, innerWidth - w - 8) + 'px'; t.style.top = (y + 14 + hh > innerHeight ? y - hh - 14 : y + 14) + 'px';
}

/* ---------------- small builders ---------------- */
const empty = (icon, title, text, actions = '') => `<div class="card empty"><div class="e-ic">${ic(icon)}</div><h3>${title}</h3><p>${text}</p>${actions ? `<div class="row">${actions}</div>` : ''}</div>`;
const skeletonRows = n => `<div class="card">${'<div class="skel row"></div>'.repeat(n)}</div>`;
function kindBadge(r) { // Why: why a file is (or isn't) ready to sort, at a glance
  if (r.kind === 'project') return `<span class="badge b-proj">${ic('lock')} project</span>`;
  if (r.kind === 'assets') return '<span class="badge b-asset">assets</span>';
  if (r.kind === 'sorted') return '<span class="badge b-sorted">sorted</span>';
  return '';
}
const voBadge = r => r.viewonly ? '<span class="badge b-vo" title="Listed and searchable; not moved or deleted unless you opt in">view-only</span>' : '';
function fileIcon(r, big = false) { // Why: images get a lazy real thumbnail; everything else a coloured type icon
  const c = CAT[r.cat] || CAT.Other;
  const src = DEMO ? API.thumb(r.id) : r.thumb, img = r.cat === 'Images' && src ? `<img alt="" data-fallback ${DEMO ? 'src' : 'data-src'}="${esc(src)}">` : '';
  return `<span class="ficon" data-css="--c:${c.c}">${ic(c.ic)}${img}</span>`;
}

/* ---------------- file lists: every file, its full folder, a clear size ---------------- */
const fileManager = () => S.info && S.info.os === 'mac' ? 'Finder' : S.info && S.info.os === 'linux' ? 'the file manager' : 'Explorer';
function selBox(r) { return `<input type="checkbox" data-a="sel" data-id="${r.id}" ${S.sel.has(r.id) ? 'checked' : ''} aria-label="Select ${esc(r.name)}">` }
function pageBox(rows, label) { // Why: one tick selects (or clears) every file in this list; "some" shows as indeterminate
  const n = rows.filter(r => S.sel.has(r.id)).length;
  return `<input type="checkbox" data-a="selpage" ${rows.length && n === rows.length ? 'checked' : ''} ${n && n < rows.length ? 'data-mixed' : ''} aria-label="${esc(label)}">`;
}
function fileTable(rows, { q = '', act = true, sel = true } = {}) {
  const max = Math.max(1, ...rows.map(r => r.size));
  return `<div class="tbl-wrap"><table class="ftable"><thead><tr>${sel ? `<th class="c-sel">${pageBox(rows, 'Select every file in this list')}</th>` : ''}<th class="c-name">Name</th><th class="c-size">Size</th><th class="c-date">Modified</th><th class="c-folder">Folder</th>${act ? '<th class="c-act"><span class="sr">Actions</span></th>' : ''}</tr></thead><tbody>`
    + rows.map(r => `<tr class="${r.included ? '' : 'ex'} ${S.sel.has(r.id) ? 'sel' : ''}" data-id="${r.id}">
      ${sel ? `<td class="c-sel">${selBox(r)}</td>` : ''}
      <td class="c-name"><div class="fname">${fileIcon(r)}<span class="fn-text"><button class="fn-open" data-a="preview" data-id="${r.id}" title="Preview ${esc(r.name)}"><b>${q ? hlHtml(r.name, q) : esc(r.name)}</b></button>
        <small><span class="ext">${esc(r.ext ? '.' + r.ext : 'no ext')}</span><span>${esc(r.cat)}</span>${kindBadge(r)}${voBadge(r)}</small></span></div></td>
      <td class="c-size">${sizeHtml(r.size)}<i class="sbar"><i data-css="width:${Math.max(2, pct(r.size, max)).toFixed(1)}%"></i></i></td>
      <td class="c-date num" title="${esc(dtt(r.mtime))}">${dt(r.mtime)}</td>
      <td class="c-folder">${pathHtml(r.path)}</td>
      ${act ? `<td class="c-act"><button class="btn sm ghost" data-a="reveal" data-id="${r.id}" title="Show in ${fileManager()}">${ic('external')} Open location</button></td>` : ''}</tr>`).join('')
    + '</tbody></table></div>';
}
function fileGrid(rows) {
  return `<div class="tiles">` + rows.map((r, i) => { const c = CAT[r.cat] || CAT.Other;
    const src = DEMO ? API.thumb(r.id) : r.thumb;
    return `<figure class="tile ${S.sel.has(r.id) ? 'sel' : ''}" data-id="${r.id}" data-css="animation-delay:${Math.min(i, 24) * 14}ms;--c:${c.c}"><label class="tsel" title="Select">${selBox(r)}</label>
      <button class="thumb" data-a="preview" data-id="${r.id}" aria-label="Preview ${esc(r.name)}">${ic(c.ic)}${r.cat === 'Images' && src ? `<img alt="" data-fallback ${DEMO ? 'src' : 'data-src'}="${esc(src)}">` : ''}<span class="size-pill num" title="${bytesTxt(r.size)}">${sz(r.size)}</span></button>
      <figcaption><b title="${esc(r.name)}">${esc(r.name)}</b><span class="mut num">${sizeHtml(r.size)} · ${dt(r.mtime)}</span><span class="fpath" title="${esc(r.path)}">${esc(base(r.path))}</span>
      <span class="row">${kindBadge(r)}${voBadge(r)}</span><button class="link" data-a="reveal" data-id="${r.id}">Open location</button></figcaption></figure>` }).join('') + '</div>';
}
function pageNums(page, pages) { // Why: 1 … 4 5 [6] 7 8 … 20
  const out = [], add = n => { if (!out.includes(n)) out.push(n) };
  add(1); for (let n = Math.max(2, page - 2); n <= Math.min(pages - 1, page + 2); n++) add(n); if (pages > 1) add(pages);
  return out.flatMap((n, i) => i && n - out[i - 1] > 1 ? ['…', n] : [n]);
}
function pagerHtml(p, act = 'pg') { // Why: 100 per page with Prev/Next, page numbers and "Jump to page"
  const first = p.total ? (p.page - 1) * p.per + 1 : 0, last = Math.min(p.page * p.per, p.total);
  const count = `<div class="count">Showing <b class="num">${fmt(first)}–${fmt(last)}</b> of <b class="num">${fmt(p.total)}</b> files${p.size != null ? ` · ${sizeHtml(p.size)} in total` : ''}</div>`;
  if (p.pages <= 1) return `<nav class="pager">${count}</nav>`;
  return `<nav class="pager" aria-label="Pages"><button class="btn sm ghost" data-a="${act}" data-p="${p.page - 1}" ${p.page <= 1 ? 'disabled' : ''}>${ic('chevl')} Prev</button>`
    + pageNums(p.page, p.pages).map(n => n === '…' ? '<span class="gap">…</span>' : `<button class="pg ${n === p.page ? 'on' : ''}" data-a="${act}" data-p="${n}" ${n === p.page ? 'aria-current="page"' : ''}>${n}</button>`).join('')
    + `<button class="btn sm ghost" data-a="${act}" data-p="${p.page + 1}" ${p.page >= p.pages ? 'disabled' : ''}>Next ${ic('chevr')}</button>
      <label class="jump">Jump to <input type="number" min="1" max="${p.pages}" placeholder="${p.page}" data-c="jump" data-act="${act}" aria-label="Jump to page"> of ${fmt(p.pages)}</label>${count}</nav>`;
}
function fmtChips(extFacet, selected, act = 'fmt', limit = 18) { // Why: multi-select extension chips with live counts
  const sel = selected, have = new Map(extFacet);
  for (const x of sel) if (!have.has(x)) have.set(x, 0);
  const all = [...have].sort((a, b) => (sel.has(b[0]) - sel.has(a[0])) || b[1] - a[1]);
  if (!all.length) return '';
  const shown = S.fmtAll ? all : all.slice(0, limit);
  return `<span class="fmt-l">Formats</span>` + shown.map(([e, n]) => `<button class="fchip ${sel.has(e) ? 'on' : ''}" data-a="${act}" data-x="${esc(e)}" aria-pressed="${sel.has(e)}">.${esc(e || 'none')} <span class="num">${fmt(n)}</span></button>`).join('')
    + (all.length > limit ? `<button class="link" data-a="fmtall">${S.fmtAll ? 'Fewer' : `+${all.length - limit} more`}</button>` : '')
    + (sel.size ? `<button class="link" data-a="${act}-clear">Clear formats</button>` : '');
}
function catTabs(facetCat, active, act = 'tab') { // Why: all 14 categories always visible; empty ones dimmed, never hidden
  const total = Object.values(facetCat).reduce((a, c) => ({ n: a.n + c.n, size: a.size + c.size }), { n: 0, size: 0 });
  const tab = (key, label, icon, color, x) => `<button class="ctab ${active === key ? 'on' : ''} ${x.n ? '' : 'zero'}" data-a="${act}" data-k="${esc(key)}" data-css="--c:${color}" aria-pressed="${active === key}">${ic(icon)}<span><b>${esc(label)}</b><small class="num">${fmt(x.n)} · ${sz(x.size)}</small></span></button>`;
  return `<div class="cat-tabs" role="tablist">${tab('', 'All files', 'files', ALL_FILES.c, total)}` + CATS.map(c => tab(c.key, c.key, c.ic, c.c, facetCat[c.key] || { n: 0, size: 0 })).join('') + '</div>';
}
function renderFilters() { // Why: "Active filters" row with an x per filter and "Clear all"
  const F = S.F, a = [];
  if (['media', 'search', 'large'].includes(S.view)) {
    if (S.view === 'search' && F.q.trim()) a.push(['q', 'Search', F.q.trim()]);
    if (F.type && S.view !== 'media') a.push(['type', 'Type', F.type]);
    F.formats.forEach(x => a.push(['format:' + x, 'Format', '.' + x]));
    if (F.dir) a.push(['folder', 'Folder', F.dirPath || F.folder]);
    else if (F.folder.trim()) a.push(['folder', 'Folder contains', F.folder.trim()]);
    if (F.date) a.push(['date', 'Date', dateLabel()]);
  }
  $('#filters').innerHTML = a.length ? '<span class="fl">Active filters</span>' + a.map(([k, n, l]) => `<span class="fchip-a"><span class="k">${esc(n)}</span><span class="v">${esc(l)}</span><button data-a="rmf" data-k="${esc(k)}" aria-label="Remove ${esc(n)} filter">${ic('x')}</button></span>`).join('')
    + (a.length > 1 ? '<button class="link" data-a="clearf">Clear all</button>' : '') : '';
}
function dateLabel() { // Why: readable active-filter chip for the date filter
  const F = S.F, f = { today: 'Today', yesterday: 'Yesterday', '7d': 'Last 7 days', '30d': 'Last 30 days', month: 'This month' }[F.date];
  const field = F.datefield && F.datefield !== 'modified' ? ` (${F.datefield})` : '';
  return (f || ({ on: `On ${F.from}`, between: `${F.from} → ${F.to}`, ym: `Month ${F.from}`, year: `Year ${F.from}` }[F.date] || F.date)) + field;
}

/* ---------------- virtual list (long folder / extension lists) ---------------- */
function virtualList(box, items, rowH, render, rowCls = '') { // Why: thousands of rows stay smooth: only visible rows exist in the DOM
  box.innerHTML = `<div class="vspace" data-css="height:${items.length * rowH}px;position:relative"></div>`;
  const space = box.firstElementChild;
  let last = '';
  const draw = () => {
    const top = box.scrollTop, h = box.clientHeight || 600, a = Math.max(0, Math.floor(top / rowH) - 8), b = Math.min(items.length, Math.ceil((top + h) / rowH) + 8);
    const key = a + ':' + b; if (key === last) return; last = key;
    space.innerHTML = items.slice(a, b).map((it, k) => `<div class="vrow ${rowCls}" data-css="top:${(a + k) * rowH}px;height:${rowH}px">${render(it, a + k)}</div>`).join('');
  };
  box.onscroll = () => requestAnimationFrame(draw);
  applyCss(box); draw();
  return { redraw: () => { last = ''; draw() } };
}
