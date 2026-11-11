/* AuraSort - API client (server.py on 127.0.0.1) or the demo backend, plus the search-worker client. */
'use strict';
const TOKEN = (document.querySelector('meta[name=app-token]') || {}).content || '__TOKEN__';
const DEMO_Q = new URLSearchParams(location.search).has('demo');
const DEMO = TOKEN === '__TOKEN__' || DEMO_Q;

async function call(path, body) { // Why: every request carries the per-run token in a header (never in the URL)
  let r;
  try {
    r = await fetch('/api/' + path, { method: body ? 'POST' : 'GET', headers: { 'X-AuraSort-Token': TOKEN, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined });
  } catch (e) { throw new Error('offline') }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const e = apiError(j, r, path); if (r.status === 423 && typeof Pin !== 'undefined' && !/^pin\//.test(path)) Pin.onLocked(); throw e }
  return j;
}
function apiError(j, r, path) { // Why: the server answers {error, code, hint}; keep all three (and the step) for friendly text and "Copy details"
  const e = new Error(j.error || r.statusText || 'Request failed');
  e.code = j.code || ''; e.hint = j.hint || ''; e.status = r.status; e.step = 'request ' + String(path).split('?')[0];
  if (j.retry_after != null) e.retry_after = j.retry_after;   // PIN lockout countdown
  if (j.attempts_left != null) e.attempts_left = j.attempts_left;
  return e;
}
function friendly(e) { // Why: plain-English errors; no stack traces, exception names or paths
  const m = String(e && e.message || e || ''), code = e && e.code;
  if (m === 'offline' || /failed to fetch|networkerror/i.test(m)) return `Can't reach the ${APP.name} server. Make sure server.py is still running, then reload.`;
  if (code && ERROR_TEXT[code]) return ERROR_TEXT[code];
  if (/session expired|bad token/i.test(m)) return ERROR_TEXT.session_expired;
  if (/^[A-Z][a-zA-Z]*Error\b/.test(m) || /unexpected error \(/i.test(m)) return ERROR_TEXT.internal;   // never show an exception name
  return m ? m.charAt(0).toUpperCase() + m.slice(1) : 'Something went wrong.';
}
const RealApi = {
  info: () => call('info'), diagnostics: scan => call('diagnostics?' + qs({ scan: scan ? 1 : 0 })), drives: () => call('drives'), browse: p => call('browse?' + qs({ path: p })),
  settings: () => call('settings'), saveSettings: d => call('settings', d),
  estimate: b => call('scan/estimate', b), scanStart: b => call('scan/start', b), scanControl: action => call('scan/control', { action }), scanStatus: () => call('scan/status'),
  summary: () => call('summary'), files: p => call('files?' + qs(p)), fileIds: p => call('files/ids?' + qs(p)), rows: ids => call('rows', { ids }),
  extensions: () => call('extensions'), folders: p => call('folders?' + qs(p)), include: b => call('folders/include', b),
  thumb: () => '',   // real thumbnails use the signed link the server puts on each row (r.thumb)
  reveal: id => call('reveal', { id }), revealJob: job => call('reveal', { job }), disk: p => call('disk?' + qs({ path: p })),
  plan: b => call('plan', b), execute: b => guarded('transfer', 'execute', b), job: id => call('job?' + qs({ id })), conflicts: b => call('conflicts', b),
  history: limit => call('history?' + qs({ limit })), undo: id => guarded('undo', 'undo', { id }), snapshots: p => call('snapshots?' + qs(p)),
  preview: id => call('preview?' + qs({ id })), openFile: (id, macro_ok) => call('open', { id, macro_ok: !!macro_ok }),
  calendar: p => call('calendar?' + qs(p)), timeline: p => call('timeline?' + qs(p)),
  selection: ids => call('selection', { ids }), trash: b => guarded('trash', 'trash', b), mkdir: (parent, name) => call('mkdir', { parent, name }),
  openTrash: () => call('open-trash', {}), historyItem: id => call('history/item?' + qs({ id })), jobControl: (id, action) => call('job/control', { id, action }),
  aiStatus: () => call('ai/status'), aiSettings: b => call('ai/settings', b), aiKey: b => guarded('ai_key', 'ai/key', b), aiTest: b => call('ai/test', b), aiStartEngine: () => call('ai/engine/start', {}),
  aiPull: model => call('ai/pull', { model }), aiStart: b => call('ai/start', b), aiConfirm: (job, allow_confidential) => call('ai/confirm', { job, allow_confidential }),
  integrityStart: b => call('integrity/start', b), integrityResults: p => call('integrity/results?' + qs(p)), duplicatesStart: () => call('duplicates/start', {}),
  duplicatesResults: p => call('duplicates/results?' + qs(p)), duplicatesExtras: () => call('duplicates/extras'), cleanup: p => call('cleanup?' + qs(p)),
  cleanupIds: p => call('cleanup/ids?' + qs(p)), quarantine: b => guarded('transfer', 'quarantine', b),
  interrupted: () => call('interrupted'), resume: id => guarded('transfer', 'interrupted/resume', { id }), cleanInterrupted: id => guarded('trash', 'interrupted/clean', { id }),
  deleteData: () => guarded('delete_data', 'data/delete', { confirm: 'DELETE' }),
  pinStatus: () => call('pin/status'), pinSet: b => call('pin/set', b), pinUnlock: b => call('pin/unlock', b), pinLock: () => call('pin/lock', {}),
  pinVerify: b => call('pin/verify', b), pinReset: () => call('pin/reset', { confirm: 'RESET' }), pinSettings: b => guarded('settings', 'pin/settings', b),
  elevate: () => guarded('settings', 'elevate', {}),
  appTrash: () => call('apptrash'), appTrashRestore: id => guarded('undo', 'apptrash/restore', { id }),
  aiClear: () => call('ai/clear', {}), aiReset: () => guarded('ai_key', 'ai/reset', {}), aiResults: p => call('ai/results?' + qs(p)), aiIds: p => call('ai/ids?' + qs(p))
};
const API = DEMO ? DemoApi : RealApi;

/* ---------------- search worker client ---------------- */
const Search = {
  w: null, seq: 0, waits: new Map(), version: null,
  start() { // Why: one worker for the whole session
    if (this.w) return;
    this.w = new Worker('js/search-worker.js');
    this.w.onmessage = e => { const r = this.waits.get(e.data.id); if (!r) return; this.waits.delete(e.data.id); e.data.error ? r.rej(new Error(e.data.error)) : r.res(e.data) };
  },
  post(msg) { this.start(); msg.id = ++this.seq; return new Promise((res, rej) => { this.waits.set(msg.id, { res, rej }); this.w.postMessage(msg) }) },
  async ensure(version) { // Why: reload the compact index only when the server's index changed
    if (this.version === version) return;
    if (DEMO) await this.post({ type: 'demo', table: DemoApi.table(), version });
    else await this.post({ type: 'ensure', token: TOKEN, version });
    this.version = version;
  },
  async query(params, version) { await this.ensure(version); return this.post({ type: 'search', params }) }
};
