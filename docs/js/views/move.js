/* AuraSort - Sort & move: settings, exact server-side preview (incl. free space before/after), confirm, then the move stage. */
'use strict';
const EST_RENAME_FILES_PER_S = 800, EST_COPY_BYTES_PER_S = 80 * 1024 * 1024;
function moveState() {
  if (!S.mv) S.mv = { dest: (S.settings && S.settings.dest) || (S.info && S.info.dest) || '', mode: 'move', flat: false, types: new Set(CATS.filter(c => !c.vo).map(c => c.key)), formats: new Set(), plan: null, disk: null, fmts: [] };
  return S.mv;
}
function viewMove(v) {
  const m = moveState(), s = S.summary;
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Sort &amp; move</p><h1>Preview, then sort safely</h1><p>Files from your ticked folders go into tidy sub-folders. Nothing moves until you confirm, every move is logged, and Undo puts everything back.</p></div>
      <div class="actions"><button class="btn ghost" data-a="nav" data-v="folders">${ic('folder')} Choose folders</button></div></div>
  <div class="grid g2" data-css="grid-template-columns:minmax(300px,.9fr) minmax(0,1.3fr);align-items:start">
    <section class="card"><h2>Settings</h2>
      <h3 data-css="margin:18px 0 8px">Destination folder</h3><div class="row" data-css="flex-wrap:nowrap"><input type="text" data-c="dest" value="${esc(m.dest)}" aria-label="Destination folder" data-css="flex:1"><button class="btn ghost" data-a="pick-dest">${ic('folder')} Browse…</button></div>
      <h3 data-css="margin:18px 0 8px">What to do</h3>
      ${[['move', 'Move', 'Keeps one copy. Undo is available.'], ['copy', 'Copy', 'Originals stay where they are. Needs free space.']].map(([k, l, d]) => `<label class="note" data-css="cursor:pointer;margin-bottom:8px;${m.mode === k ? 'border-color:var(--accent)' : ''}"><input type="radio" name="mvmode" data-c="mvmode" value="${k}" ${m.mode === k ? 'checked' : ''}><span><b>${l}</b><br><small class="mut">${d}</small></span></label>`).join('')}
      <h3 data-css="margin:18px 0 8px">Layout</h3><label class="row"><input type="checkbox" data-c="mvflat" ${m.flat ? 'checked' : ''}> One folder per type (no sub-folders like Images/Camera)</label>
      <h3 data-css="margin:18px 0 8px">Types to sort</h3>
      ${CATS.filter(c => !c.vo).map(c => `<label class="row" data-css="padding:5px 0"><input type="checkbox" data-c="mvtype" data-k="${esc(c.key)}" ${m.types.has(c.key) ? 'checked' : ''}><span data-css="color:${c.c}">${ic(c.ic)}</span> ${esc(c.key)} <small class="mut num">(${fmt(s.by_cat[c.key].ready)} ready · ${sz(s.by_cat[c.key].ready_size)})</small></label>`).join('')}
      <p class="mut" data-css="margin-top:10px">${ic('lock')} View-only types (installers, code, disk images, fonts, databases, logs, other) are never moved unless you opt in from Settings.</p>
      <h3 data-css="margin:18px 0 8px">Only these formats <small class="mut">(optional)</small></h3><div class="fmt-row" id="mvfmts"><span class="mut">Loading…</span></div></section>
    <div class="stack"><section class="card" id="mvprev"><div class="skel xl"></div>${'<div class="skel row"></div>'.repeat(4)}</section></div></div>`;
  loadPlan();
}
async function loadPlan() { // Why: the preview is computed by the server with the exact rules the move will use
  const m = moveState(), token = (loadPlan.n = (loadPlan.n || 0) + 1);
  try {
    const [plan, disk, f] = await Promise.all([API.plan({ dest: m.dest, types: [...m.types], formats: [...m.formats] }), API.disk(m.dest).catch(() => null), API.files({ scope: 'ready', per: 1 })]);
    if (token !== loadPlan.n || !$('#mvprev')) return;
    Object.assign(m, { plan, disk, fmts: f.facets.ext });
  } catch (e) { if ($('#mvprev')) $('#mvprev').innerHTML = empty('alert', 'Could not build the preview', esc(friendly(e))); return }
  $('#mvfmts').innerHTML = fmtChips(m.fmts, m.formats, 'mvfmt') || '<span class="mut">No files are ready to sort.</span>';
  drawPreview();
}
function predicted(m) { // Why: an honest time range (same-drive moves are renames; copies/cross-drive moves copy bytes)
  const p = m.plan, cross = m.mode === 'copy' ? p.size : p.cross_bytes;
  const secs = cross ? cross / EST_COPY_BYTES_PER_S + p.n / EST_RENAME_FILES_PER_S : p.n / EST_RENAME_FILES_PER_S;
  return [secs * .7, Math.max(1, secs * 1.6)];
}
function drawPreview() {
  const m = moveState(), p = m.plan, d = m.disk, sep = m.dest.includes('\\') ? '\\' : '/';
  const cross = m.mode === 'copy' ? p.size : p.cross_bytes, after = d ? d.free - cross : null;
  const bar = (label, free, warn) => `<div class="row" data-css="flex-wrap:nowrap;margin:6px 0"><span data-css="width:56px" class="mut">${label}</span><span class="meter ${warn ? 'warn' : ''}" data-css="flex:1"><i data-css="width:${pct(d.total - Math.max(0, free), d.total).toFixed(1)}%"></i></span><b class="num" data-css="width:120px;text-align:right">${sz(Math.max(0, free))} free</b></div>`;
  const pr = predicted(m);
  $('#mvprev').innerHTML = `<p class="eyebrow">Preview</p><h2>Nothing has moved yet</h2>
    <div class="kv" data-css="margin:16px 0"><div><small>Files</small><b class="num">${fmt(p.n)}</b></div><div><small>Size</small><b class="num">${sz(p.size)}</b></div><div><small>From folders</small><b class="num">${fmt(p.ndirs)}</b></div></div>
    ${m.formats.size ? `<div class="note" data-css="margin-bottom:14px">${ic('info')}<div>Only <b>${[...m.formats].map(x => '.' + esc(x)).join(', ')}</b> files will be ${m.mode === 'move' ? 'moved' : 'copied'}.</div></div>` : ''}
    ${d ? `<h3>Free space on the destination drive</h3>${bar('Before', d.free)}${bar('After', after, after < d.total * .05)}<p class="mut">${m.mode === 'copy' ? `Copying adds ${sz(p.size)} to this drive.` : p.cross_bytes ? `${sz(p.cross_bytes)} comes from another drive; that drive gains the same amount.` : 'Same drive: free space stays the same. Files are reorganised, never permanently deleted.'} Estimated time: ${durRange(pr[0], pr[1])}.</p>
      ${after < 0 ? `<div class="note err">${ic('alert')}<div>Not enough free space on the destination drive.</div></div>` : ''}` : ''}
    <div class="tbl-wrap" data-css="margin-top:14px"><table class="tbl"><thead><tr><th>New folder</th><th class="r">Files</th><th class="r">Size</th></tr></thead><tbody>
      ${CATS.filter(c => p.by_cat[c.key]).map(c => { const x = p.by_cat[c.key]; return `<tr><td><span data-css="color:${c.c}">${ic(c.ic)}</span> <span class="fpath">${esc(m.dest + sep)}<b>${esc(c.key)}</b></span>${m.flat ? '' : `<small class="mut" data-css="display:block">${Object.entries(x.subs).sort((a, b) => b[1] - a[1]).map(([k, n]) => `${esc(k)} (${fmt(n)})`).join(' · ')}</small>`}</td><td class="r num">${fmt(x.n)}</td><td class="r">${sizeHtml(x.size)}</td></tr>` }).join('') || '<tr><td colspan="3" class="mut">Nothing to sort with these settings. Tick some folders or types.</td></tr>'}
    </tbody></table></div>
    ${p.dirs.length ? `<details data-css="margin-top:12px"><summary data-css="cursor:pointer"><b>Where the files come from</b> <span class="mut">(${fmt(p.ndirs)} folders)</span></summary>${p.dirs.map(x => `<div class="row between" data-css="padding:6px 0;border-bottom:1px solid var(--hair)">${pathHtml(x.path)}<span class="num mut">${fmt(x.n)} files</span></div>`).join('')}</details>` : ''}
    <div class="note ok" data-css="margin:16px 0">${ic('shield')}<div>${fmt(S.summary.left_alone)} files in unticked, protected or view-only places will <b>not</b> be touched. <button class="link" data-a="nav" data-v="folders">Change folders</button></div></div>
    <button class="btn pri lg" data-a="mv-start" ${p.n && !(after < 0) ? '' : 'disabled'}>${ic('moveto')} ${m.mode === 'move' ? 'Move' : 'Copy'} ${fmt(p.n)} files…</button>`;
}
async function startMove() {
  const m = moveState(), p = m.plan;
  try { m.dest = (await API.saveSettings({ dest: m.dest })).dest || m.dest } catch (e) { /* the server validates the destination again */ }
  const ok = await confirmDialog({ title: `${m.mode === 'move' ? 'Move' : 'Copy'} ${fmt(p.n)} files?`, ok: `Yes, ${m.mode} them`,
    body: `<p><b class="num">${sz(p.size)}</b> from <b>${fmt(p.ndirs)}</b> folders → <span class="fpath">${esc(m.dest)}</span></p>${m.formats.size ? `<p>Only formats: <b>${[...m.formats].map(x => '.' + esc(x)).join(', ')}</b></p>` : ''}
      <p>Nothing is ever permanently deleted. ${m.mode === 'move' ? 'You can undo this from History.' : 'Originals stay where they are.'}</p>${p.project_files ? `<div class="note err">${ic('alert')}<div><b>${fmt(p.project_files)} files are inside project or asset folders you ticked.</b> Moving them can break those projects, apps or sites.</div></div>` : ''}`,
    check: p.project_files ? 'I understand the risk' : '' });
  if (!ok) return;
  try {
    const r = await API.execute({ dest: m.dest, mode: m.mode, flat: m.flat, types: [...m.types], formats: [...m.formats], allow_project: !!p.project_files });
    if (r.blocked) toast(`${fmt(r.blocked)} protected or view-only files were left out.`);
    Stage.open(p, r.job, { mode: m.mode, dest: m.dest, predicted: predicted(m) });
  } catch (e) { toast(friendly(e), 'err') }
}
CH.dest = t => { const m = moveState(); m.dest = t.value.trim(); clearTimeout(CH.dt); CH.dt = setTimeout(loadPlan, 450) };
CH.mvmode = t => { moveState().mode = t.value; render(false) };
CH.mvflat = t => { moveState().flat = t.checked; drawPreview() };
CH.mvtype = t => { const m = moveState(); t.checked ? m.types.add(t.dataset.k) : m.types.delete(t.dataset.k); loadPlan() };
ACT.mvfmt = t => { const m = moveState(), x = t.dataset.x; m.formats.has(x) ? m.formats.delete(x) : m.formats.add(x); loadPlan() };
ACT['mvfmt-clear'] = () => { moveState().formats = new Set(); loadPlan() };
ACT['pick-dest'] = () => Picker.open({ mode: 'dest', title: 'Choose the destination folder', onDone: paths => { if (paths[0]) { moveState().dest = paths[0]; render(false) } } });
ACT['mv-start'] = () => startMove();
ACT['st-done'] = () => Stage.close(Stage.back);
ACT['st-pause'] = t => API.jobControl(Stage.jid, t.dataset.p === 'true' ? 'resume' : 'pause').catch(e => toast(friendly(e), 'err'));
ACT['st-cancel'] = async () => { // Why: files already done stay done and verified; the file in progress is kept at its source
  if (!await confirmDialog({ title: 'Stop now?', ok: 'Stop', danger: true, body: '<p>Files already finished stay where they are (and can be undone from History). The file being copied right now stays at its original place; its partial copy is removed.</p>' })) return;
  API.jobControl(Stage.jid, 'cancel').catch(e => toast(friendly(e), 'err'));
};
ACT['st-open'] = () => API.revealJob(Stage.jid).then(r => r && r.demo && toast('Demo: this would open the destination folder.')).catch(e => toast(friendly(e), 'err'));
ACT['st-undo'] = async () => { if (!await confirmDialog({ title: 'Undo this move?', body: 'Every file goes back to where it came from (nothing is overwritten).', ok: 'Undo move' })) return;
  try { const r = await API.undo(Stage.jid); toast(`Restored ${fmt(r.restored)} files${r.missing ? `, ${fmt(r.missing)} missing` : ''}`, 'ok'); Stage.close('history') } catch (e) { toast(friendly(e), 'err') } };
