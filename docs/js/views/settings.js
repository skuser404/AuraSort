/* AuraSort - Settings, Help and Insights pages. */
'use strict';
function viewSettings(v) {
  const st = S.settings || {}, pref = themePref();
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Settings</p><h1>Settings</h1><p>Stored on this computer only.</p></div></div>
  <div class="stack">
  <section class="card"><h2>Theme</h2><p class="mut">Dark, Light, or follow your system. Applied instantly and remembered.</p>
    <div class="grid g3" data-css="margin-top:14px">${[['dark', 'moon', 'Dark', 'Dark grey, easy on the eyes at night'], ['light', 'sun', 'Light', 'Light grey with dark text'], ['system', 'monitor', 'System', 'Follows your system setting']]
      .map(([k, i, l, d]) => `<button class="drive ${pref === k ? 'on' : ''}" data-a="theme" data-t="${k}" aria-pressed="${pref === k}"><span class="d-top"><span class="d-ic">${ic(i)}</span><span><b>${l}</b><small class="mut">${d}</small></span><span class="d-check" aria-hidden="true">${pref === k ? ic('check') : ''}</span></span></button>`).join('')}</div></section>
  <section class="card"><h2>Default destination</h2><p class="mut">Where sorted files go. A dedicated folder inside your home folder is safest.</p>
    <div class="row" data-css="margin-top:12px;flex-wrap:nowrap"><input type="text" id="set-dest" value="${esc(st.dest || (S.info && S.info.dest) || '')}" aria-label="Default destination" data-css="flex:1"><button class="btn ghost" data-a="set-pick-dest">${ic('folder')} Browse…</button><button class="btn pri" data-a="set-save-dest">${ic('check')} Save</button></div></section>
  <section class="card"><h2>Folders to skip</h2><p class="mut">Never scanned (in addition to system and tool folders, which are always skipped).</p>
    <div class="chips" data-css="margin:12px 0">${(st.skip || []).map((p, i) => `<span class="chip" title="${esc(p)}">${ic('folder')}<span class="t">${esc(p)}</span><button data-a="set-rm-skip" data-i="${i}" aria-label="Remove ${esc(p)}">${ic('x')}</button></span>`).join('') || '<span class="mut">None.</span>'}</div>
    <button class="btn ghost" data-a="set-pick-skip">${ic('plus')} Add folders to skip…</button></section>
  <section class="card" id="set-pin"><h2>PIN lock</h2><p class="mut">${esc(APP.name)} asks for your PIN when it opens and before every move, copy, delete, undo or replace. It protects ${esc(APP.name)} on this computer; it does not stop someone already signed in to your account from using other programs, so also lock your screen.</p><div id="set-pin-body"><div class="skel row"></div></div></section>
  <section class="card" id="set-apptrash" ${S.info && S.info.apptrash ? '' : 'hidden'}><h2>AuraSort trash</h2><p class="mut">Files kept by "Replace", and on Android every deleted file, are moved into a folder named .AuraSortTrash on the same drive. Restore puts them back.</p><div id="set-apptrash-body"></div></section>
  <section class="card" id="set-diag"><h2>Diagnostics</h2><p class="mut">Checks Python, your data folder, the file index, the folders Quick Scan uses and a 3-second test scan. Same as <code>py server.py --doctor</code>. No file names are included; your user name is masked.</p>
    <div class="row" data-css="margin-top:12px"><button class="btn" data-a="diag-run">${ic('check')} Run diagnostics</button><button class="btn ghost" data-a="diag-copy" disabled>${ic('copy')} Copy diagnostics</button></div><div id="diag-out"></div></section>
  <section class="card" id="set-ai"><h2>Document Insights</h2><p class="mut">Optional and off until you turn it on in Insights, Documents.</p><div id="set-ai-body"><div class="skel row"></div></div></section>
  ${legalSection()}
  <section class="card"><h2>Privacy &amp; data</h2>
    <div class="act"><span class="a-ic">${ic('lock')}</span><span><b>Local only</b><small class="mut">The server listens on 127.0.0.1 with a per-run token. No telemetry, no analytics, no network calls.</small></span></div>
    <div class="act"><span class="a-ic">${ic('shield')}</span><span><b>Never permanently deletes</b><small class="mut">Moves are logged and undoable; deletes only go to the Recycle Bin / Trash.</small></span></div>
    <div class="act"><span class="a-ic">${ic('folder')}</span><span><b>Your data folder</b><small class="mut fpath">${esc((S.info && S.info.home ? S.info.home : '~') + (S.info && S.info.sep || '/') + '.aurasort')} (index, history, thumbnails; readable by you only)</small></span></div>
    <div class="act"><span class="a-ic">${ic('info')}</span><span><b>${esc(APP.name)} ${esc(S.info && S.info.version || '')}</b><small class="mut">${esc(APP.tagline)}${S.info && S.info.created_note ? ' · ' + esc(S.info.created_note) : ''}</small></span></div></section>
  </div>`;
  loadAISettings(); loadPinSettings(); if (S.info && S.info.apptrash) loadAppTrash();
}
async function loadPinSettings() { // Why: idle lock, "remember for N minutes" (off by default), lock now, change PIN
  const box = $('#set-pin-body'); if (!box) return;
  let st; try { st = await API.pinStatus() } catch (e) { box.innerHTML = `<p class="mut">${esc(friendly(e))}</p>`; return }
  if (!$('#set-pin-body')) return;
  if (st.demo) { box.innerHTML = '<p class="mut">The demo has no PIN (nothing on your computer is touched).</p>'; return }
  const sel = (k, list, cur, lbl) => `<label>${lbl} <select data-c="pin-set" data-k="${k}">${list.map(([v, l]) => `<option value="${v}" ${+cur === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>`;
  box.innerHTML = `<div class="row" data-css="margin:12px 0;gap:18px">
      ${sel('pin_idle_min', [[1, '1 minute'], [5, '5 minutes'], [10, '10 minutes'], [15, '15 minutes'], [30, '30 minutes'], [60, '1 hour']], st.idle_min, 'Lock after')}
      ${sel('pin_remember_min', [[0, 'Ask every time'], [1, 'Do not ask again for 1 minute'], [5, '... for 5 minutes'], [15, '... for 15 minutes']], st.remember_min, 'Before an action')}</div>
    <div class="row"><button class="btn" data-a="pin-lock-now">${ic('lock')} Lock now</button><button class="btn ghost" data-a="pin-change">Change PIN</button></div>`;
}
CH['pin-set'] = async t => { // Why: these settings weaken or restore a protection, so changing them needs the PIN (server-enforced)
  try { await API.pinSettings({ [t.dataset.k]: +t.value }); Pin.status = await API.pinStatus(); toast('Saved', 'ok') } catch (e) { toastError(e); loadPinSettings(); if (S.info && S.info.apptrash) loadAppTrash() }
};
ACT['pin-lock-now'] = async () => { try { await API.pinLock() } catch (e) { /* already locked */ } Pin.onLocked() };
ACT['pin-change'] = () => { // Why: the current PIN is needed to set a new one
  modal(`<h2>Change your PIN</h2>${pinField('pc-old', 'Current PIN', 6)}${pinField('pc-new', 'New PIN (4 or 6 digits)', 6)}${pinField('pc-new2', 'New PIN again', 6)}
    <p id="pin-msg" class="pin-msg" role="status"></p><div class="row" data-css="justify-content:flex-end;margin-top:12px"><button class="btn ghost" data-a="cf-no">Cancel</button><button class="btn pri" data-a="pc-save">Change PIN</button></div>`);
  ACT['cf-no'] = () => closeModal();
  $$('#modal .pin-in').forEach(i => i.addEventListener('input', () => { i.value = i.value.replace(/\D/g, '').slice(0, 6) }));
  setTimeout(() => $('#pc-old') && $('#pc-old').focus(), 30);
};
ACT['pc-save'] = async () => {
  const o = $('#pc-old').value, n = $('#pc-new').value, n2 = $('#pc-new2').value, msg = $('#pin-msg');
  if (!/^\d{4}(\d{2})?$/.test(n)) { msg.className = 'pin-msg err'; msg.textContent = 'The new PIN must be 4 or 6 digits.'; return }
  if (n !== n2) { msg.className = 'pin-msg err'; msg.textContent = 'The two new PINs are different.'; return }
  try { const r = await API.pinSet({ pin: n, current: o }); closeModal(); toast(r.weak ? 'PIN changed. It is easy to guess; consider a less obvious one.' : 'PIN changed.', 'ok') }
  catch (e) { msg.className = 'pin-msg err'; msg.textContent = friendly(e) }
};
async function loadAppTrash() { // Why: restore files kept by "Replace" (and, on Android, deleted files); optional purge timer
  const box = $('#set-apptrash-body'); if (!box) return;
  let d; try { d = await API.appTrash() } catch (e) { box.innerHTML = `<p class="mut">${esc(friendly(e))}</p>`; return }
  if (!$('#set-apptrash-body')) return;
  box.innerHTML = `${d.items.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>File</th><th>From</th><th class="r">Size</th><th>When</th><th></th></tr></thead><tbody>
    ${d.items.slice(0, 200).map(i => `<tr><td>${esc(base(i.original))}</td><td class="mut fpath">${esc(parentOf(i.original))}</td><td class="r">${sizeHtml(i.size)}</td><td>${esc(ago(i.time))}${i.reason === 'replaced' ? ' <span class="badge b-mut">replaced</span>' : ''}</td><td><button class="btn sm" data-a="at-restore" data-id="${esc(i.id)}">${ic('undo')} Restore</button></td></tr>`).join('')}</tbody></table></div>` : '<p class="mut">Empty.</p>'}
    <label class="row" data-css="margin-top:12px">Erase items older than <select data-c="pin-set" data-k="apptrash_purge_days">${d.purge_choices.map(v => `<option value="${v}" ${v === d.purge_days ? 'selected' : ''}>${v ? v + ' days' : 'never (keep them)'}</option>`).join('')}</select></label>
    <p class="mut">This timer is off unless you turn it on. It is the only thing in ${esc(APP.name)} that erases a file for good.</p>`;
}
ACT['at-restore'] = async t => { try { const r = await API.appTrashRestore(t.dataset.id); toast('Put back: ' + base(r.path), 'ok'); loadAppTrash() } catch (e) { toastError(e) } };
async function loadAISettings() { // Why: limits and the results timer for Document Insights, plus "Withdraw consent"
  const box = $('#set-ai-body'); if (!box) return;
  let st; try { st = await API.aiStatus() } catch (e) { box.innerHTML = `<p class="mut">${esc(friendly(e))}</p>`; return }
  if (!$('#set-ai-body')) return;
  if (st.demo) { box.innerHTML = '<p class="mut">Not available in the demo.</p>'; return }
  const s = st.settings, num = (k, l, lo, hi) => `<label>${l}<input type="number" data-c="set-ai-num" data-k="${k}" min="${lo}" max="${hi}" value="${s[k]}"></label>`;
  box.innerHTML = `<div class="form-grid set-ai">
      <label for="set-ttl">Clear results after</label><select id="set-ttl" data-c="set-ai-ttl">${st.ttl_choices.map(m => `<option value="${m}" ${s.ttl_min === m ? 'selected' : ''}>${m} minutes</option>`).join('')}</select>
    </div><div class="row" data-css="margin:12px 0">${num('parallel', 'Parallel jobs ', 1, 4)}${num('ctx', 'Context length ', 1024, 32768)}${num('pages', 'Pages per document ', 1, 50)}
      <label class="row"><input type="checkbox" data-c="set-ai-cpu" ${s.cpu_friendly ? 'checked' : ''}> CPU-friendly (one at a time)</label></div>
    <p class="mut">Turned on: ${s.consent_local ? esc(dtt(s.consent_local)) : 'no'}. Cloud allowed: ${s.consent_cloud ? esc(dtt(s.consent_cloud)) : 'no'}. API key: ${s.key_saved ? 'saved in the keychain' : s.key_in_session ? 'this session only' : 'none'}.</p>
    <button class="btn danger" data-a="set-ai-reset">Withdraw consent and reset AI settings</button>`;
}
CH['set-ai-ttl'] = t => API.aiSettings({ settings: { ttl_min: +t.value } }).then(() => toast('Saved. Applies to the next batch.', 'ok')).catch(e => toastError(e));
CH['set-ai-num'] = t => API.aiSettings({ settings: { [t.dataset.k]: +t.value } }).then(() => toast('Saved', 'ok')).catch(e => toastError(e));
CH['set-ai-cpu'] = t => API.aiSettings({ settings: { cpu_friendly: t.checked } }).then(() => toast('Saved', 'ok')).catch(e => toastError(e));
ACT['set-ai-reset'] = async () => {
  if (!await confirmDialog({ title: 'Withdraw consent and reset?', danger: true, ok: 'Reset', body: '<p>Document Insights is turned off, its settings go back to defaults, any saved API key is removed (from memory and the keychain), and current results are cleared. Your files are not touched.</p>' })) return;
  try { await API.aiReset(); toast('Document Insights is off and reset.', 'ok'); render(false) } catch (e) { toastError(e) }
};
const DIAG_MARK = { ok: ['check', 'b-ok', 'OK'], warn: ['alert', 'b-asset', 'Check'], fail: ['alert', 'b-err', 'Problem'] };
ACT['diag-run'] = async t => { // Why: the same facts as --doctor, readable here and copyable for a bug report
  const box = $('#diag-out'); t.disabled = true; box.innerHTML = '<div class="skel row"></div><div class="skel row"></div>';
  try {
    const d = await API.diagnostics(true); S.diag = d;
    box.innerHTML = `<div class="diag-list">${d.checks.map(c => { const [i, b, l] = DIAG_MARK[c.status] || DIAG_MARK.warn; return `<div class="act"><span class="a-ic">${ic(i)}</span><span><b>${esc(c.name)} <span class="badge ${b}">${l}</span></b><small class="mut fpath">${esc(c.value)}</small>${c.fix ? `<small>${esc(c.fix)}</small>` : ''}</span></div>` }).join('')}</div>`;
    const cp = $('[data-a="diag-copy"]'); if (cp) cp.disabled = false;
  } catch (e) { box.innerHTML = `<p class="mut">${esc(friendly(e))}</p>` } finally { t.disabled = false }
};
ACT['diag-copy'] = async () => { if (S.diag) { await copyText(S.diag.text); toast('Diagnostics copied. Paste them into a GitHub issue.', 'ok') } };
ACT['set-pick-dest'] = () => Picker.open({ mode: 'dest', title: 'Choose the default destination', onDone: p => { if (p[0]) $('#set-dest').value = p[0] } });
ACT['set-save-dest'] = async () => { try { S.settings = await API.saveSettings({ dest: $('#set-dest').value.trim() }); if (S.mv) S.mv.dest = S.settings.dest; toast('Destination saved', 'ok') } catch (e) { toastError(e) } };
ACT['set-pick-skip'] = () => Picker.open({ mode: 'skip', title: 'Choose folders to skip', selected: (S.settings || {}).skip || [], onDone: async paths => { try { S.settings = await API.saveSettings({ skip: paths }); if (S.setup) S.setup.skip = paths; render(false) } catch (e) { toastError(e) } } });
ACT['set-rm-skip'] = async t => { const skip = ((S.settings || {}).skip || []).slice(); skip.splice(+t.dataset.i, 1); try { S.settings = await API.saveSettings({ skip }); if (S.setup) S.setup.skip = skip; render(false) } catch (e) { toastError(e) } };

function viewHelp(v) {
  const sec = (i, t, body) => `<section class="card help-sec"><h2>${t}</h2><div class="mut">${body}</div></section>`;
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Help</p><h1>How ${esc(APP.name)} works</h1><p>${esc(APP.subline)}</p></div></div><div class="stack">
    ${sec('scan', 'Quick Scan vs Deep Scan', '<p><b>Quick Scan</b> reads your usual folders (Downloads, Documents, Desktop, Pictures, Videos/Movies, Music). It usually takes seconds.</p><p><b>Deep Scan</b> reads whole drives you choose (internal, external or network) plus any folders you add. It can be paused, resumed or cancelled, and shows an estimated time before you start.</p>')}
    ${sec('explore', 'Finding files', '<p>Every file is listed in <b>Media Explorer</b> with its size, date and full folder, 100 per page. Use the search bar (Ctrl/Cmd+K): it matches file names partially, ignores case and forgives small typos. Format chips (.jpg, .pdf…) filter instantly; the folder box narrows to folders whose path contains your text.</p>')}
    ${sec('lock', 'View-only categories', '<p>Code & Scripts, Installers & Apps, Disk images, Fonts, Databases, Text & Logs and Other are listed and searchable, but never moved or deleted unless you opt in and confirm a warning.</p>')}
    ${sec('shield', 'Safety guarantees', '<ul><li>Project folders (package.json, .git, .sln, Premiere/Blender/Ableton projects, websites…) and asset-like folders start unticked and need an explicit confirmation.</li><li>System folders are never scanned or touched.</li><li>Every file is re-checked right before it is moved (still there, unchanged, not a link).</li><li>Moves never overwrite: a clash becomes “name (1).ext”.</li><li>Every move is logged and can be undone. Nothing is ever permanently deleted.</li></ul>')}
    ${sec('moveto', 'Sorting', '<p><b>Sort &amp; move</b> previews exactly which folders will be created, how many files go into each, and how free space changes. Only then do you confirm. Copy keeps the originals; Move keeps one copy and can be undone from History.</p>')}
    ${sec('info', 'Privacy', '<p>The server only listens on 127.0.0.1 and needs a per-run token. There is no telemetry and no network access. Your index, history and thumbnails live in your own data folder, readable by you only.</p>')}
  </div>`;
}

