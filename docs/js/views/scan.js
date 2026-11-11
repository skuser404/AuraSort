/* AuraSort - Scan: Quick Scan (usual folders) or Deep Scan (drives + folders), estimate, live progress, pause/resume/cancel. */
'use strict';
const DRIVE_ICON = { internal: 'drive', external: 'usb', removable: 'usb', network: 'network', optical: 'disc', ram: 'drive', unknown: 'drive' };
function scanSetup() { // Why: remembered between runs (settings), drives chosen per scan
  if (!S.setup) {
    const st = S.settings || {};
    S.setup = { mode: st.mode === 'deep' ? 'deep' : 'quick', drives: new Set((st.drives || []).filter(r => S.drives.some(d => d.root === r && d.ready))), folders: (st.roots || []).filter(r => !S.drives.some(d => d.root === r)), skip: st.skip || [], est: null, estimating: false };
  }
  return S.setup;
}
const deepRoots = st => [...st.drives, ...st.folders];
const NOTHING_PICKED = 'Pick at least one drive or folder.';
const scanReady = st => st.mode === 'quick' || deepRoots(st).length > 0;   // Deep Scan of folders only is a valid choice

function viewScan(v) {
  if (S.scan && ['running', 'paused'].includes(S.scan.state)) return scanProgress(v);
  const st = scanSetup(), quick = (S.info && S.info.quick || []).filter(q => q.exists);
  const chips = (arr, kind) => arr.map((p, i) => `<span class="chip" title="${esc(p)}">${ic('folder')}<span class="t">${esc(p)}</span><button data-a="rm-${kind}" data-i="${i}" aria-label="Remove ${esc(p)}">${ic('x')}</button></span>`).join('') || '<span class="mut">None.</span>';
  const what = st.mode === 'quick' ? `Quick Scan of ${fmt(quick.length)} usual folders` : `Deep Scan of ${fmt(st.drives.size)} ${st.drives.size === 1 ? 'drive' : 'drives'}${st.folders.length ? ` and ${fmt(st.folders.length)} ${st.folders.length === 1 ? 'folder' : 'folders'}` : ''}`;
  const risky = scanNeedsCare(st);
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Scan</p><h1>Scan your PC</h1><p>Scanning reads file names, sizes and dates. It does not open, change or move anything.</p></div></div>
  ${S.pending && S.pending.has ? `<div class="note" data-css="margin-bottom:16px">${ic('link')}<div><b>Opening a shared link</b> after the scan finishes.</div></div>` : ''}
  <div class="scan-grid"><section class="card"><div class="seg" role="tablist" data-css="margin-bottom:18px">
      <button class="${st.mode === 'quick' ? 'on' : ''}" data-a="scanmode" data-m="quick" role="tab" aria-selected="${st.mode === 'quick'}">Quick Scan</button><button class="${st.mode === 'deep' ? 'on' : ''}" data-a="scanmode" data-m="deep" role="tab" aria-selected="${st.mode === 'deep'}">Deep Scan</button></div>
    ${st.mode === 'quick' ? `<h3>Your usual folders</h3><p class="mut">Downloads, Documents, Desktop, Pictures, Videos and Music, where files tend to pile up. Usually done in seconds.</p>
      <div class="chips" data-css="margin:12px 0 4px">${quick.map(q => `<span class="chip" title="${esc(q.path)}">${ic('folder')}<span class="t">${esc(q.name)}${q.onedrive ? ' (OneDrive)' : ''}</span></span>`).join('') || '<span class="mut">No standard folders found.</span>'}</div>
      ${quick.length ? `<details class="qpaths"><summary class="mut">Exactly which folders</summary><ul class="mut fpath">${quick.map(q => `<li>${esc(q.path)}${q.onedrive ? ' <span class="badge b-mut">OneDrive</span>' : ''}</li>`).join('')}</ul></details>` : ''}`
    : `<h3>Drives</h3><p class="mut">Tick the drives to scan completely. System folders (Windows, Program Files, AppData and similar) are always skipped.</p>
      <div class="drives" data-css="margin:12px 0 18px">${S.drives.map(d => { const on = st.drives.has(d.root), p = d.total ? pct(d.used, d.total) : 0;
        return `<button class="drive ${on ? 'on' : ''} ${d.ready ? '' : 'off'}" data-a="drive" data-r="${esc(d.root)}" ${d.ready ? '' : 'disabled title="Not ready (unplugged, empty or not responding)"'} aria-pressed="${on}">
          <span class="d-top"><span class="d-ic">${ic(DRIVE_ICON[d.type] || 'drive')}</span><span><b>${esc(d.name)} (${esc(driveName(d.root))})</b><small class="mut">${esc(d.type)}${d.fs ? ' · ' + esc(d.fs) : ''}</small></span><span class="d-check" aria-hidden="true">${on ? ic('check') : ''}</span></span>
          ${d.ready ? `<span class="meter ${p > 90 ? 'warn' : ''}"><i data-css="width:${p.toFixed(1)}%"></i></span><small class="num mut">${sz(d.free)} free of ${sz(d.total)}</small>` : '<small class="mut">Not ready</small>'}</button>` }).join('')}</div>
      <h3>Folders</h3><div class="chips" data-css="margin:10px 0">${chips(st.folders, 'root')}</div><button class="btn ghost" data-a="pick-roots">${ic('plus')} Add folders</button>`}
    <h3 data-css="margin-top:22px">Folders to skip</h3><div class="chips" data-css="margin:10px 0">${chips(st.skip, 'skip')}</div><button class="btn ghost" data-a="pick-skip">${ic('plus')} Add folders to skip</button></section>
  <aside class="card ready"><h2>Ready to start</h2>
    <dl class="checklist">
      <div><dt>What</dt><dd>${esc(what)}</dd></div>
      <div><dt>Time</dt><dd id="est">${estimateHtml(st)}</dd></div>
      <div><dt>Read</dt><dd>File names, sizes and dates only</dd></div>
      <div><dt>Skipped</dt><dd>System and tool folders${st.skip.length ? `, plus ${fmt(st.skip.length)} of yours` : ''}</dd></div>
      <div><dt>Not touched</dt><dd>Nothing is moved, changed or deleted during a scan</dd></div>
    </dl>
    <p class="mut auth-note">Only scan files you own or are authorised to manage.</p>
    ${risky ? `<div class="note warn">${ic('alert')}<div>${esc(risky)}</div></div>` : ''}
    ${S.scanFail ? scanFailHtml(S.scanFail) : ''}
    ${S.scanResult ? scanExplainHtml(S.scanResult) : ''}
    <button class="btn pri lg" data-a="scan-start" ${scanReady(st) ? '' : 'disabled aria-describedby="start-help"'}>Start ${st.mode === 'quick' ? 'Quick' : 'Deep'} Scan</button>
    ${scanReady(st) ? '' : `<p class="mut start-help" id="start-help">${NOTHING_PICKED}</p>`}
    ${S.summary && S.summary.scan ? `<p class="mut" data-css="margin-top:14px">Last scan: ${S.summary.scan.mode === 'deep' ? 'Deep' : 'Quick'}, ${ago(S.summary.scan.finished)}, ${fmt(S.summary.total)} files${S.summary.scan.noaccess ? `, ${fmt(S.summary.scan.noaccess)} folders skipped (no access)` : ''}</p>` : ''}</aside></div>`;
  estimateSoon();
}
function estimateHtml(st) { // Why: an honest range from a short benchmark, always labelled as an estimate
  if (st.estimating) return 'Measuring the disk speed (2-3 seconds)…';
  if (!scanReady(st)) return NOTHING_PICKED;
  if (!st.est) return st.estErr ? `<span class="mut">No time estimate right now (${esc(st.estErr)}). You can still start the scan.</span>` : 'Estimating…';
  const e = st.est;
  return `<b>Estimated scan time: ${durRange(e.low_s, e.high_s)}</b><small class="mut" data-css="display:block">About ${fmt(e.est_files)} files at ${fmt(e.files_per_s)} files/s. This is an estimate.</small>`;
}
function scanNeedsCare(st) { // Why: a stronger reminder when the scan reaches network drives or another person's profile
  if (st.mode !== 'deep') return '';
  const net = S.drives.filter(d => st.drives.has(d.root) && d.type === 'network');
  const home = String((S.info && S.info.home) || '').toLowerCase(), other = st.folders.find(f => /[\\/]users[\\/][^\\/]+/i.test(f) && !f.toLowerCase().startsWith(home));
  if (net.length) return `This includes a network drive (${net.map(d => driveName(d.root)).join(', ')}). Make sure you are allowed to scan it, for example under your workplace's IT rules.`;
  if (other) return 'This includes another person\'s user folder. Only scan it if you are allowed to manage those files.';
  return '';
}
const estimateSoon = debounce(async () => { // Why: the ETA updates whenever the selection changes (once per selection, not per redraw)
  const st = scanSetup(); if (S.view !== 'scan' || !scanReady(st)) return;
  const req = { mode: st.mode, roots: st.mode === 'deep' ? deepRoots(st) : [] }, key = JSON.stringify(req);
  if (st.estKey === key && (st.est || st.estimating)) { const b = $('#est'); if (b) b.innerHTML = estimateHtml(st); return }
  st.estKey = key; st.estimating = true; st.est = null; st.estErr = ''; const box = $('#est'); if (box) box.innerHTML = estimateHtml(st);
  try { const e = await API.estimate(req); if (st.estKey === key) st.est = e }
  catch (e) { if (st.estKey === key) { st.est = null; st.estErr = friendly(e).replace(/[.]$/, '').toLowerCase(); st.estKey = '' } }
  if (st.estKey === key || !st.estKey) st.estimating = false;
  const b2 = $('#est'); if (b2) b2.innerHTML = estimateHtml(st);
}, ESTIMATE_DEBOUNCE_MS);

function scanRequest(st) { // Why: the one place that builds the scan request (contract: core/schema.py scan_request, docs/ARCHITECTURE.md)
  return { mode: st.mode, roots: st.mode === 'deep' ? deepRoots(st) : [], skip: st.skip, est_files: st.est ? st.est.est_files : 0 };
}
async function startScan() {
  const st = scanSetup();
  if (!scanReady(st)) { toast(NOTHING_PICKED, 'err'); return }   // also covers "Start" from the folder picker with nothing chosen
  const req = scanRequest(st);
  try {
    await API.scanStart(req);
    API.saveSettings({ drives: [...st.drives] }).catch(() => {});
    S.scanFail = null; S.scanResult = null; S.scan = { state: 'running', found: 0 }; render(false); pollScan();
  } catch (e) {
    if (e.code === 'no_storage_access' || e.code === 'no_quick_folders') {   // a card with the exact fix, not a passing toast
      S.scanResult = { found: 0, skipped: '', explain: [{ code: e.code, title: e.message, body: e.hint }] }; render(false); return;
    }
    toastError(e, { retry: startScan, what: 'starting a scan', paths: req.roots });
  }
}
function scanExplainHtml(r) { // Why: a scan that finds nothing (or nothing to sort) says why and what to do, never just zeros
  return `<div class="scan-explain" role="status"><p><b>${r.found ? `The last scan found ${fmt(r.found)} files.` : 'The last scan found no files.'}</b>${r.skipped ? ` <span class="mut">${esc(r.skipped)}</span>` : ''}</p>
    ${r.explain.map(x => `<div class="note explain">${ic('alert')}<div><h3>${esc(x.title)}</h3><p>${esc(x.body)}</p></div></div>`).join('')}
    <div class="row" data-css="margin-top:10px"><button class="btn sm ghost" data-a="nav" data-v="settings">${ic('check')} Open Diagnostics</button></div></div>`;
}
function scanFailHtml(f) { // Why: a failed scan explains itself on the page, with a way forward (Try again, Copy details)
  return `<div class="note err scan-fail" role="alert">${ic('alert')}<div><b>The last scan stopped.</b> ${esc(f.message || ERROR_TEXT.internal)}${f.hint ? ` <span class="mut">${esc(f.hint)}</span>` : ''}
    <div class="row"><button class="btn sm" data-a="scan-start">Try again</button><button class="btn sm ghost" data-a="scan-fail-details">Copy details</button></div></div></div>`;
}
ACT['scan-fail-details'] = () => { const f = S.scanFail || {}; showErrorDetails({ e: { failure: f, message: f.message }, what: 'scan', paths: f.paths || [] }) };
function skippedText(s) { // Why: nothing is dropped silently: "12 skipped: 9 no permission, 3 removed during the scan"
  const r = s.skipped_reasons || [];
  return s.skipped_total ? `${fmt(s.skipped_total)} skipped: ${r.map(x => `${fmt(x.n)} ${x.label}`).join(', ')}` : '';
}
async function pollScan() { // Why: live partial counts while the scan runs; finishing loads the new index
  if (pollScan.on) return; pollScan.on = true;
  try {
    for (;;) {
      let s; try { s = await API.scanStatus() } catch (e) { toastError(e); break }
      S.scan = s; if (S.view === 'scan') updateScanUI(s);
      if (!['running', 'paused'].includes(s.state)) { await scanDone(s); break }
      await sleep(POLL_SCAN_MS);
    }
  } finally { pollScan.on = false }
}
async function scanDone(s) {
  if (s.state === 'done') {
    notify(`Scan finished: ${fmt(s.found)} files`, `${sz(s.bytes)} · ${dur(s.elapsed)}`, 'scan'); toast(`Scan finished: ${fmt(s.found)} files (${sz(s.bytes)})${s.skipped_total ? `, ${fmt(s.skipped_total)} skipped` : ''}`, 'ok');
    S.extData = null; await refreshIndex();
    S.scanResult = (s.explain && s.explain.length) ? { found: s.found, explain: s.explain, skipped: skippedText(s) } : null;
    const p = S.pending; S.pending = null;
    if (!s.found) { S.view = 'scan'; render(false); syncURL('replace') }   // stay here: the explanation is the next step, not an empty dashboard
    else if (p && p.has) { applyParams(p); render(); syncURL('replace'); syncSearchBox() } else go('dashboard');
  } else if (s.state === 'cancelled') { toast('Scan cancelled. Your previous index is kept.'); render(false) }
  else {
    const f = Object.assign({ message: (s.errors || [])[0] || ERROR_TEXT.internal }, s.failure || {}, { paths: s.roots || [] });
    S.scanFail = f; toastError({ message: f.message, code: f.code, hint: f.hint, failure: f }, { retry: startScan, what: 'scan', paths: f.paths }); render(false);
  }
}
function scanProgress(v) {
  const s = S.scan || {};
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">${s.mode === 'deep' ? 'Deep Scan' : 'Quick Scan'}</p><h1 id="sc-title">${s.state === 'paused' ? 'Paused' : 'Scanning…'}</h1><p>Reading names, sizes and dates only. You can keep using ${esc(APP.name)}; results appear as soon as it finishes.</p></div>
    <div class="actions"><button class="btn" data-a="scan-pause" id="sc-pause">${s.state === 'paused' ? ic('play') + ' Resume' : ic('pause') + ' Pause'}</button><button class="btn danger" data-a="scan-cancel">${ic('stop')} Cancel</button></div></div>
  <section class="card progress-panel"><div class="ring-wrap">${ringSvg('ring', 'sc-ring')}<div class="ring-c"><b class="num" id="sc-pct">0%</b><small>estimated</small></div></div>
    <div><div class="kv"><div><small>Files found</small><b class="num" id="sc-found">0</b></div><div><small>Folders scanned</small><b class="num" id="sc-dirs">0</b></div><div><small>Total size</small><b class="num" id="sc-bytes">0 B</b></div>
      <div><small>Elapsed</small><b class="num" id="sc-el">0 s</b></div><div><small>Remaining (estimate)</small><b class="num" id="sc-rem">…</b></div><div><small>Speed</small><b class="num" id="sc-rate">—</b></div></div>
      <p class="mut" data-css="margin:14px 0 0;word-break:break-all" id="sc-cur"></p><p class="mut" id="sc-noacc"></p></div></section>
  <div class="grid g2" data-css="margin-top:20px"><section class="card"><div class="card-h"><h2>Live folders</h2><small>the folders being read right now</small></div><div class="ticker" id="sc-ticker"></div></section>
    <section class="card"><div class="card-h"><h2>Found so far</h2><small>per file type</small></div><div class="hero-scene scan-scene">${Scene.html()}</div><div class="catcount" id="sc-cats"></div><div id="sc-drives" data-css="margin-top:16px"></div></section></div>`;
  updateScanUI(s);
  const sv = $('#view .scene'); if (sv) Scene.mount(sv, 'scan', {});
}
function updateScanUI(s) { // Why: update numbers in place (no re-render flicker while polling)
  const set = (id, t) => { const e = $('#' + id); if (e && e.textContent !== t) e.textContent = t };
  if (!$('#sc-found')) return;
  const ring = $('#sc-ring'); if (ring) ring.style.strokeDashoffset = (100 - (s.pct || 0)).toFixed(2);
  set('sc-pct', Math.round(s.pct || 0) + '%'); set('sc-found', fmt(s.found)); set('sc-dirs', fmt(s.dirs)); set('sc-bytes', sz(s.bytes)); set('sc-el', dur(s.elapsed));
  set('sc-rem', s.remaining == null ? 'measuring…' : '~' + dur(s.remaining)); set('sc-rate', s.rate ? fmt(s.rate) + ' files/s' : '—');
  set('sc-title', s.state === 'paused' ? 'Paused' : 'Scanning…'); set('sc-cur', s.current_file ? 'Now: ' + s.current_file : '');
  set('sc-noacc', skippedText(s));
  const pb = $('#sc-pause'); if (pb) { const want = s.state === 'paused' ? 'Resume' : 'Pause'; if (!pb.textContent.includes(want)) pb.innerHTML = s.state === 'paused' ? ic('play') + ' Resume' : ic('pause') + ' Pause' }
  const tk = $('#sc-ticker'), recent = (s.recent || []).slice().reverse();
  if (tk && tk.dataset.k !== recent.join('|')) { tk.dataset.k = recent.join('|'); tk.innerHTML = recent.map(p => `<div>${esc(p)}</div>`).join('') }
  Scene.feed(s.by_cat);
  const cats = $('#sc-cats'); if (cats) cats.innerHTML = CATS.map(c => { const n = (s.by_cat || {})[c.key] || 0; return `<span class="${n ? '' : 'zero'}" data-css="--c:${c.c}">${ic(c.ic)}${esc(c.key)} <b class="num">${fmt(n)}</b></span>` }).join('');
  const dv = $('#sc-drives'); if (dv) dv.innerHTML = (s.drives || []).filter(d => d.pct != null).map(d => `<div class="row" data-css="margin-top:8px"><span data-css="width:70px">${esc(driveName(d.root))}</span><span class="meter" data-css="flex:1"><i data-css="width:${Math.min(100, d.pct).toFixed(1)}%"></i></span><span class="num">${Math.round(d.pct)}%</span></div>`).join('');
}
ACT.scanmode = t => { const st = scanSetup(); st.mode = t.dataset.m === 'deep' ? 'deep' : 'quick'; st.est = null; render(false) };
ACT.drive = t => { const st = scanSetup(), r = t.dataset.r; st.drives.has(r) ? st.drives.delete(r) : st.drives.add(r); st.est = null; render(false) };
ACT['rm-root'] = t => { const st = scanSetup(); st.folders.splice(+t.dataset.i, 1); st.est = null; render(false) };
ACT['rm-skip'] = t => { const st = scanSetup(); st.skip.splice(+t.dataset.i, 1); API.saveSettings({ skip: st.skip }).catch(() => {}); st.est = null; render(false) };
ACT['pick-roots'] = () => Picker.open({ mode: 'scan', title: 'Choose folders to scan', selected: scanSetup().folders, onDone: (paths, start) => { const st = scanSetup(); st.folders = paths; st.est = null; render(false); if (start) startScan() } });
ACT['pick-skip'] = () => Picker.open({ mode: 'skip', title: 'Choose folders to skip', selected: scanSetup().skip, onDone: paths => { const st = scanSetup(); st.skip = paths; API.saveSettings({ skip: paths }).catch(() => {}); st.est = null; render(false) } });
ACT['scan-start'] = () => startScan();
ACT['scan-pause'] = async () => { try { S.scan = await API.scanControl(S.scan && S.scan.state === 'paused' ? 'resume' : 'pause'); updateScanUI(S.scan) } catch (e) { toastError(e) } };
ACT['scan-cancel'] = async () => { if (!await confirmDialog({ title: 'Cancel the scan?', body: 'Files found so far are not saved; your previous index is kept.', ok: 'Cancel scan', danger: true })) return; try { await API.scanControl('cancel') } catch (e) { toastError(e) } };
