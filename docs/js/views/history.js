/* AuraSort - History: every scan, move, copy and Recycle Bin action; Undo for moves; details of what each one touched. */
'use strict';
const KIND_LABEL = { scan: 'Scan', move: 'Move', copy: 'Copy', trash: 'Recycle Bin', quarantine: 'Quarantine', integrity: 'Integrity check', duplicates: 'Duplicate check' };
function histLabel(x) { // Why: each row says plainly what happened ("Moved 8 files")
  const n = `${fmt(x.count)} ${x.count === 1 ? 'file' : 'files'}`;
  if (x.kind === 'quarantine' || x.label === 'quarantine') return `Quarantined ${n}`;
  if (x.kind === 'move') return `Moved ${n}`;
  if (x.kind === 'copy') return `Copied ${n}`;
  if (x.kind === 'trash') return `Sent ${n} to the ${binName()}`;
  if (x.kind === 'scan') return `${x.label || 'Scan'} found ${n}`;
  return x.label || KIND_LABEL[x.kind] || x.kind;
}
async function viewHistory(v) {
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Activity</p><h1>History &amp; undo</h1><p>Every action is logged on this computer. Moves can be undone. Files sent to the ${esc(binName())} are restored from there.</p></div></div><div id="hist">${skeletonRows(5)}</div>`;
  let h = [], broken = [];
  try { [h, broken] = await Promise.all([API.history(200), API.interrupted().catch(() => [])]) } catch (e) { $('#hist').innerHTML = empty('alert', 'History is unavailable', esc(friendly(e))); return }
  if (S.view !== 'history' || !$('#hist')) return;
  $('#hist').innerHTML = (broken.length ? `<section class="card" data-css="margin-bottom:20px"><h2>Stopped before finishing</h2><p class="mut">${esc(APP.name)} closed while these were running (for example a crash or power loss). Nothing was half-moved: every finished file is complete, the rest are still at their original places.</p>
    ${broken.map(x => `<div class="act"><span class="a-ic">${ic('alert')}</span><span><b>${esc(histLabel(x))} of ${fmt(x.left + x.count)} planned</b><small class="mut">${fmt(x.left)} left (${sz(x.left_bytes)})${x.parts ? `, ${fmt(x.parts)} partial ${x.parts === 1 ? 'copy' : 'copies'} found` : ''} · ${esc(ago(x.time))}</small></span>
      <button class="btn sm" data-a="int-resume" data-id="${esc(x.id)}" ${x.left ? '' : 'disabled'}>Resume</button><button class="btn sm ghost" data-a="int-clean" data-id="${esc(x.id)}">Clean up</button></div>`).join('')}</section>` : '') + (h.length ? `<div class="card list-card"><div class="tbl-wrap"><table class="tbl"><thead><tr><th>When</th><th>Action</th><th>Destination</th><th class="r">Size</th><th></th></tr></thead><tbody>
    ${h.map(x => `<tr><td class="num" title="${esc(dtt(x.time))}">${esc(ago(x.time))}</td><td><b>${esc(histLabel(x))}</b>${x.imported ? ' <span class="badge b-mut">imported</span>' : ''}${x.undone ? ' <span class="badge b-ok">undone</span>' : ''}${x.failed ? ` <span class="badge b-asset">${fmt(x.failed)} skipped</span>` : ''}</td>
      <td>${x.dest ? pathHtml(x.dest) : x.kind === 'trash' ? `<span class="mut">${esc(binName())}</span>` : '<span class="mut">—</span>'}</td><td class="r">${x.size ? sizeHtml(x.size) : '—'}</td>
      <td class="r"><div class="row" data-css="justify-content:flex-end;flex-wrap:nowrap">${x.undoable ? `<button class="btn sm" data-a="undo" data-id="${esc(x.id)}">${ic('undo')} Undo</button>` : ''}
        ${x.kind === 'trash' ? `<button class="btn sm ghost" data-a="open-bin">Open ${esc(binName())}</button>` : ''}
        ${['move', 'copy', 'trash', 'quarantine'].includes(x.kind) && x.count ? `<button class="btn sm ghost" data-a="histinfo" data-id="${esc(x.id)}">Details</button>` : ''}
        ${x.dest && x.kind !== 'scan' ? `<button class="btn sm ghost" data-a="openjob" data-id="${esc(x.id)}" title="Open destination" aria-label="Open destination">${ic('external')}</button>` : ''}</div></td></tr>`).join('')}
    </tbody></table></div></div>` : empty('history', 'Nothing here yet', 'Scans, moves, copies and Recycle Bin actions appear here. Moves can be undone.', `<button class="btn pri" data-a="nav" data-v="${S.hasIndex ? 'move' : 'scan'}">${S.hasIndex ? 'Sort files' : 'Scan my PC'}</button>`));
}
ACT['int-resume'] = async t => { try { const r = await API.resume(t.dataset.id); Stage.open({ n: r.count, by_cat: r.by_cat }, r.job, { mode: 'move', dest: '', back: 'history' }) } catch (e) { toastError(e) } };
ACT['int-clean'] = async t => {
  if (!await confirmDialog({ title: 'Clean up?', ok: 'Clean up', body: `<p>Partial copies left by the stopped job go to the ${esc(binName())}. Your original files are not touched, and the job is closed.</p>` })) return;
  try { const r = await API.cleanInterrupted(t.dataset.id); toast(`Cleaned up ${fmt(r.removed)} partial ${r.removed === 1 ? 'copy' : 'copies'}.`, 'ok'); render(false) } catch (e) { toastError(e) }
};
ACT.undo = async t => {
  if (!await confirmDialog({ title: 'Undo this move?', body: 'Files go back to where they came from. If a file with the same name exists there now, the restored one gets “(1)” added. Nothing is overwritten.', ok: 'Undo' })) return;
  try { const r = await API.undo(t.dataset.id); toast(`Restored ${fmt(r.restored)} files${r.missing ? `, ${fmt(r.missing)} missing` : ''}`, 'ok'); await refreshIndex(); render(false) } catch (e) { toastError(e) }
};
ACT.histinfo = async t => { // Why: exactly which files an action touched, and where they went
  let d; try { d = await API.historyItem(t.dataset.id) } catch (e) { toastError(e); return }
  modal(`<h2>${esc(histLabel(d))}</h2><p class="mut">${esc(dtt(d.time))}${d.size ? ` · ${sz(d.size)}` : ''}</p>
    <div class="hist-ops">${d.ops.map(o => `<div>${pathHtml(o.src)}${o.dst ? `<span class="hist-sub">→ ${esc(o.dst)}</span>` : ''}</div>`).join('')}${d.more ? `<div class="mut">and ${fmt(d.more)} more</div>` : ''}</div>
    <div class="row" data-css="justify-content:flex-end;margin-top:16px"><button class="btn pri" data-a="cf-no">Close</button></div>`);
  ACT['cf-no'] = () => closeModal();
};
ACT.openjob = t => API.revealJob(t.dataset.id).then(r => r && r.demo && toast('Demo: this would open the destination folder.')).catch(e => toastError(e));
