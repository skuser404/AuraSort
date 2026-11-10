/* AuraSort - Insights page: "Storage tips" (rule-based) and "Documents" (Document Insights: optional, off by default).
   Document text is read on this computer; a model only suggests labels; confidential flags come from rules first;
   results live in the server's memory and clear themselves after the chosen time. */
'use strict';
const SENS = [['', 'All'], ['confidential', 'Confidential'], ['sensitive', 'Sensitive'], ['normal', 'Normal']];
const AI_ENGINES = [['ollama', 'Ollama'], ['lmstudio', 'LM Studio'], ['llamacpp', 'llama.cpp server']];
const DOC_EXTS_UI = ['pdf', 'docx', 'pptx', 'xlsx', 'txt', 'md', 'csv'];
const AI = { st: null, job: null, timer: null, res: null };

function insTabs(cur) {
  return `<div class="seg" role="tablist" data-css="margin-bottom:18px">${[['storage', 'Storage tips'], ['documents', 'Documents']].map(([k, l]) => `<button class="${cur === k ? 'on' : ''}" data-a="instab" data-k="${k}" role="tab" aria-selected="${cur === k}">${l}</button>`).join('')}</div>`;
}
function viewInsights(v) {
  const tab = S.insTab || (S.F.sens ? 'documents' : 'storage');
  S.insTab = tab;
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Insights</p><h1>Insights</h1><p>${tab === 'storage' ? 'Observations worked out from your real numbers with simple rules. Each one opens a list for you to review.'
    : 'What your documents are, and which ones look confidential. Read on this computer; the model only suggests.'}</p></div></div>${insTabs(tab)}<div id="ins"></div>`;
  if (tab === 'storage') $('#ins').innerHTML = `<section class="card">${insightHtml(insightsFor(S.summary))}</section>`;
  else loadAI();
}
ACT.instab = t => { S.insTab = t.dataset.k; if (t.dataset.k === 'storage') S.F.sens = ''; render(false); syncURL('replace') };

async function loadAI() {
  const box = $('#ins'); if (!box) return;
  box.innerHTML = skeletonRows(3);
  try { AI.st = await API.aiStatus() } catch (e) { box.innerHTML = empty('alert', 'Document Insights is unavailable', esc(friendly(e))); return }
  if (!$('#ins')) return;
  const st = AI.st;
  if (st.demo) { box.innerHTML = `<section class="card"><h2>Document Insights</h2><p class="mut">Runs only in the real app, on your own computer. The demo does not read documents.</p></section>`; return }
  if (!st.settings.consent_local) { box.innerHTML = aiFirstRun(); return }
  AI.job = st.job;
  box.innerHTML = `<div class="grid g-7-5">${aiEngineCard(st)}${aiHardwareCard(st)}</div><div class="stack" data-css="margin-top:20px">${aiRunCard(st)}<div id="ai-res"></div></div>`;
  if (AI.job) pollAI(); else if (st.results.count) loadAIResults(); else $('#ai-res').innerHTML = '';
}

/* ---------------- first run: explain, choose, consent ---------------- */
function aiFirstRun() {
  return `<section class="card ai-first"><h2>Before you turn it on</h2>
    <ul class="plain-list"><li>It reads the text of the documents you choose (PDF, Word, PowerPoint, Excel, text) and suggests what each one is.</li>
      <li>Confidential items (card numbers, PAN, Aadhaar, bank statements, passwords and similar) are found by fixed rules first. The model can raise a flag, never remove one.</li>
      <li>The model only suggests labels. It cannot open, move, delete or run anything.</li>
      <li>Results stay in memory and clear themselves after ${fmt(60)} minutes (you can choose 30, 60 or 90), when you quit, or when a file is moved or deleted.</li>
      <li>Nothing is read or sent before you start a batch.</li></ul>
    <h3 data-css="margin:18px 0 8px">Where should it run?</h3>
    <label class="ad-opt"><input type="radio" name="ai-where" value="local" checked><span><b>On this computer (recommended)</b> <small class="mut">Uses a free local engine such as Ollama or LM Studio. Nothing leaves this computer.</small></span></label>
    <label class="ad-opt"><input type="radio" name="ai-where" value="cloud"><span><b>Cloud API (optional)</b> <small class="mut">DeepSeek or another OpenAI-compatible service. You connect it with an API key, and every batch asks first.</small></span></label>
    <label class="row" data-css="margin:16px 0"><input type="checkbox" id="ai-consent" data-c="ai-consent"> <span>I understand what Document Insights reads and that it only suggests.</span></label>
    <button class="btn pri" data-a="ai-enable" id="ai-enable" disabled>Turn on Document Insights</button>
    <p class="mut" data-css="margin-top:12px">Details: <button class="link" data-a="legal" data-doc="ai">AI Data Notice</button>.</p></section>`;
}
CH['ai-consent'] = t => { $('#ai-enable').disabled = !t.checked };
ACT['ai-enable'] = async () => {
  if (!$('#ai-consent').checked) return;
  try { await API.aiSettings({ accept_local: true }); const where = ($('input[name=ai-where]:checked') || {}).value; await loadAI(); if (where === 'cloud') aiConnect() } catch (e) { toastError(e) }
};

/* ---------------- engine, hardware, cloud ---------------- */
function aiEngineCard(st) {
  const e = st.engine || {}, s = st.settings, running = e.running;
  const models = (e.models || []).map(m => m.name);
  return `<section class="card"><div class="card-h"><h2>Engine on this computer</h2><span class="badge ${running ? 'b-ok' : 'b-mut'}">${running ? 'running' : 'not running'}</span></div>
    <div class="row" data-css="margin-bottom:12px"><select data-c="ai-engine" aria-label="Engine">${AI_ENGINES.map(([k, l]) => `<option value="${k}" ${s.engine === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
      ${running ? `<select data-c="ai-model" aria-label="Model"><option value="">Choose a model</option>${models.map(m => `<option ${s.model === m ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select>` : ''}
      <button class="btn ghost" data-a="ai-test">Test connection</button></div>
    ${running ? (models.length ? `<p class="mut">${fmt(models.length)} ${models.length === 1 ? 'model' : 'models'} installed${s.model ? `. Using <b>${esc(s.model)}</b>.` : '. Choose one above.'}</p>` : '<p class="mut">The engine is running but has no models yet. Download one from the panel on the right.</p>')
      : s.engine === 'ollama' && e.installed ? `<p class="mut">Ollama is installed but not running.</p><button class="btn" data-a="ai-start-engine">Start engine</button>`
      : `<div class="note">${ic('info')}<div><b>No engine found on ${esc(e.url || 'this computer')}.</b> Install one (free), start it, then press Test connection.
          <ol class="steps"><li>Download <a href="${esc(st.downloads.ollama)}" target="_blank" rel="noopener noreferrer">Ollama</a> or <a href="${esc(st.downloads.lmstudio)}" target="_blank" rel="noopener noreferrer">LM Studio</a> and install it.</li>
          <li>Start it. Ollama runs in the background; in LM Studio, start the local server.</li><li>Download a small model (see the table on the right).</li></ol>${esc(APP.name)} never installs anything by itself.</div></div>`}
    <div class="ai-cloud"><div><b>Cloud API (optional)</b> <span class="mut">${s.consent_cloud && (s.key_in_session || s.key_saved) ? `connected: ${esc((st.presets[s.provider] || {}).label || s.provider)}, ${esc(s.cloud_model)}` : 'not connected'}</span></div>
      <button class="btn sm ghost" data-a="ai-connect">${s.consent_cloud ? 'Change' : 'Connect'}</button></div></section>`;
}
function aiHardwareCard(st) {
  const h = st.hardware, running = st.engine && st.engine.running && st.settings.engine === 'ollama';
  return `<section class="card"><h2>This computer</h2><dl class="checklist" data-css="margin-top:10px">
      <div><dt>Memory</dt><dd>${h.ram_gb ? `${h.ram_gb} GB` : 'unknown'}</dd></div><div><dt>Processor</dt><dd>${fmt(h.cores)} cores</dd></div>
      <div><dt>Graphics</dt><dd>${h.gpu ? `${esc(h.gpu.name)} (${fmt(h.gpu.vram_mb)} MB)` : 'No NVIDIA GPU found (CPU is fine, just slower)'}</dd></div></dl>
    <table class="tbl ai-tiers"><thead><tr><th>Memory</th><th>Model size</th><th>Examples</th></tr></thead><tbody>${h.tiers.map(t => `<tr class="${h.tier && h.tier.min_gb === t.min_gb ? 'rec' : ''}"><td class="num">${t.min_gb >= 14 ? '16 GB' : t.min_gb >= 7 ? '8 GB' : '4 GB'}</td><td>${esc(t.label)}${h.tier && h.tier.min_gb === t.min_gb ? ' <span class="badge b-ok">fits</span>' : ''}</td>
      <td>${t.examples.map(m => running ? `<button class="link" data-a="ai-pull" data-m="${esc(m)}">${esc(m)}</button>` : `<code>${esc(m)}</code>`).join(', ')}</td></tr>`).join('')}</tbody></table>
    <p class="mut" data-css="margin-top:10px">Image descriptions need ${h.vision_ok ? 'a vision model; this computer has enough memory' : 'more memory than this computer has'}. ${running ? 'Select a model name to download it.' : ''}</p>${st.pypdf ? '' : '<p class="mut">PDFs are read with a basic built-in reader. Installing the optional <code>pypdf</code> package reads more of them.</p>'}</section>`;
}
CH['ai-engine'] = async t => { await saveAI({ engine: t.value, model: '' }); loadAI() };
CH['ai-model'] = async t => { await saveAI({ model: t.value }); loadAI() };
async function saveAI(part) { try { AI.st.settings = await API.aiSettings({ settings: part }) } catch (e) { toastError(e) } }
ACT['ai-test'] = async () => { try { const r = await API.aiTest({ mode: 'local' }); toast(`Connected. ${fmt(r.models.length)} models found.`, 'ok'); loadAI() } catch (e) { toastError(e) } };
ACT['ai-start-engine'] = async t => { t.disabled = true; t.textContent = 'Starting…'; try { await API.aiStartEngine(); await sleep(2500); loadAI() } catch (e) { toastError(e); t.disabled = false } };
ACT['ai-pull'] = async t => {
  const m = t.dataset.m;
  if (!await confirmDialog({ title: `Download ${m}?`, ok: 'Download', body: `<p>Ollama downloads the model from its own servers. Small models are about 1 to 5 GB; the exact size appears as soon as the download starts. You can cancel it.</p>` })) return;
  try { const r = await API.aiPull(m); pullProgress(r.job, m) } catch (e) { toastError(e) }
};
async function pullProgress(jid, m) {
  modal(`<h2>Downloading ${esc(m)}</h2><div class="meter" data-css="margin:16px 0 8px"><i id="pl-bar" data-css="width:0%"></i></div><p class="mut num" id="pl-txt">Starting…</p><div class="row" data-css="justify-content:flex-end"><button class="btn ghost" data-a="pl-cancel" data-j="${esc(jid)}">Cancel</button></div>`);
  for (;;) {
    let j; try { j = await API.job(jid) } catch (e) { break }
    if ($('#pl-bar')) { $('#pl-bar').style.width = j.total_bytes ? `${(100 * j.bytes / j.total_bytes).toFixed(1)}%` : '0%'; $('#pl-txt').textContent = `${j.status || ''} ${j.total_bytes ? `${sz(j.bytes)} of ${sz(j.total_bytes)}` : ''}` }
    if (!['running', 'paused'].includes(j.state)) { closeModal(); toast(j.state === 'done' ? `${m} is ready.` : (j.errors[0] || 'The download stopped.'), j.state === 'done' ? 'ok' : 'err'); loadAI(); return }
    await sleep(800);
  }
}
ACT['pl-cancel'] = t => API.jobControl(t.dataset.j, 'cancel').then(() => toast('Download cancelled.')).catch(e => toastError(e));

function aiConnect() { // Why: API keys, not passwords; a clear privacy warning; an explicit consent for the cloud
  const s = AI.st.settings, p = AI.st.presets;
  modal(`<h2>Connect a cloud API</h2>
    <p class="mut">Cloud providers use <b>API keys</b>, not your account login. Create a key on the provider's website and paste it here. Never type your account password into ${esc(APP.name)}.</p>
    <div class="form-grid"><label for="cl-prov">Provider</label><select id="cl-prov">${Object.entries(p).map(([k, x]) => `<option value="${k}" ${s.provider === k ? 'selected' : ''}>${esc(x.label)}</option>`).join('')}</select>
      <label for="cl-url">API address</label><input type="text" id="cl-url" value="${esc(s.cloud_url)}" placeholder="starts with https">
      <label for="cl-model">Model</label><input type="text" id="cl-model" value="${esc(s.cloud_model)}">
      <label for="cl-key">API key</label><input type="password" id="cl-key" autocomplete="off" spellcheck="false" placeholder="${s.key_in_session || s.key_saved ? 'A key is saved. Paste a new one to replace it.' : 'Paste the key'}"></div>
    <p class="mut" id="cl-page">${p[s.provider] && p[s.provider].key_page ? `Get a key at <a href="${esc(p[s.provider].key_page)}" target="_blank" rel="noopener noreferrer">${esc(p[s.provider].key_page)}</a>.` : ''}</p>
    <label class="row"><input type="checkbox" id="cl-remember"> <span>Remember the key in this computer's keychain (otherwise it is forgotten when ${esc(APP.name)} closes)</span></label>
    <div class="note warn" data-css="margin:14px 0">${ic('alert')}<div>Text you send is handled under the provider's own privacy policy, and ${esc(APP.name)} cannot delete it from their servers. DeepSeek's privacy policy states that data may be stored on servers in China; check the current policy. For banking, job, legal and medical documents, use <b>On this computer</b> instead.</div></div>
    <label class="row"><input type="checkbox" id="cl-consent"> <span>I understand that the documents I send in a batch go to this provider (IDs and numbers masked, Confidential files held back unless I choose otherwise).</span></label>
    <div class="row" data-css="justify-content:flex-end;margin-top:16px"><button class="btn ghost" data-a="cf-no">Cancel</button><button class="btn ghost" data-a="cl-test">Test connection</button><button class="btn pri" data-a="cl-save">Save</button></div>`);
  ACT['cf-no'] = () => closeModal();
  $('#cl-prov').onchange = e => { const x = p[e.target.value]; if (x.base_url) $('#cl-url').value = x.base_url; if (x.model) $('#cl-model').value = x.model; $('#cl-page').innerHTML = x.key_page ? `Get a key at <a href="${esc(x.key_page)}" target="_blank" rel="noopener noreferrer">${esc(x.key_page)}</a>.` : '' };
}
async function cloudSave(test) {
  if (!$('#cl-consent').checked) { toast('Tick the consent box first.', 'err'); return false }
  try {
    await API.aiSettings({ accept_cloud: true, settings: { provider: $('#cl-prov').value, cloud_url: $('#cl-url').value.trim(), cloud_model: $('#cl-model').value.trim() } });
    const key = $('#cl-key').value.trim();
    if (key) { const r = await API.aiKey({ key, remember: $('#cl-remember').checked }); if ($('#cl-remember').checked && !r.remembered) toast('No keychain is available here, so the key is kept for this session only.') }
    $('#cl-key').value = '';
    if (test) { const r = await API.aiTest({ mode: 'cloud' }); toast(`Connected. ${fmt(r.models.length)} models available.`, 'ok') }
    return true;
  } catch (e) { toastError(e); return false }
}
ACT['ai-connect'] = () => aiConnect();
ACT['cl-test'] = () => cloudSave(true);
ACT['cl-save'] = async () => { if (await cloudSave(false)) { closeModal(); loadAI() } };

/* ---------------- running a batch ---------------- */
function aiRunCard(st) {
  const s = st.settings, docs = [...S.sel.values()].length, ready = st.engine && st.engine.running && s.model, cloud = s.consent_cloud && (s.key_in_session || s.key_saved);
  return `<section class="card" id="ai-run"><div class="card-h"><h2>Read documents</h2><small>${fmt(st.docs)} documents in the index</small></div>
    <div class="row ai-run-opts"><label class="ad-opt"><input type="radio" name="ai-scope" value="all" ${docs ? '' : 'checked'}><span><b>All documents</b> <small class="mut num">${fmt(st.docs)} files</small></span></label>
      <label class="ad-opt"><input type="radio" name="ai-scope" value="sel" ${docs ? 'checked' : 'disabled'}><span><b>Selected files</b> <small class="mut num">${fmt(docs)} selected (documents only)</small></span></label></div>
    <div class="row ai-run-opts"><label class="ad-opt"><input type="radio" name="ai-mode" value="local" ${ready ? 'checked' : 'disabled'}><span><b>On this computer</b> <small class="mut">${ready ? esc(s.model) : 'start an engine and choose a model first'}</small></span></label>
      <label class="ad-opt"><input type="radio" name="ai-mode" value="cloud" ${cloud ? '' : 'disabled'}><span><b>Cloud API</b> <small class="mut">${cloud ? 'asks before sending' : 'not connected'}</small></span></label>
      <label class="ad-opt"><input type="radio" name="ai-mode" value="rules" ${ready ? '' : 'checked'}><span><b>Rules only</b> <small class="mut">confidential check, no descriptions</small></span></label></div>
    <div id="ai-prog"></div><button class="btn pri" data-a="ai-go" id="ai-go">Start</button></section>`;
}
ACT['ai-go'] = async () => {
  const scope = ($('input[name=ai-scope]:checked') || {}).value, mode = ($('input[name=ai-mode]:checked') || {}).value || 'rules';
  try { const r = await API.aiStart({ mode, ids: scope === 'sel' ? Sel.ids() : null }); AI.job = r.job; pollAI() } catch (e) { toastError(e) }
};
async function pollAI() { // Why: patient, honest progress ("Reading 214 of 1,030 documents, about 38 min left")
  const go = $('#ai-go'); if (go) go.hidden = true;
  if (pollAI.on) return; pollAI.on = true;
  try {
    for (;;) {
      let j; try { j = await API.job(AI.job) } catch (e) { break }
      const box = $('#ai-prog'); if (!box) break;
      const total = j.total;
      const verb = j.phase === 'reading' ? 'Reading' : j.phase === 'confirm' ? 'Waiting for your OK' : 'Describing';
      box.innerHTML = `<p><b>${verb} ${fmt(j.phase === 'reading' ? j.read : j.done)} of ${fmt(total)} documents</b>${j.remaining ? `, about ${dur(j.remaining)} left (estimate)` : ''}</p>
        <div class="meter" data-css="margin:8px 0"><i data-css="width:${(100 * (j.phase === 'reading' ? j.read : j.done) / Math.max(1, total)).toFixed(1)}%"></i></div>
        <p class="mut num">${esc(j.current_file || '')} · elapsed ${dur(j.elapsed)}${j.confidential ? ` · ${fmt(j.confidential)} confidential so far` : ''}</p>
        <div class="row">${j.state === 'paused' ? '<button class="btn sm" data-a="ai-ctl" data-c="resume">Resume</button>' : j.state === 'running' ? '<button class="btn sm ghost" data-a="ai-ctl" data-c="pause">Pause</button>' : ''}<button class="btn sm danger" data-a="ai-ctl" data-c="cancel">Cancel</button></div>`;
      applyCss(box);
      if (j.phase === 'confirm' && !$('#cc-send')) cloudConfirm(j);
      if (!['running', 'paused', 'waiting'].includes(j.state)) { box.innerHTML = ''; if ($('#ai-go')) $('#ai-go').hidden = false; AI.job = null; loadAIResults(true, j); break }
      await sleep(POLL_JOB_MS * 3);
    }
  } finally { pollAI.on = false }
}
ACT['ai-ctl'] = t => API.jobControl(AI.job, t.dataset.c).catch(e => toastError(e));
function cloudConfirm(j) { // Why: nothing goes to the cloud until the user sees exactly what will be sent, for this batch
  const p = j.cloud_plan;
  modal(`<h2>Send ${fmt(p.files - p.confidential)} documents to the cloud API?</h2>
    <dl class="checklist"><div><dt>Files</dt><dd>${fmt(p.files - p.confidential)} of ${fmt(p.files)} (Confidential ones held back)</dd></div><div><dt>Text</dt><dd class="num">about ${fmt(p.chars)} characters, first ${fmt(p.pages)} pages at most</dd></div>
      <div><dt>Masked</dt><dd>Card, account, PAN, Aadhaar and similar numbers, e-mail addresses and phone numbers are replaced before sending</dd></div><div><dt>Never sent</dt><dd>File paths, other files, the files themselves</dd></div></dl>
    ${p.confidential ? `<label class="row" data-css="margin:10px 0"><input type="checkbox" id="cc-conf"> <span>Also send the ${fmt(p.confidential)} Confidential files (not recommended)</span></label>` : ''}
    <div class="row" data-css="justify-content:flex-end;margin-top:14px"><button class="btn ghost" data-a="cc-stop">Do not send</button><button class="btn pri" data-a="cc-send" id="cc-send">Send</button></div>`);
  ACT['cc-send'] = async () => { const conf = !!($('#cc-conf') && $('#cc-conf').checked); closeModal(); try { await API.aiConfirm(AI.job, conf) } catch (e) { toastError(e) } };
  ACT['cc-stop'] = async () => { closeModal(); try { await API.jobControl(AI.job, 'cancel') } catch (e) { /* ignore */ } };
}

/* ---------------- results ---------------- */
function aiParams(extra = {}) { const F = S.F; return Object.assign({ sens: F.sens, doctype: S.aiType || '', junk: S.aiJunk ? '1' : '', q: F.q.trim(), format: [...F.formats], date: F.date, from: F.from, to: F.to, page: S.page, per: PAGE_SIZE }, extra) }
async function loadAIResults(fresh, job) {
  const box = $('#ai-res'); if (!box) return;
  let r; try { r = await API.aiResults(aiParams()) } catch (e) { box.innerHTML = empty('alert', 'Could not load results', esc(friendly(e))); return }
  if (!$('#ai-res')) return;
  AI.res = r; S.page = r.page; Sel.remember(r.rows, { kind: 'ai', params: aiParams({ page: '', per: '' }), total: r.total });
  const sm = r.summary;
  if (!sm.count) { box.innerHTML = fresh ? `<div class="note">${ic('info')}<div>${job && job.state === 'cancelled' ? 'Stopped. Nothing was kept.' : 'No results.'}</div></div>` : ''; return }
  box.innerHTML = `<div class="note ${sm.confidential ? 'err' : 'ok'} ai-banner">${ic(sm.confidential ? 'lock' : 'check')}<div><b>Completed. ${fmt(sm.count)} documents read, ${fmt(sm.confidential)} confidential.</b>
      <span class="mut" id="ai-clock"></span></div><button class="btn sm ghost" data-a="ai-clear">Clear now</button></div>
    <div class="toolbar" data-css="margin-top:14px"><div class="seg" role="group" aria-label="Sensitivity">${SENS.map(([k, l]) => `<button class="${(S.F.sens || '') === k ? 'on' : ''}" data-a="ai-sens" data-k="${k}">${l}${k ? ` <span class="num">${fmt(r.levels[k] || 0)}</span>` : ''}</button>`).join('')}</div>
      <select data-c="ai-type" aria-label="Document type"><option value="">All document types</option>${r.types.map(([t, n]) => `<option value="${esc(t)}" ${S.aiType === t ? 'selected' : ''}>${esc(t)} (${fmt(n)})</option>`).join('')}</select>
      <label class="row"><input type="checkbox" data-c="ai-junk" ${S.aiJunk ? 'checked' : ''}> Likely junk</label>${dateBtn()}
      <label class="fld">${ic('search')}<input type="search" data-c="ai-q" placeholder="Search names and descriptions" value="${esc(S.F.q)}" maxlength="100" aria-label="Search results"></label>
      ${sm.confidential ? '<button class="btn sm" data-a="ai-private">Move confidential to a Private folder</button>' : ''}</div>
    <div class="list-head"><span class="row nowrap"><label class="lh-sel">${pageBox(r.rows, 'Select every file on this page')}</label><span><b class="num">${fmt(r.total)}</b> <span class="mut">documents</span></span></span><span class="mut">Total ${sizeHtml(r.size)}</span></div>
    <div class="card list-card">${aiTable(r.rows)}</div><div id="ai-pager">${r.total ? pagerHtml(r, 'ai-pg') : ''}</div>`;
  applyCss(box); Sel.paint(); tickClock();
}
function aiTable(rows) {
  if (!rows.length) return '<p class="mut" data-css="padding:16px">No documents match these filters.</p>';
  return `<div class="tbl-wrap"><table class="ftable ai-table"><thead><tr><th class="c-sel">${pageBox(rows, 'Select every file in this list')}</th><th class="c-name">Document</th><th>Description</th><th class="c-sens">Sensitivity</th><th class="c-size">Size</th><th class="c-folder">Folder</th></tr></thead><tbody>`
    + rows.map(f => { const a = f.ai; return `<tr class="lvl-${a.level} ${S.sel.has(f.id) ? 'sel' : ''}" data-id="${f.id}"><td class="c-sel">${selBox(f)}</td>
      <td class="c-name"><div class="fname">${fileIcon(f)}<span class="fn-text"><button class="fn-open" data-a="preview" data-id="${f.id}"><b>${esc(f.name)}</b></button><small><span class="ext">.${esc(f.ext)}</span>${a.doc_type ? `<span>${esc(a.doc_type)}</span>` : ''}</small></span></div></td>
      <td>${a.description ? esc(a.description) : `<span class="mut">${esc(a.note || 'Not described')}</span>`}${a.reasons.length ? `<div class="reasons">${a.reasons.map(x => `<span class="rchip r-${x.level}" title="${esc(x.label)}">${esc(x.label)}${x.masked ? ` <span class="num">${esc(x.masked)}</span>` : ''}${x.count > 1 ? ` ×${fmt(x.count)}` : ''}</span>`).join('')}</div>` : ''}
        ${a.key_fields.length ? `<small class="mut">${a.key_fields.map(esc).join(' · ')}</small>` : ''}${a.junk === 'high' || a.action === 'delete-candidate' ? ' <span class="badge b-asset">likely junk</span>' : ''}</td>
      <td class="c-sens"><span class="badge s-${a.level}">${esc(a.level)}</span></td><td class="c-size">${sizeHtml(f.size)}<small class="mut num" data-css="display:block">${dt(f.mtime)}</small></td><td class="c-folder">${pathHtml(f.path)}</td></tr>` }).join('') + '</tbody></table></div>';
}
function tickClock() { // Why: a visible countdown until the results clear themselves
  clearInterval(AI.timer);
  const draw = () => { const el = $('#ai-clock'), exp = AI.res && AI.res.summary.expires_at; if (!el || !exp) { clearInterval(AI.timer); return }
    const left = Math.max(0, exp - Date.now() / 1000); el.textContent = ` Results clear in ${Math.floor(left / 60)}:${pad2(Math.floor(left % 60))}.`;
    if (left <= 0) { clearInterval(AI.timer); loadAIResults() } };
  draw(); AI.timer = setInterval(draw, 1000);
}
ACT['ai-sens'] = t => { S.F.sens = t.dataset.k; S.page = 1; loadAIResults(); syncURL('replace') };
ACT['ai-pg'] = t => { S.page = Math.max(1, +t.dataset.p); loadAIResults() };
ACT['ai-clear'] = async () => { try { await API.aiClear(); toast('Results cleared.', 'ok'); loadAIResults() } catch (e) { toastError(e) } };
CH['ai-type'] = t => { S.aiType = t.value; S.page = 1; loadAIResults() };
CH['ai-junk'] = t => { S.aiJunk = t.checked; S.page = 1; loadAIResults() };
CH['ai-q'] = t => { S.F.q = t.value.slice(0, 100); clearTimeout(CH.aq); CH.aq = setTimeout(() => { S.page = 1; loadAIResults() }, FILTER_DEBOUNCE_MS) };
ACT['ai-private'] = async () => { // Why: a safe, undoable move of the confidential files into one private folder
  let ids; try { ids = (await API.aiIds(aiParams({ sens: 'confidential', page: '', per: '' }))).ids } catch (e) { toastError(e); return }
  const root = (S.settings && S.settings.dest) || (S.info && S.info.dest) || '';
  try { await API.mkdir(root, 'Private').catch(e => { if (!/already exists/i.test(e.message)) throw e }) } catch (e) { toastError(e); return }
  const dest = joinPath(root, 'Private'), st = await preflight(ids); if (!st) return;
  const r = await actionDialog('move', ids, dest, st, null); if (!r) return;
  try { const x = await API.execute({ ids, dest, mode: 'move', layout: r.layout, allow_project: r.allow_project, allow_viewonly: r.allow_viewonly }); if (x.count) Stage.open({ n: x.count, by_cat: x.by_cat }, x.job, { mode: 'move', dest, back: 'insights', fromSelection: true }) }
  catch (e) { toastError(e) }
};
