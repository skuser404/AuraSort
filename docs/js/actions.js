/* AuraSort - acting on selected files: Move to…, Copy to…, Recycle Bin / Trash.
   Every action shows exactly what will happen first (from the server's preflight). Files in project/asset folders and
   view-only types are left alone unless ticked; 100+ files to the Recycle Bin need the number typed. Nothing is ever
   permanently deleted, and every action is logged in History. */
'use strict';
const TRASH_TYPED_MIN = 100;   // mirrors TRASH_TYPED_CONFIRM_MIN in core/config.py
const GUARDED = new Set(['project', 'assets']);
const LAYOUT_OPTS = [['here', 'Straight into this folder'], ['type', 'Into one folder per type', 'Images, Videos, PDFs…'], ['organized', 'Into type and sub-folders', 'Images/Camera, PDFs/Invoices…']];
const binName = () => S.info && (S.info.os === 'mac' || S.info.os === 'linux') ? 'Trash' : 'Recycle Bin';
const filesWord = n => n === 1 ? 'file' : 'files';

function splitSelection(st, allowProject, allowVo) { // Why: the client shows the same split the server will apply
  const optin = new Set(st.optin || []), out = { keep: 0, keepSize: 0, left: 0 };
  for (const [cat, kind, , n, size] of st.groups) {
    const blocked = (GUARDED.has(kind) && !allowProject) || (VIEW_ONLY.has(cat) && !optin.has(cat) && !allowVo.has(cat));
    if (blocked) out.left += n; else { out.keep += n; out.keepSize += size }
  }
  return out;
}
function actionDialog(kind, ids, dest, st, disk) { // kind: move | copy | trash. Resolves to the options, or null if cancelled.
  const guarded = st.groups.filter(g => GUARDED.has(g[1])).reduce((a, g) => a + g[3], 0);
  const vo = {}; for (const [cat, , , n] of st.groups) if (VIEW_ONLY.has(cat) && !(st.optin || []).includes(cat)) vo[cat] = (vo[cat] || 0) + n;
  const byCat = {}; for (const [cat, , , n, s] of st.groups) { const c = byCat[cat] || (byCat[cat] = { n: 0, size: 0 }); c.n += n; c.size += s }
  const typed = kind === 'trash' && ids.length >= TRASH_TYPED_MIN, verb = { move: 'Move', copy: 'Copy', trash: `Move to the ${binName()}` }[kind];
  return new Promise(res => {
    closeModal.done = () => res(null);
    const box = modal(`<p class="eyebrow">${kind === 'trash' ? esc(binName()) : kind === 'move' ? 'Move' : 'Copy'}</p><h2>${kind === 'trash' ? `Send ${fmt(st.n)} ${filesWord(st.n)} to the ${esc(binName())}?` : `${esc(verb)} ${fmt(st.n)} ${filesWord(st.n)}?`}</h2>
      <p class="ad-route"><b class="num">${sz(st.size)}</b> <span class="mut">→</span> ${kind === 'trash' ? `<b>${esc(binName())}</b>` : `<span class="fpath">${esc(dest)}</span>`}</p>
      <div class="catcount">${CATS.filter(c => byCat[c.key]).map(c => `<span data-css="--c:${c.c}">${ic(c.ic)} ${esc(c.key)} <b class="num">${fmt(byCat[c.key].n)}</b></span>`).join('')}</div>
      ${kind !== 'trash' ? `<h3 data-css="margin:18px 0 8px">Where inside that folder</h3>${LAYOUT_OPTS.map(([k, l, d], i) => `<label class="ad-opt"><input type="radio" name="ad-layout" value="${k}" ${i === 0 ? 'checked' : ''}><span><b>${l}</b>${d ? ` <small class="mut">${d}</small>` : ''}</span></label>`).join('')}` : ''}
      ${kind !== 'trash' ? `<h3 data-css="margin:16px 0 8px">Checking copies between drives</h3>
        <label class="ad-opt"><input type="radio" name="ad-verify" value="full" checked><span><b>Check every byte</b> <small class="mut">safest; each copy is read back and compared</small></span></label>
        <label class="ad-opt"><input type="radio" name="ad-verify" value="fast"><span><b>Fast check</b> <small class="mut">size and sampled blocks, for very large jobs</small></span></label>` : ''}
      <div class="stack ad-notes">
        ${st.missing ? `<div class="note warn">${ic('alert')}<div><b>${fmt(st.missing)}</b> selected ${filesWord(st.missing)} are no longer in the index and will be skipped.</div></div>` : ''}
        ${guarded ? `<div class="note err">${ic('lock')}<div><b>${fmt(guarded)} ${filesWord(guarded)} are inside project or asset folders.</b> Changing them can break those projects, apps or sites, so they are left where they are.
          <label class="row" data-css="margin-top:8px"><input type="checkbox" id="ad-proj"> <span>Include them anyway (I understand the risk)</span></label></div></div>` : ''}
        ${Object.keys(vo).length ? `<div class="note warn">${ic('eye')}<div><b>View-only types are left alone</b> unless you include them:${Object.entries(vo).map(([c, n]) => `<label class="row" data-css="margin-top:6px"><input type="checkbox" data-vo="${esc(c)}"> <span>Include ${esc(c)} (${fmt(n)})</span></label>`).join('')}</div></div>` : ''}
        ${kind === 'trash' && st.no_bin ? `<div class="note warn">${ic('alert')}<div><b>${fmt(st.no_bin)} ${filesWord(st.no_bin)}</b> are on a drive without a ${esc(binName())}, so they will be skipped. ${esc(APP.name)} never deletes permanently.</div></div>` : ''}
        ${kind === 'trash' ? `<div class="note">${ic('shield')}<div>Files stay in the ${esc(binName())} until you empty it, so you can restore them. ${esc(APP.name)} never deletes permanently.</div></div>`
          : kind === 'move' ? `<div class="note ok">${ic('undo')}<div>If a file with the same name is already there, you choose next: skip it, keep both, or replace. Nothing is overwritten silently, and Undo in History puts every file back.</div></div>`
          : `<div class="note">${ic('info')}<div>The originals stay where they are.${disk ? ` Free on the destination drive: <b class="num">${sz(disk.free)}</b>.` : ''}</div></div>`}
      </div>
      ${typed ? `<label class="ad-typed">To confirm, type <b class="num">${ids.length}</b><input type="text" id="ad-count" inputmode="numeric" autocomplete="off" aria-label="Type ${ids.length} to confirm"></label>` : ''}
      <p class="ad-sum" id="ad-sum"></p>
      <div class="row" data-css="justify-content:flex-end"><button class="btn ghost" data-a="ad-no">Cancel</button><button class="btn ${kind === 'trash' ? 'danger-solid' : 'pri'}" data-a="ad-ok" id="ad-ok" disabled></button></div>`, 'adlg');
    const read = () => ({ allowProject: !!($('#ad-proj') && $('#ad-proj').checked), allowVo: new Set($$('[data-vo]', box).filter(c => c.checked).map(c => c.dataset.vo)) });
    const update = () => {
      const o = read(), sp = splitSelection(st, o.allowProject, o.allowVo), ok = $('#ad-ok');
      const noRoom = kind === 'copy' && disk && disk.free < sp.keepSize, typedOk = !typed || ($('#ad-count').value.trim() === String(ids.length));
      $('#ad-sum').innerHTML = sp.keep ? `${kind === 'trash' ? 'Will move' : kind === 'move' ? 'Will move' : 'Will copy'} <b class="num">${fmt(sp.keep)}</b> ${filesWord(sp.keep)} (<span class="num">${sz(sp.keepSize)}</span>)${sp.left ? ` · <b class="num">${fmt(sp.left)}</b> left where they are` : ''}${noRoom ? ' · <b class="bad">not enough free space</b>' : ''}`
        : 'Nothing to do: every selected file is protected or view-only. Tick “Include” above to change that.';
      ok.disabled = !sp.keep || noRoom || !typedOk;
      ok.innerHTML = `${ic(kind === 'trash' ? 'trash' : kind === 'move' ? 'moveto' : 'copy')} ${kind === 'trash' ? `Send ${fmt(sp.keep)} ${filesWord(sp.keep)} to the ${esc(binName())}` : `${esc(verb)} ${fmt(sp.keep)} ${filesWord(sp.keep)}`}`;
    };
    box.addEventListener('change', update); box.addEventListener('input', update); update();
    ACT['ad-no'] = () => closeModal();
    ACT['ad-ok'] = () => {
      const o = read(), layout = ($('input[name=ad-layout]:checked', box) || {}).value || 'here';
      const verify = ($('input[name=ad-verify]:checked', box) || {}).value || 'full';
      const out = { allow_project: o.allowProject, allow_viewonly: [...o.allowVo], layout, verify, confirm_count: typed ? $('#ad-count').value.trim() : undefined };
      closeModal.done = null; closeModal(); res(out);
    };
  });
}

/* ---------------- "a file with this name already exists" ---------------- */
const CLASH_LABEL = { skip: 'Skip', keep: 'Keep both', replace: 'Replace' };
async function resolveConflicts(body) { // Why: never overwrite silently: show every clash side by side and let you choose. Resolves to the
  // choice ({action, skip_identical, per}), {} when there is no clash, or null if you cancelled.
  const keys = ['ids', 'dest', 'mode', 'layout', 'flat', 'types', 'formats', 'kind', 'allow_project', 'allow_viewonly'];
  let c; try { c = await API.conflicts(Object.fromEntries(keys.filter(k => body[k] !== undefined).map(k => [k, body[k]]))) } catch (e) { toastError(e); return null }
  if (!c.total) return {};
  const per = {};
  return new Promise(res => {
    closeModal.done = () => res(null);
    const row = r => { const d = r.dst, newer = d && r.src.mtime > d.mtime ? 'src' : d && d.mtime > r.src.mtime ? 'dst' : '';
      return `<tr data-fid="${r.fid}"><td><b title="${esc(r.target)}">${esc(r.name)}</b>${r.identical ? ' <span class="badge b-ok">identical content</span>' : ''}${r.within_selection ? ' <span class="badge b-mut">twice in your selection</span>' : ''}${d && d.readonly ? ' <span class="badge b-asset">read-only</span>' : ''}</td>
        <td class="r">${sizeHtml(r.src.size)}<small class="mut" data-css="display:block">${esc(dt(r.src.mtime))}${newer === 'src' ? ' · newer' : ''}</small></td>
        <td class="r">${d ? `${sizeHtml(d.size)}<small class="mut" data-css="display:block">${esc(dt(d.mtime))}${newer === 'dst' ? ' · newer' : ''}</small>` : '<span class="mut">another file in this batch</span>'}</td>
        <td><select data-c="clash-one" data-fid="${r.fid}" aria-label="What to do with ${esc(r.name)}"><option value="">As chosen below</option>${Object.entries(CLASH_LABEL).filter(([k]) => d || k === 'keep').map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select></td></tr>`; };
    modal(`<p class="eyebrow">Name clashes</p><h2>${fmt(c.total)} ${c.total === 1 ? 'file already exists' : 'files already exist'} in this folder</h2>
      <p class="mut">${c.identical ? `${fmt(c.identical)} of them ${c.identical === 1 ? 'has' : 'have'} identical content. ` : ''}Nothing is overwritten unless you choose Replace, and then the existing file is kept in the ${esc(APP.name)} trash so Undo can put it back.</p>
      <div class="tbl-wrap clash-tbl"><table class="tbl"><thead><tr><th>Name</th><th class="r">Coming in</th><th class="r">Already there</th><th>Do</th></tr></thead><tbody>${c.rows.map(row).join('')}</tbody></table></div>
      ${c.more ? `<p class="mut">…and ${fmt(c.more)} more, handled by the choice below.</p>` : ''}
      <label class="row" data-css="margin:14px 0 6px"><input type="checkbox" id="clash-same" checked> <span><b>Skip identical files</b> (recommended)</span></label>
      <div class="seg" role="radiogroup" aria-label="For all other clashes">${Object.entries(CLASH_LABEL).map(([k, l]) => `<button role="radio" data-a="clash-all" data-k="${k}" class="${k === 'keep' ? 'on' : ''}" aria-checked="${k === 'keep'}">${l}</button>`).join('')}</div>
      <p class="mut" id="clash-help" data-css="margin-top:8px"></p>
      <div class="row" data-css="justify-content:flex-end;margin-top:16px"><button class="btn ghost" data-a="clash-no">Cancel</button><button class="btn pri" data-a="clash-ok">Continue</button></div>`, 'adlg');
    let all = 'keep';
    const help = { skip: 'Files that already exist are left where they are and not moved.', keep: 'The incoming file gets a new name, like “photo (1).jpg”.', replace: 'The existing file goes to the AuraSort trash (Undo restores it); the incoming file takes its place.' };
    const paint = () => { $$('[data-a="clash-all"]').forEach(b => { b.classList.toggle('on', b.dataset.k === all); b.setAttribute('aria-checked', b.dataset.k === all) }); $('#clash-help').textContent = help[all] };
    ACT['clash-all'] = t => { all = t.dataset.k; paint() };
    CH['clash-one'] = t => { if (t.value) per[t.dataset.fid] = t.value; else delete per[t.dataset.fid] };
    ACT['clash-no'] = () => closeModal();
    ACT['clash-ok'] = () => { closeModal.done = null; closeModal(); res({ action: all, skip_identical: $('#clash-same') ? $('#clash-same').checked : false, per }) };
    paint();
  });
}

/* ---------------- flows ---------------- */
async function preflight(ids) { try { return await API.selection(ids) } catch (e) { toastError(e); return null } }
function moveOrCopy(mode, ids, single = false) { // Why: choose (or create) a folder, confirm with the exact numbers, then the move stage
  if (!ids.length) return;
  const start = (S.settings && S.settings.dest) || (S.info && S.info.dest) || '';
  Picker.open({ mode: 'dest', start, title: `${mode === 'move' ? 'Move' : 'Copy'} ${fmt(ids.length)} ${filesWord(ids.length)} to…`, okLabel: `${mode === 'move' ? 'Move' : 'Copy'} here`,
    onDone: async paths => {
      const dest = paths[0]; if (!dest) return;
      const st = await preflight(ids); if (!st) return;
      const disk = mode === 'copy' ? await API.disk(dest).catch(() => null) : null;
      const r = await actionDialog(mode, ids, dest, st, disk); if (!r) return;
      const body = { ids, dest, mode, layout: r.layout, verify: r.verify, allow_project: r.allow_project, allow_viewonly: r.allow_viewonly };
      const clash = await resolveConflicts(body); if (clash === null) return;
      try {
        const x = await API.execute(Object.assign(body, Object.keys(clash).length ? { conflicts: clash } : {}));
        if (!x.count) { toast(`Nothing was ${mode === 'move' ? 'moved' : 'copied'}: every selected file is protected or view-only.`, 'err'); return }
        if (x.blocked) toast(`${fmt(x.blocked)} protected or view-only ${filesWord(x.blocked)} stayed where they are.`);
        closePreview();
        if (S.settings) S.settings.dest = dest;
        Stage.open({ n: x.count, by_cat: x.by_cat }, x.job, { mode, dest, back: S.view, fromSelection: !single });
      } catch (e) { toastError(e) }
    } });
}
async function toBin(ids, single = false) { // Why: Recycle Bin / Trash only, after a confirmation with the exact numbers
  if (!ids.length) return;
  const st = await preflight(ids); if (!st) return;
  const r = await actionDialog('trash', ids, '', st, null); if (!r) return;
  let x;
  try { x = await API.trash({ ids, allow_project: r.allow_project, allow_viewonly: r.allow_viewonly, confirm_count: r.confirm_count }) } catch (e) { toastError(e); return }
  if (!x.count) { toast('Nothing was sent: every selected file is protected or view-only.', 'err'); return }
  closePreview();
  await binProgress(x, single);
}
async function binProgress(x, single) { // Why: a calm progress dialog fed by the real job, then a summary with "Open Recycle Bin"
  modal(`<p class="eyebrow">${esc(binName())}</p><h2 id="bp-title">Moving ${fmt(x.count)} ${filesWord(x.count)} to the ${esc(binName())}…</h2>
    <div class="meter" data-css="margin:18px 0 10px"><i id="bp-bar" data-css="width:0%"></i></div><p class="mut num" id="bp-txt">Starting…</p><div id="bp-end"></div>`);
  let j = null;
  for (;;) {
    try { j = await API.job(x.job) } catch (e) { toastError(e); break }
    const bar = $('#bp-bar'), txt = $('#bp-txt');
    if (bar) bar.style.width = `${(100 * (j.done || 0) / Math.max(1, j.total || 1)).toFixed(1)}%`;
    if (txt) txt.textContent = `${fmt(j.done || 0)} of ${fmt(j.total || 0)} checked · ${fmt(j.moved || 0)} sent · ${sz(j.bytes || 0)}`;
    if (j.state !== 'running' && j.state !== 'paused') break;
    await sleep(POLL_JOB_MS);
  }
  const sent = (j && j.moved) || 0, skipped = (j && j.skipped) || 0, errs = ((j && j.errors) || []).slice(0, 6);
  if ($('#bp-title')) {
    $('#bp-title').textContent = sent ? `Sent ${fmt(sent)} ${filesWord(sent)} to the ${binName()}` : `Nothing was sent to the ${binName()}`;
    $('#bp-end').innerHTML = `${skipped ? `<div class="note warn" data-css="margin:12px 0">${ic('alert')}<div><b>${fmt(skipped)}</b> skipped (changed, missing or no ${esc(binName())}):<br><small>${errs.map(esc).join('<br>')}</small></div></div>` : ''}
      <p class="mut">They stay in the ${esc(binName())} until you empty it. Restore them from there at any time.</p>
      <div class="row" data-css="justify-content:flex-end;margin-top:14px"><button class="btn ghost" data-a="open-bin">${ic('external')} Open ${esc(binName())}</button><button class="btn pri" data-a="bp-done">${ic('check')} Done</button></div>`;
    setTimeout(() => { const b = $('#bp-end .btn.pri'); b && b.focus() }, 30);
  }
  if (sent) notify(`Sent ${fmt(sent)} ${filesWord(sent)} to the ${binName()}`, sz((j && j.bytes) || 0), 'trash');
  if (!single) Sel.clear(); else { for (const c of (j && j.current) || []) S.sel.delete(c.id); Sel.paint() }
  await refreshIndex(); if (S.refresh) S.refresh();
}

/* ---------------- buttons ---------------- */
SEL_ACTIONS.push({ html: () => `<button class="btn sm ghost" data-a="act-copy">${ic('copy')} Copy to…</button><button class="btn sm" data-a="act-move">${ic('moveto')} Move to…</button>
  <button class="btn sm danger" data-a="act-trash">${ic('trash')} ${esc(binName())}</button>` });
ACT['act-move'] = () => moveOrCopy('move', Sel.ids());
ACT['act-copy'] = () => moveOrCopy('copy', Sel.ids());
ACT['act-trash'] = () => toBin(Sel.ids());
ACT['pv-move'] = t => moveOrCopy('move', [+t.dataset.id], true);
ACT['pv-copyto'] = t => moveOrCopy('copy', [+t.dataset.id], true);
ACT['pv-trash'] = t => toBin([+t.dataset.id], true);
ACT['open-bin'] = () => API.openTrash().then(r => r && r.demo && toast(`Demo: this would open the ${binName()}.`)).catch(e => toastError(e));
ACT['bp-done'] = () => closeModal();
