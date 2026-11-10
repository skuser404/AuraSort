/* AuraSort - Corrupted files, Duplicates and Cleanup. All three only read and suggest; acting on files always goes
   through the selection bar (Move, Quarantine, Recycle Bin) with its confirmations. */
'use strict';
const SEV_TABS = [['', 'All problems'], ['corrupted', 'Corrupted'], ['damaged', 'Damaged'], ['warning', 'Warnings']];
const CK = { sev: '', page: 1, dpage: 1, reason: '', rpage: 1 };

function jobBox(id, label) { return `<div id="${id}" class="job-box"></div>` + (label ? `<p class="mut">${esc(label)}</p>` : '') }
async function followJob(jid, box, onDone) { // Why: one progress widget for checks: real counts, an estimate, pause/resume/cancel
  for (;;) {
    let j; try { j = await API.job(jid) } catch (e) { break }
    const el = $('#' + box); if (!el) return;
    const stage = j.kind === 'duplicates' ? (j.stage === 'full' ? 'Comparing every byte of possible matches' : 'Comparing sizes and the first and last 64 KB') : `Checking (${j.mode === 'deep' ? 'deep' : 'quick'})`;
    el.innerHTML = `<p><b>${esc(stage)}: ${fmt(j.done)} of ${fmt(j.total)} files</b>${j.remaining ? `, about ${dur(j.remaining)} left (estimate)` : ''}</p>
      <div class="meter" data-css="margin:8px 0"><i data-css="width:${(j.pct || 0).toFixed(1)}%"></i></div><p class="mut num">${esc(j.current_file || '')}</p>
      <div class="row">${j.state === 'paused' ? '<button class="btn sm" data-a="ck-ctl" data-c="resume">Resume</button>' : '<button class="btn sm ghost" data-a="ck-ctl" data-c="pause">Pause</button>'}<button class="btn sm danger" data-a="ck-ctl" data-c="cancel">Cancel</button></div>`;
    el.dataset.job = jid; applyCss(el);
    if (!['running', 'paused'].includes(j.state)) { el.innerHTML = ''; onDone(j); return }
    await sleep(POLL_JOB_MS * 3);
  }
}
ACT['ck-ctl'] = t => { const jid = t.closest('.job-box').dataset.job; API.jobControl(jid, t.dataset.c).catch(e => toast(friendly(e), 'err')) };
async function downloadCsv() { // Why: the token stays in a header; the CSV arrives as a blob the browser saves
  try {
    const r = await fetch('/api/integrity/csv', { headers: { 'X-AuraSort-Token': TOKEN } }); if (!r.ok) throw new Error('Export failed.');
    const url = URL.createObjectURL(await r.blob()), a = document.createElement('a');
    a.href = url; a.download = `${APP.name.toLowerCase()}-problem-files.csv`; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
  } catch (e) { toast(friendly(e), 'err') }
}

/* ---------------- Corrupted ---------------- */
function viewCorrupted(v) {
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Corrupted files</p><h1>Damaged and broken files</h1><p>A read-only check: Quick looks at each file's structure, Deep reads every byte. Nothing is changed or repaired, and every result says why it may have happened and what to do.</p></div></div>
    <section class="card"><div class="row"><div class="seg" role="group" aria-label="Check depth"><button class="${(CK.mode || 'quick') === 'quick' ? 'on' : ''}" data-a="ck-mode" data-m="quick">Quick</button><button class="${CK.mode === 'deep' ? 'on' : ''}" data-a="ck-mode" data-m="deep">Deep</button></div>
      <span class="mut">${CK.mode === 'deep' ? 'Reads every byte: slower, finds more.' : 'Checks headers, endings and structure: fast.'}</span><span class="sb-sp"></span>
      <button class="btn pri" data-a="ck-start">${S.sel.size ? `Check ${fmt(S.sel.size)} selected files` : 'Check all files'}</button></div>${jobBox('ck-job')}</section>
    <div id="ck-res" data-css="margin-top:20px">${skeletonRows(3)}</div>`;
  S.refresh = loadCorrupted; loadCorrupted();
}
async function loadCorrupted() {
  let r; try { r = await API.integrityResults({ sev: CK.sev, page: CK.page, per: PAGE_SIZE }) } catch (e) { if ($('#ck-res')) $('#ck-res').innerHTML = empty('alert', 'Could not load results', esc(friendly(e))); return }
  const box = $('#ck-res'); if (!box) return;
  const s = r.summary; Sel.remember(r.rows, { kind: 'none', total: r.total });
  if (!s.checked) { box.innerHTML = `<p class="mut">Not checked yet. Start a check above; it only reads files.</p>`; return }
  box.innerHTML = `${s.hint ? `<div class="note err" data-css="margin-bottom:14px">${ic('drive')}<div>${esc(s.hint)}</div></div>` : ''}
    <div class="toolbar"><div class="seg" role="group" aria-label="Severity">${SEV_TABS.map(([k, l]) => `<button class="${CK.sev === k ? 'on' : ''}" data-a="ck-sev" data-k="${k}">${l} <span class="num">${fmt(k ? s.by_sev[k] : s.problems)}</span></button>`).join('')}</div>
      <span class="sb-sp"></span><span class="mut num">${fmt(s.checked)} files checked${s.last ? `, ${ago(s.last)}` : ''}</span>${s.problems ? '<button class="btn sm ghost" data-a="ck-csv">Export CSV</button>' : ''}</div>
    ${r.total ? `<div class="list-head"><span class="row nowrap"><label class="lh-sel">${pageBox(r.rows, 'Select every file on this page')}</label><span><b class="num">${fmt(r.total)}</b> <span class="mut">problem files</span></span></span><span class="mut">Total ${sizeHtml(r.size)}</span></div>
      <div class="card list-card">${problemTable(r.rows)}</div>${pagerHtml(r, 'ck-pg')}` : `<div class="note ok">${ic('check')}<div>No problems found in ${fmt(s.checked)} checked files.</div></div>`}`;
  applyCss(box); Sel.paint();
}
function problemTable(rows) {
  return `<div class="tbl-wrap"><table class="ftable prob-table"><thead><tr><th class="c-sel"></th><th class="c-name">File</th><th>Problem</th><th class="c-size">Size</th><th class="c-folder">Folder</th></tr></thead><tbody>`
    + rows.map(r => { const f = r.findings[0] || {}; return `<tr class="${S.sel.has(r.id) ? 'sel' : ''}"><td class="c-sel">${selBox(r)}</td>
      <td class="c-name"><div class="fname">${fileIcon(r)}<span class="fn-text"><button class="fn-open" data-a="preview" data-id="${r.id}"><b>${esc(r.name)}</b></button><small><span class="ext">.${esc(r.ext || 'none')}</span></small></span></div></td>
      <td><span class="badge sev-${esc(f.sev)}">${esc(f.sev)}</span> ${esc(f.detail)}<small class="mut" data-css="display:block;margin-top:4px">Likely cause: ${esc(f.cause)}</small><small class="mut" data-css="display:block">What to do: ${esc(f.fix)}</small></td>
      <td class="c-size">${sizeHtml(r.size)}</td><td class="c-folder">${pathHtml(r.path)}</td></tr>` }).join('') + '</tbody></table></div>';
}
ACT['ck-mode'] = t => { CK.mode = t.dataset.m; render(false) };
ACT['ck-sev'] = t => { CK.sev = t.dataset.k; CK.page = 1; loadCorrupted() };
ACT['ck-pg'] = t => { CK.page = Math.max(1, +t.dataset.p); loadCorrupted() };
ACT['ck-csv'] = () => downloadCsv();
ACT['ck-start'] = async () => {
  try { const r = await API.integrityStart({ mode: CK.mode || 'quick', ids: S.sel.size ? Sel.ids() : null }); followJob(r.job, 'ck-job', j => { notify(`Check finished: ${fmt(j.problems || 0)} problem files`, `${fmt(j.checked || 0)} checked`, 'alert'); loadCorrupted() }) }
  catch (e) { toast(friendly(e), 'err') }
};

/* ---------------- Duplicates ---------------- */
function viewDuplicates(v) {
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Duplicates</p><h1>Identical files</h1><p>Found by comparing sizes, then the first and last 64 KB, then every byte. Empty files are never counted. Nothing is removed unless you choose to.</p></div></div>
    <section class="card"><div class="row"><span id="dp-sum" class="mut"></span><span class="sb-sp"></span><button class="btn pri" data-a="dp-start">Find duplicates</button></div>${jobBox('dp-job')}</section>
    <div id="dp-res" data-css="margin-top:20px">${skeletonRows(3)}</div>`;
  S.refresh = loadDuplicates; loadDuplicates();
}
async function loadDuplicates() {
  let r; try { r = await API.duplicatesResults({ page: CK.dpage }) } catch (e) { if ($('#dp-res')) $('#dp-res').innerHTML = empty('alert', 'Could not load duplicates', esc(friendly(e))); return }
  const box = $('#dp-res'); if (!box) return;
  const s = r.summary, rows = r.groups.flatMap(g => g.rows);
  Sel.remember(rows, { kind: 'none', total: rows.length });
  $('#dp-sum').textContent = s.last ? `${fmt(s.groups)} groups, ${sz(s.wasted)} could be freed. Checked ${ago(s.last)}.` : 'Not checked yet.';
  if (!s.last) { box.innerHTML = '<p class="mut">Not checked yet. Press Find duplicates; it only reads files.</p>'; return }
  if (!s.groups) { box.innerHTML = `<div class="note ok">${ic('check')}<div>No duplicates found. Nice.</div></div>`; return }
  box.innerHTML = `<div class="toolbar"><button class="btn" data-a="dp-extras">Select all but the newest copy</button><span class="mut">then use the bar below to move them or send them to the ${esc(binName())}</span></div>`
    + r.groups.map(g => `<section class="card dup-group"><div class="card-h"><h3>${fmt(g.n)} identical copies, ${sz(g.size)} each</h3><small class="num">${sz(g.wasted)} wasted</small></div>
      <div class="tbl-wrap"><table class="ftable"><tbody>${g.rows.map(f => `<tr class="${S.sel.has(f.id) ? 'sel' : ''}"><td class="c-sel">${selBox(f)}</td><td class="c-name"><div class="fname">${fileIcon(f)}<span class="fn-text"><button class="fn-open" data-a="preview" data-id="${f.id}"><b>${esc(f.name)}</b></button>
        <small>${f.id === g.keep ? '<span class="badge b-ok">newest, keep</span>' : ''}${kindBadge(f)}</small></span></div></td><td class="c-date num">${dt(f.mtime)}</td><td class="c-folder">${pathHtml(f.path)}</td></tr>`).join('')}</tbody></table></div></section>`).join('')
    + pagerHtml({ page: r.page, pages: r.pages, per: r.per, total: r.total }, 'dp-pg');
  applyCss(box); Sel.paint();
}
ACT['dp-start'] = async () => { try { const r = await API.duplicatesStart(); followJob(r.job, 'dp-job', j => { notify(`Duplicate check finished: ${fmt(j.groups || 0)} groups`, sz(j.wasted || 0) + ' could be freed', 'files'); loadDuplicates() }) } catch (e) { toast(friendly(e), 'err') } };
ACT['dp-pg'] = t => { CK.dpage = Math.max(1, +t.dataset.p); loadDuplicates() };
ACT['dp-extras'] = async () => { try { const r = await API.duplicatesExtras(); r.ids.forEach((id, i) => S.sel.set(id, { size: r.sizes[i] })); Sel.paint(); toast(`Selected ${fmt(r.ids.length)} extra copies (${sz(r.sizes.reduce((a, b) => a + b, 0))}).`, 'ok') } catch (e) { toast(friendly(e), 'err') } };

/* ---------------- Cleanup ---------------- */
function viewCleanup(v) {
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Cleanup</p><h1>Clean junk files</h1><p>Suggestions found with simple rules. Nothing is selected or removed until you review the list and choose. Files in project folders are left out.</p></div></div>
    <div id="cl-groups" class="cl-groups">${skeletonRows(2)}</div><div id="cl-list" data-css="margin-top:20px"></div>`;
  S.refresh = () => { loadCleanup(); if (CK.reason) loadCleanupList() }; loadCleanup(); if (CK.reason) loadCleanupList();
}
async function loadCleanup() {
  let r; try { r = await API.cleanup({}) } catch (e) { if ($('#cl-groups')) $('#cl-groups').innerHTML = empty('alert', 'Could not load suggestions', esc(friendly(e))); return }
  const box = $('#cl-groups'); if (!box) return;
  box.innerHTML = r.groups.map(g => `<button class="cl-group ${CK.reason === g.key ? 'on' : ''}" ${g.link ? `data-a="nav" data-v="${g.link}"` : `data-a="cl-open" data-k="${g.key}"`} ${g.n ? '' : 'disabled'}>
    <b>${esc(g.label)}</b><span class="num">${fmt(g.n)} ${g.n === 1 ? 'file' : 'files'} · ${sz(g.size)}</span><small class="mut">${esc(g.desc)}</small></button>`).join('');
}
async function loadCleanupList() {
  let r; try { r = await API.cleanup({ reason: CK.reason, page: CK.rpage, per: PAGE_SIZE }) } catch (e) { toast(friendly(e), 'err'); return }
  const box = $('#cl-list'); if (!box) return;
  Sel.remember(r.rows, { kind: 'cleanup', params: { reason: CK.reason }, total: r.total });
  box.innerHTML = r.total ? `<div class="list-head"><span class="row nowrap"><label class="lh-sel">${pageBox(r.rows, 'Select every file on this page')}</label><span><b class="num">${fmt(r.total)}</b> <span class="mut">files</span></span></span><span class="mut">Total ${sizeHtml(r.size)}</span></div>
    <div class="card list-card">${fileTable(r.rows)}</div>${pagerHtml(r, 'cl-pg')}` : '<p class="mut">Nothing in this group.</p>';
  Sel.paint();
}
ACT['cl-open'] = t => { CK.reason = t.dataset.k; CK.rpage = 1; $$('.cl-group').forEach(b => b.classList.toggle('on', b === t)); loadCleanupList() };
ACT['cl-pg'] = t => { CK.rpage = Math.max(1, +t.dataset.p); loadCleanupList() };

/* ---------------- Quarantine (from the selection bar on the Corrupted page) ---------------- */
SEL_ACTIONS.push({ html: () => S.view === 'corrupted' ? `<button class="btn sm ghost" data-a="act-quarantine">${ic('shield')} Quarantine</button>` : '' });
ACT['act-quarantine'] = async () => {
  const ids = Sel.ids(), st = await preflight(ids); if (!st) return;
  const r = await actionDialog('move', ids, 'Quarantine folder (inside your destination)', st, null); if (!r) return;
  try { const x = await API.quarantine({ ids, allow_project: r.allow_project, allow_viewonly: r.allow_viewonly, verify: r.verify }); if (x.count) Stage.open({ n: x.count, by_cat: x.by_cat }, x.job, { mode: 'move', dest: x.dest, back: 'corrupted', fromSelection: true }) }
  catch (e) { toast(friendly(e), 'err') }
};
