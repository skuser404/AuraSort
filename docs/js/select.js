/* AuraSort - selection: tick files across pages and filters, Shift-click ranges, "Select all N matching",
   and the sticky action bar. The selection is a Map id -> { size, cat, name } so totals are exact and instant. */
'use strict';
const SEL_ACTIONS = [];   // extra bar buttons registered by other modules: { html: n => '...' }

const Sel = {
  set(id, on, row) { // Why: one place adds/removes ids; sizes come from the row (or the server for "select all")
    if (!on) { S.sel.delete(id); return }
    const r = row || S.rowsById.get(id), old = S.sel.get(id);
    S.sel.set(id, r ? { size: r.size, cat: r.cat, name: r.name } : old || { size: 0 });
  },
  bytes() { let n = 0; for (const v of S.sel.values()) n += v.size || 0; return n },
  ids() { return [...S.sel.keys()] },
  clear() { S.sel.clear(); S.selAnchor = null; Sel.paint() },
  remember(rows, ctx) { // Why: list views tell the selection which rows are on screen and how to "select all matching"
    S.rowsById = new Map(rows.map(r => [r.id, r]));
    S.listCtx = ctx;
  },
  paint() { // Why: rows, tiles, "select page" boxes and the sticky bar always agree with the selection
    for (const b of $$('#view input[data-a=sel]')) {
      const on = S.sel.has(+b.dataset.id); b.checked = on;
      const host = b.closest('tr, .tile'); if (host) host.classList.toggle('sel', on);
    }
    for (const h of $$('#view input[data-a=selpage]')) {
      const boxes = $$('input[data-a=sel]', h.closest('table') || $('#view')), n = boxes.filter(b => b.checked).length;
      h.checked = !!boxes.length && n === boxes.length; h.indeterminate = n > 0 && n < boxes.length;
    }
    renderSelBar();
  }
};

function renderSelBar() {
  const bar = $('#selbar'), n = S.sel.size, show = n > 0 && LIST_VIEWS.has(S.view) && $('#stage').hidden;
  document.body.classList.toggle('has-selbar', show);
  if (!show) { bar.hidden = true; bar.innerHTML = ''; return }
  const c = S.listCtx, one = n === 1 ? Sel.ids()[0] : null;
  const more = c && c.kind !== 'none' && !c.allSelected && c.total > 0 && (c.total > n || $$('#view input[data-a=sel]').some(b => !b.checked));
  bar.innerHTML = `<span class="sb-count">${ic('checkall')}<span><b class="num">${fmt(n)}</b> ${n === 1 ? 'file' : 'files'} selected · ${sizeHtml(Sel.bytes())}</span></span>
    ${more ? `<button class="link sb-all" data-a="selall">Select all ${fmt(c.total)} matching</button>` : ''}
    <span class="sb-sp"></span>
    ${one != null ? `<button class="btn sm ghost" data-a="preview" data-id="${one}">${ic('eye')} Preview</button><button class="btn sm ghost" data-a="reveal" data-id="${one}">${ic('external')} Open location</button>` : ''}
    ${SEL_ACTIONS.map(a => a.html(n)).join('')}
    <button class="icon-btn sb-x" data-a="selclear" aria-label="Clear selection" title="Clear selection (Esc)">${ic('x')}</button>`;
  bar.hidden = false;
}

ACT.sel = (t, e) => { // Why: tick one file; Shift-click ticks (or clears) everything between it and the last one clicked
  const id = +t.dataset.id, on = t.checked;
  let targets = [t];
  if (e && e.shiftKey && S.selAnchor != null) {
    const boxes = $$('#view input[data-a=sel]'), a = boxes.findIndex(b => +b.dataset.id === S.selAnchor), z = boxes.indexOf(t);
    if (a >= 0 && z >= 0) targets = boxes.slice(Math.min(a, z), Math.max(a, z) + 1);
  }
  for (const b of targets) Sel.set(+b.dataset.id, on);
  S.selAnchor = id; Sel.paint();
};
ACT.selpage = t => { // Why: the header box selects every file of that list (all 100 on the page)
  const on = t.checked;
  for (const b of $$('input[data-a=sel]', t.closest('table') || $('#view'))) Sel.set(+b.dataset.id, on);
  Sel.paint();
};
ACT.selall = async t => { // Why: "Select all N matching" resolves the whole filter to ids (with sizes) in one request
  const c = S.listCtx; if (!c) return;
  t.disabled = true; t.textContent = 'Selecting…';
  try {
    let ids, sizes;
    if (c.kind === 'search') { const r = await Search.query(Object.assign({}, c.params, { allIds: true, page: 1 }), S.summary ? S.summary.version : 0); ids = r.all; sizes = r.allSizes }
    else { const r = await (c.kind === 'ai' ? API.aiIds : c.kind === 'cleanup' ? API.cleanupIds : API.fileIds)(Object.assign({}, c.params, { page: '', per: '' })); ids = r.ids; sizes = r.sizes }
    ids.forEach((id, i) => { if (!S.sel.has(id)) S.sel.set(id, { size: sizes[i] || 0 }) });
    c.allSelected = true;
    toast(`Selected all ${fmt(ids.length)} matching files`, 'ok');
  } catch (e) { toastError(e) }
  Sel.paint();
};
ACT.selclear = () => Sel.clear();
