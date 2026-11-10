/* AuraSort - preview panel: images (zoom), video and audio (seekable), PDF, text; every detail of the file and safe Open buttons.
   Content comes through short-lived signed links; text is shown as plain text, never as HTML. */
'use strict';
const PV = { id: null, list: [], zoom: 'fit', back: null, data: null, seq: 0 };

function previewIds() { // Why: Previous/Next follow the order the files are shown in on screen
  const ids = [];
  for (const b of $$('#view [data-a=preview][data-id]')) { const id = +b.dataset.id; if (!ids.includes(id)) ids.push(id) }
  return ids;
}
async function openPreview(id) {
  const pv = $('#pv'), seq = ++PV.seq;
  if (pv.hidden) PV.back = document.activeElement;
  PV.id = id; PV.list = previewIds(); PV.zoom = 'fit'; PV.data = null;
  pauseMedia();
  pv.innerHTML = `<div class="pv-card" role="dialog" aria-modal="true" aria-label="File preview"><div class="pv-head"><div class="skel" data-css="height:22px;flex:1"></div>
    <button class="icon-btn" data-a="pv-close" aria-label="Close preview" title="Close (Esc)">${ic('x')}</button></div><div class="pv-media"><div class="skel" data-css="width:100%;height:100%;border-radius:0"></div></div></div>`;
  pv.hidden = false; document.body.classList.add('pv-open');
  let d;
  try { d = await API.preview(id) } catch (e) { if (seq === PV.seq && !pv.hidden) $('.pv-media', pv).innerHTML = `<div class="pv-none">${ic('alert')}<b>No preview</b><span>${esc(friendly(e))}</span></div>`; return }
  if (seq !== PV.seq || pv.hidden) return;
  PV.data = d; drawFilePreview(d);
}
function pauseMedia() { const m = $('#pv-av'); if (m) { try { m.pause() } catch (e) { /* ignore */ } } }
function closePreview() {
  const pv = $('#pv'); if (pv.hidden) return;
  pauseMedia(); PV.seq++; pv.hidden = true; pv.innerHTML = ''; document.body.classList.remove('pv-open');
  if (PV.back && document.contains(PV.back)) PV.back.focus();
}

function pvMedia(d) { // Why: one renderer per preview kind; anything the browser can't show gets a clear explanation
  const f = d.file, c = CAT[f.cat] || CAT.Other, big = `<span class="ficon xl" data-css="--c:${c.c}">${ic(c.ic)}${f.thumb ? `<img alt="" data-fallback src="${esc(f.thumb)}">` : ''}</span>`;
  if (d.kind === 'image') return `<div class="pv-img" id="pv-img"><img id="pv-im" alt="${esc(f.name)}" src="${esc(d.src)}"></div>
    <div class="pv-zoom" role="group" aria-label="Zoom"><button data-a="pv-zoom" data-z="out" aria-label="Zoom out">${ic('zoomout')}</button><button data-a="pv-zoom" data-z="fit" aria-label="Fit to panel">${ic('fit')}</button>
    <button data-a="pv-zoom" data-z="1" aria-label="Actual size">100%</button><button data-a="pv-zoom" data-z="in" aria-label="Zoom in">${ic('zoomin')}</button></div>`;
  if (d.kind === 'video') return `<video id="pv-av" controls preload="metadata" src="${esc(d.src)}"></video>`;
  if (d.kind === 'audio') return `<div class="pv-audio">${big}<audio id="pv-av" controls preload="metadata" src="${esc(d.src)}"></audio></div>`;
  if (d.kind === 'pdf') return `<iframe class="pv-pdf" title="${esc(f.name)}" src="${esc(d.src)}"></iframe>`;
  if (d.kind === 'text') return `<pre class="pv-text" tabindex="0">${esc(d.text)}</pre>${d.truncated ? `<p class="pv-cap">Showing the first ${sz(TEXT_PREVIEW_BYTES)} of ${sz(f.size)}</p>` : ''}`;
  if (d.kind === 'cloud') return `<div class="pv-none">${ic('network', 'xl-i')}<b>Online-only file</b><span>It lives in OneDrive or iCloud and is not downloaded. A preview would download it, so none is shown. Open file lets your cloud app fetch it.</span></div>`;
  if (d.kind === 'missing') return `<div class="pv-none">${ic('alert', 'xl-i')}<b>This file is no longer there</b><span>It was moved, renamed or deleted after the last scan. Scan again to refresh the list.</span></div>`;
  return `<div class="pv-none">${big}<b>No preview for ${esc(f.ext ? '.' + f.ext : 'this kind of')} files</b><span>${d.demo ? 'The demo shows previews for images only.' : d.open_block ? 'You can still see every detail below.' : 'Use Open file to view it in its own app.'}</span></div>`;
}
function drawFilePreview(d) {
  const f = d.file, i = PV.list.indexOf(f.id), on = S.sel.has(f.id);
  const created = d.created_supported === false ? '<span class="mut">Not recorded on this system</span>' : f.ctime ? esc(dtt(f.ctime)) : '—';
  const status = [kindBadge(f), voBadge(f), f.included ? '' : '<span class="badge b-mut">not ticked for sorting</span>'].join('') || '<span class="badge b-ok">ready to sort</span>';
  $('#pv').innerHTML = `<div class="pv-card" role="dialog" aria-modal="true" aria-label="Preview of ${esc(f.name)}">
    <div class="pv-head">${fileIcon(f)}<h2 title="${esc(f.name)}">${esc(f.name)}</h2><button class="icon-btn" data-a="pv-close" aria-label="Close preview" title="Close (Esc)">${ic('x')}</button></div>
    <div class="pv-media pv-${esc(d.kind)}">${pvMedia(d)}</div>
    <div class="pv-body">
      <div class="pv-actions">${d.open_block ? `<button class="btn pri" disabled title="${esc(d.open_block)}">${ic('lock')} Open file</button>` : `<button class="btn pri" data-a="pv-open" data-id="${f.id}">${ic('external')} Open file</button>`}
        <button class="btn ghost" data-a="reveal" data-id="${f.id}">${ic('folder')} Open location</button><button class="btn ghost" data-a="pv-copy">${ic('copy')} Copy path</button>
        <label class="btn ghost pv-selbtn"><input type="checkbox" data-a="pv-sel" ${on ? 'checked' : ''}> Select</label></div>
      ${d.kind !== 'missing' ? `<div class="pv-actions pv-more"><button class="btn sm ghost" data-a="pv-move" data-id="${f.id}">${ic('moveto')} Move to…</button><button class="btn sm ghost" data-a="pv-copyto" data-id="${f.id}">${ic('copy')} Copy to…</button>
        <button class="btn sm danger" data-a="pv-trash" data-id="${f.id}">${ic('trash')} ${esc(binName())}</button></div>` : ''}
      ${d.open_block ? `<div class="note warn">${ic('shield')}<span>${esc(d.open_block)}</span></div>` : ''}
      ${d.macro ? `<div class="note warn">${ic('alert')}<span>This Office file type can contain macros. ${esc(APP.name)} asks before opening it.</span></div>` : ''}
      <dl class="pv-det">
        <dt>Size</dt><dd>${sizeHtml(f.size)} <span class="mut num">(${bytesTxt(f.size)})</span></dd>
        <dt>Type</dt><dd>${esc(f.cat)}${f.sub ? ` <span class="mut">› ${esc(f.sub)}</span>` : ''} <span class="ext">${esc(f.ext ? '.' + f.ext : 'no extension')}</span></dd>
        <dt>Folder</dt><dd>${pathHtml(f.path)}</dd>
        <dt>Modified</dt><dd>${esc(dtt(f.mtime))}</dd>
        <dt>Created</dt><dd>${created}</dd>
        <dt>Last opened</dt><dd>${f.atime ? esc(dtt(f.atime)) : '—'}</dd>
        <dt>Status</dt><dd class="row">${status}</dd>
      </dl>
    </div>
    <div class="pv-nav"><button class="btn sm ghost" data-a="pv-step" data-d="-1" ${i <= 0 ? 'disabled' : ''}>${ic('chevl')} Previous</button>
      <span class="mut num">${i >= 0 ? `${fmt(i + 1)} of ${fmt(PV.list.length)} on this page` : ''}</span>
      <button class="btn sm ghost" data-a="pv-step" data-d="1" ${i < 0 || i >= PV.list.length - 1 ? 'disabled' : ''}>Next ${ic('chevr')}</button></div></div>`;
  const av = $('#pv-av');
  if (av) av.addEventListener('error', () => { av.outerHTML = `<div class="pv-none">${ic('video')}<b>This ${d.kind === 'audio' ? 'audio' : 'video'} format can't play in the browser</b><span>Use Open file to play it in its own app.</span></div>` }, { once: true });
  const im = $('#pv-im');
  if (im) { im.addEventListener('click', () => { PV.zoom = PV.zoom === 'fit' ? 1 : 'fit'; applyZoom() }); im.addEventListener('error', () => { $('#pv-img').innerHTML = `<div class="pv-none">${ic('image')}<b>This image can't be shown in the browser</b><span>Use Open file to view it.</span></div>` }, { once: true }) }
  const box = $('#pv-img');
  if (box) box.addEventListener('wheel', e => { if (!e.ctrlKey) return; e.preventDefault(); zoomBy(e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP) }, { passive: false });
  setTimeout(() => { const x = $('#pv [data-a=pv-close]'); x && x.focus() }, 30);
}

/* ---------------- zoom ---------------- */
function fitScale() { const im = $('#pv-im'), box = $('#pv-img'); return im && im.naturalWidth ? Math.min(1, box.clientWidth / im.naturalWidth, box.clientHeight / im.naturalHeight) : 1 }
function zoomBy(k) { const z = PV.zoom === 'fit' ? fitScale() : PV.zoom; PV.zoom = clamp(z * k, ZOOM_MIN, ZOOM_MAX); applyZoom() }
function applyZoom() { // Why: "fit" keeps the whole picture visible; any other zoom shows real pixels with scrolling
  const im = $('#pv-im'), box = $('#pv-img'); if (!im || !box) return;
  const fit = PV.zoom === 'fit';
  box.classList.toggle('zoomed', !fit);
  im.style.width = fit ? '' : Math.round(im.naturalWidth * PV.zoom) + 'px';
  im.style.maxWidth = fit ? '' : 'none'; im.style.maxHeight = fit ? '' : 'none';
}

/* ---------------- actions ---------------- */
ACT.preview = t => openPreview(+t.dataset.id);
ACT['pv-close'] = () => closePreview();
ACT['pv-step'] = t => { const i = PV.list.indexOf(PV.id) + Number(t.dataset.d); if (i >= 0 && i < PV.list.length) openPreview(PV.list[i]) };
ACT['pv-zoom'] = t => { const z = t.dataset.z; if (z === 'in') zoomBy(ZOOM_STEP); else if (z === 'out') zoomBy(1 / ZOOM_STEP); else { PV.zoom = z === 'fit' ? 'fit' : 1; applyZoom() } };
ACT['pv-copy'] = async () => { const f = PV.data && PV.data.file; if (f) toast(await copyText(joinPath(f.path, f.name)) ? 'Path copied' : 'Could not copy the path.', 'ok') };
ACT['pv-sel'] = t => { const f = PV.data && PV.data.file; if (!f) return; Sel.set(f.id, t.checked, f); Sel.paint() };
ACT['pv-open'] = async t => { // Why: macro-capable Office files get a warning first; programs never reach this button
  const id = +t.dataset.id, d = PV.data;
  if (d && d.macro && !await confirmDialog({ title: 'Open a file that can contain macros?', danger: true, ok: 'Open it',
    body: `<p><b>${esc(d.file.name)}</b> is an Office file type that can contain macros (small programs). Only open it if you trust where it came from.</p>` })) return;
  try { const r = await API.openFile(id, !!(d && d.macro)); toast(r && r.demo ? 'Demo: this would open the file in its own app.' : 'Opening it in its own app…', 'ok') }
  catch (e) { toastError(e) }
};
function previewKey(e) { // Why: Esc closes, arrows step through the files on the page, + / - / 0 zoom
  if ($('#pv').hidden || !$('#modal').hidden) return false;
  const tag = (document.activeElement && document.activeElement.tagName) || '';
  if (e.key === 'Escape') { closePreview(); return true }
  if (/^(VIDEO|AUDIO|INPUT|SELECT|TEXTAREA)$/.test(tag)) return false;
  if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { const b = $(`#pv [data-a=pv-step][data-d="${e.key === 'ArrowRight' ? 1 : -1}"]`); if (b && !b.disabled) b.click(); return true }
  if (e.key === '+' || e.key === '=') { zoomBy(ZOOM_STEP); return true }
  if (e.key === '-') { zoomBy(1 / ZOOM_STEP); return true }
  if (e.key === '0') { PV.zoom = 'fit'; applyZoom(); return true }
  return false;
}
