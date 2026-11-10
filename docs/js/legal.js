/* AuraSort - legal documents in the app: the first-run "Before you start" gate, an offline viewer for the same Markdown
   files that ship in the repo, the footer, and Settings > Legal (accepted version, "Delete my AuraSort data"). */
'use strict';
const TERMS_VERSION = '1.0.0';            // must match "Version:" in TERMS_OF_USE.md; a new version shows the gate again
const TERMS_KEY = 'aurasort.terms';
const LEGAL = {
  terms: ['TERMS_OF_USE.md', 'Terms of Use'], rules: ['ACCEPTABLE_USE.md', 'Rules of use'], privacy: ['PRIVACY_POLICY.md', 'Privacy Policy'],
  ai: ['AI_DATA_NOTICE.md', 'AI Data Notice'], thirdparty: ['THIRD_PARTY_NOTICES.md', 'Third-party notices'], conduct: ['CODE_OF_CONDUCT.md', 'Code of Conduct'],
  licence: ['LICENSE', 'Open-source licence (MIT)']
};
const LEGAL_BY_FILE = Object.fromEntries(Object.entries(LEGAL).map(([k, [f]]) => [f, k]));

function acceptedTerms() { try { return JSON.parse(localStorage.getItem(TERMS_KEY) || 'null') } catch (e) { return null } }
function termsOk() { const a = acceptedTerms(); return !!(a && a.version === TERMS_VERSION) }

function termsGate() { // Why: the app does not start until the current Terms are accepted (shown again when they change)
  if (termsOk()) return Promise.resolve();
  const prev = acceptedTerms();
  return new Promise(res => {
    const g = $('#gate');
    g.innerHTML = `<div class="gate-card" role="dialog" aria-modal="true" aria-labelledby="gate-h"><div class="brand">${LOGO}<div><b>${esc(APP.name)}</b><small>${esc(APP.tagline)}</small></div></div>
      <h1 id="gate-h">${prev ? 'The terms have changed' : 'Before you start'}</h1>
      ${prev ? `<p class="mut">You accepted version ${esc(prev.version)}. Please read version ${esc(TERMS_VERSION)}.</p>` : ''}
      <h2>The short version</h2>
      <ul class="plain-list"><li>${esc(APP.name)} runs on this computer. Nothing is sent anywhere unless you turn on an optional cloud AI service.</li>
        <li>You choose what is touched: every move, copy or delete is shown to you first and needs your OK.</li>
        <li>Back up important files first, and try it on a test folder.</li>
        <li>The AI features are optional and off. They only suggest; they never act on files.</li>
        <li>It never permanently deletes: deleted files go to the Recycle Bin / Trash, and moves can be undone.</li></ul>
      <p data-css="margin-top:14px">Read the <button class="link" data-a="legal" data-doc="terms">Terms of Use</button>, the <button class="link" data-a="legal" data-doc="rules">Rules of use</button> and the <button class="link" data-a="legal" data-doc="privacy">Privacy Policy</button>.</p>
      <label class="row" data-css="margin:16px 0"><input type="checkbox" id="gate-ok"> <span>I have read and agree to the Terms of Use, the Rules of use and the Privacy Policy (version ${esc(TERMS_VERSION)}).</span></label>
      <button class="btn pri lg" id="gate-go" disabled>Continue</button></div>`;
    applyCss(g); g.hidden = false; document.body.classList.add('gated');
    $('#gate-ok').onchange = e => { $('#gate-go').disabled = !e.target.checked };
    $('#gate-go').onclick = () => {
      if (!$('#gate-ok').checked) return;
      try { localStorage.setItem(TERMS_KEY, JSON.stringify({ version: TERMS_VERSION, date: Date.now() })) } catch (e) { /* private window: asked again next time */ }
      g.hidden = true; g.innerHTML = ''; document.body.classList.remove('gated'); res();
    };
    setTimeout(() => { const c = $('#gate-ok'); c && c.focus() }, 30);
  });
}

/* ---------------- a small, safe Markdown renderer (everything is escaped first) ---------------- */
function mdInline(s) {
  let h = esc(s);
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  h = h.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, text, url) => {
    const raw = url.replace(/&amp;/g, '&');
    if (LEGAL_BY_FILE[raw]) return `<button class="link" data-a="legal" data-doc="${LEGAL_BY_FILE[raw]}">${text}</button>`;
    return /^https:\/\/[^\s"'<>]+$/.test(raw) ? `<a href="${esc(raw)}" target="_blank" rel="noopener noreferrer">${text}</a>` : text;
  });
  return h.replace(/&lt;(https:\/\/[^\s&]+)&gt;/g, (m, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`);
}
function mdHtml(md) {
  const out = [], lines = String(md).replace(/\r/g, '').split('\n');
  let list = null, para = [], quote = [], table = [];
  const flush = () => {
    if (para.length) { out.push(`<p>${mdInline(para.join(' '))}</p>`); para = [] }
    if (list) { out.push(`<${list.t}>${list.items.map(i => `<li>${mdInline(i)}</li>`).join('')}</${list.t}>`); list = null }
    if (quote.length) { out.push(`<div class="md-box">${mdHtml(quote.join('\n'))}</div>`); quote = [] }
    if (table.length) {
      const rows = table.filter(r => !/^\|?\s*:?-{3,}/.test(r)).map(r => r.replace(/^\||\|$/g, '').split('|').map(c => c.trim()));
      out.push(`<div class="tbl-wrap"><table class="tbl"><thead><tr>${rows[0].map(c => `<th>${mdInline(c)}</th>`).join('')}</tr></thead><tbody>${rows.slice(1).map(r => `<tr>${r.map(c => `<td>${mdInline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
      table = [];
    }
  };
  for (const ln of lines) {
    let m;
    if (/^>\s?/.test(ln)) { if (!quote.length) flush(); quote.push(ln.replace(/^>\s?/, '')); continue }
    if (quote.length) flush();
    if (/^\|/.test(ln)) { if (!table.length) flush(); table.push(ln); continue }
    if (table.length) flush();
    if ((m = ln.match(/^(#{1,4})\s+(.*)/))) { flush(); const n = Math.min(4, m[1].length + 1); out.push(`<h${n}>${mdInline(m[2])}</h${n}>`); continue }
    if ((m = ln.match(/^\s*(?:[-*]|(\d+)\.)\s+(.*)/))) { const t = m[1] ? 'ol' : 'ul'; if (para.length) flush(); if (!list || list.t !== t) { flush(); list = { t, items: [] } } list.items.push(m[2]); continue }
    if (!ln.trim()) { flush(); continue }
    if (/^(Version|Effective date|Owner|Release date): /.test(ln)) { flush(); out.push(`<p class="md-meta">${mdInline(ln)}</p>`); continue }
    if (list && /^\s{2,}/.test(ln)) { list.items[list.items.length - 1] += ' ' + ln.trim(); continue }
    para.push(ln.trim());
  }
  flush();
  return out.join('');
}

async function openLegal(key) { // Why: the same files that ship in the repo, read from this computer (no network)
  const doc = LEGAL[key]; if (!doc) return;
  const box = modal(`<div class="legal-doc"><div class="skel row"></div></div><div class="row" data-css="justify-content:flex-end;margin-top:14px"><button class="btn pri" data-a="legal-close">Close</button></div>`, 'legal');
  ACT['legal-close'] = () => { closeModal(); if (!$('#gate').hidden) $('#gate-ok') && $('#gate-ok').focus() };
  let text;
  try { const r = await fetch('legal/' + doc[0]); if (!r.ok) throw new Error(); text = await r.text() } catch (e) { $('.legal-doc', box).innerHTML = `<p class="mut">This document could not be loaded. It is in the app folder as ${esc(doc[0])}.</p>`; return }
  $('.legal-doc', box).innerHTML = doc[0] === 'LICENSE' ? `<pre class="pv-text">${esc(text)}</pre>` : mdHtml(text);
}
ACT.legal = t => openLegal(t.dataset.doc);

function renderFooter() { // Why: version and the two most important documents, on every page
  const v = (S.info && S.info.version) || '1.0.0';
  $('#foot').innerHTML = `<span>${esc(APP.name)} v${esc(v)}</span><span aria-hidden="true">·</span><button class="link" data-a="legal" data-doc="terms">Terms</button><span aria-hidden="true">·</span><button class="link" data-a="legal" data-doc="privacy">Privacy</button>`;
}

function legalSection() { // Why: Settings > Legal
  const a = acceptedTerms();
  return `<section class="card" id="set-legal"><h2>Legal</h2>
    <p class="mut">${esc(APP.name)} ${esc((S.info && S.info.version) || '')}. You accepted the Terms version ${esc(a ? a.version : '?')}${a && a.date ? ` on ${esc(dtt(a.date / 1000))}` : ''}.</p>
    <div class="legal-list">${Object.entries(LEGAL).map(([k, [, title]]) => `<button class="btn sm ghost" data-a="legal" data-doc="${k}">${esc(title)}</button>`).join('')}</div>
    <div class="row" data-css="margin-top:16px"><button class="btn danger" data-a="del-data">Delete my AuraSort data</button><span class="mut">Withdraw AI consent and remove a saved API key in the Document Insights card above.</span></div></section>`;
}
ACT['del-data'] = async () => {
  if (!await confirmDialog({ title: 'Delete your AuraSort data?', danger: true, ok: 'Delete my data', check: 'I understand this cannot be undone',
    body: `<p>This removes ${esc(APP.name)}'s own data from this computer:</p><ul class="plain-list"><li>the file index and scan snapshots</li><li>History and Undo logs (moves can no longer be undone)</li>
      <li>thumbnails, settings and the log</li><li>Document Insights results and a saved API key</li></ul><p><b>Your own files are not touched</b>, and files ${esc(APP.name)} moved stay where they are.</p>` })) return;
  try { const r = await API.deleteData(); toast(`Deleted: ${r.removed.join(', ')}.`, 'ok'); S.settings = await API.settings(); await refreshIndex(); go('dashboard') }
  catch (e) { toastError(e) }
};
