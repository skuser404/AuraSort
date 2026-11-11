// AuraSort: full-app run with Playwright on a fake home. Every sidebar page, every scan combination, theme, search, format and
// date filters, selection, move picker, move + undo, Recycle Bin, preview, integrity check, Settings and Legal.
// The run FAILS on any console error, any failed request (HTTP 4xx/5xx or network error) and any error toast, except inside
// the one block that triggers an error on purpose to test the error message, "Try again" and "Copy details".
//
// Test-only dependency (the app itself has none):  npm install playwright   (uses the installed Microsoft Edge, no download)
// Usage: node tests/e2e/full.pw.mjs --home <fixture home> [--url http://localhost:8799] [--out <dir>] [--pw <folder with node_modules>]
// Start the server with AURASORT_STRICT_SCHEMA=1 so an unknown request field is a 400 (and therefore a failure here).
import { createRequire } from 'node:module';
import fs, { existsSync, readdirSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d };
const HOME = arg('home'), B = arg('url', 'http://localhost:8799'), OUT = arg('out', '.');
const pwPath = createRequire(import.meta.url).resolve('playwright', { paths: [process.cwd(), arg('pw', process.cwd()), path.dirname(new URL(import.meta.url).pathname.slice(1))] });
const pwMod = await import(pathToFileURL(pwPath).href), chromium = pwMod.chromium || pwMod.default.chromium;
const P = (...a) => path.join(HOME, ...a);
const walk = d => existsSync(d) ? readdirSync(d, { withFileTypes: true }).flatMap(e => e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]) : [];
mkdirSync(OUT, { recursive: true });

let fails = 0, passes = 0;
const check = (ok, msg, extra = '') => { ok ? passes++ : fails++; console.log((ok ? 'PASS ' : 'FAIL ') + msg + (!ok && extra ? '  -> ' + extra : '')) };
const problems = [];        // console errors, failed requests, error toasts (outside the expected-error block)
let expecting = null;       // label of the block where one error is expected on purpose
const expected = [];

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || 'msedge', headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'] });
const page = await ctx.newPage();
const note = (kind, text) => (expecting ? expected : problems).push(`${kind}: ${text}${expecting ? ' [expected: ' + expecting + ']' : ''}`);
page.on('console', m => { if (['error', 'warning'].includes(m.type())) note('console.' + m.type(), m.text()) });
page.on('pageerror', e => note('page error', (e.stack || e.message).split(/\r?\n/).slice(0, 4).join(' | ')));
page.on('requestfailed', r => { const f = r.failure() && r.failure().errorText; if (!/ERR_ABORTED/.test(f || '')) note('request failed', `${r.method()} ${r.url()} ${f}`) });
page.on('response', r => { if (r.status() >= 400) note('HTTP ' + r.status(), `${r.request().method()} ${r.url().replace(B, '')}`) });
await page.addInitScript(() => {   // every error toast is recorded, even if it disappears before anyone looks
  window.__errToasts = [];
  document.addEventListener('DOMContentLoaded', () => {
    const t = document.querySelector('#toast');
    new MutationObserver(() => { if (t.classList.contains('err') && !t.hidden) window.__errToasts.push(t.textContent) }).observe(t, { attributes: true, childList: true, subtree: true });
  });
});
const ev = (fn, a) => page.evaluate(fn, a);
const PIN = '4826';
const enterPin = async (value = PIN) => {   // the PIN prompt before a move, copy, delete, undo or replace
  await page.waitForSelector('#pinbox:not([hidden]) #pin-x'); await page.fill('#pin-x', value); await page.click('#pin-ok');
};
const toasts = async () => { const t = await ev(() => window.__errToasts.splice(0)); t.forEach(x => note('error toast', x)); return t };
const waitFor = (fn, a, ms = 15000) => page.waitForFunction(fn, a, { timeout: ms });
const nav = async v => { await page.click(`[data-a=nav][data-v=${v}]`); await waitFor(v => S.view === v && !document.querySelector('#view .skel'), v, 15000).catch(() => {}); await page.waitForTimeout(250) };
const scanDone = async (jobId, ms = 60000) => {   // the page's own poller must have seen this job finish
  await waitFor(id => S.scan && S.scan.id === id && !['running', 'paused'].includes(S.scan.state) && !pollScan.on, jobId, ms);
  await page.waitForTimeout(400); return ev(() => S.scan);
};
let lastStart = 0;
const SCAN_SPACING_MS = 2600;   // the server allows 4 scan starts per 10 s; a person never starts them faster, this test would
const startScanWith = async (mode, folders, skip = []) => {   // the real Scan page: its own state, its scanRequest(), its Start button
  const wait = lastStart + SCAN_SPACING_MS - Date.now(); if (wait > 0) await page.waitForTimeout(wait);
  lastStart = Date.now();
  await nav('scan');
  await ev(({ mode, folders, skip }) => { const st = scanSetup(); st.mode = mode; st.drives = new Set(); st.folders = folders; st.skip = skip; st.est = null; render(false) }, { mode, folders, skip });
  await page.waitForTimeout(300);
  const [resp] = await Promise.all([page.waitForResponse(r => r.url().endsWith('/api/scan/start')), page.click('[data-a=scan-start]')]);
  const body = JSON.parse(resp.request().postData()), out = await resp.json();
  const s = resp.status() === 200 ? await scanDone(out.job) : { state: 'refused', errors: [out.error] };
  return { body, s };
};

try {
  /* ---------- first run ---------- */
  await page.goto(B + '/');
  await ev(() => localStorage.removeItem('aurasort.terms')); await page.reload();
  await page.waitForSelector('#gate:not([hidden])');
  await page.check('#gate-ok'); await page.click('#gate-go');
  check(true, 'terms gate accepted through the UI');

  /* ---------- PIN: this computer, set your PIN, the bear ---------- */
  await page.waitForSelector('#pin-next');
  const facts = await page.textContent('.pin-facts');
  check(/Device/.test(facts) && /Signed in as/.test(facts) && /AuraSort will ask for your PIN here/.test(await page.textContent('#gate')), '"This computer" shows the device and user name and says the PIN will be asked here');
  await page.mouse.move(5, 5); await page.waitForTimeout(250);
  check(await ev(() => !!document.querySelector('#pal .pp-pupil').getAttribute('transform')), 'the eyes follow the cursor');
  await page.click('#pin-next'); await page.waitForSelector('#pin-a');
  check(await page.getAttribute('#pin-a', 'inputmode') === 'numeric' && await page.getAttribute('#pin-a', 'autocomplete') === 'off', 'PIN fields: numeric keypad, no autofill');
  await page.fill('#pin-a', '1234');
  check(await ev(() => document.querySelector('#pal').classList.contains('is-cover')), 'typing a masked PIN: the bear covers its eyes');
  check(/easy to guess/.test(await page.textContent('#pin-msg')), 'a weak PIN (1234) gets a warning');
  await page.check('#pin-showbox');
  check(await ev(() => document.querySelector('#pal').classList.contains('is-peek')) && await page.getAttribute('#pin-a', 'type') === 'text', '"Show PIN": the bear peeks and the digits show');
  await page.uncheck('#pin-showbox');
  await page.fill('#pin-a', PIN); await page.fill('#pin-b', '4827');
  check(await page.isDisabled('#pin-start') && /different/.test(await page.textContent('#pin-msg')), 'two different PINs: Start stays disabled');
  await page.fill('#pin-b', PIN);
  await page.click('#pin-start');
  await waitFor(() => !!S.info && !S.info.locked && document.querySelector('#gate').hidden);
  check(await ev(() => !localStorage.getItem('aurasort.pin') && !Object.keys(localStorage).some(k => localStorage.getItem(k).includes('4826'))), 'the PIN is not in browser storage');
  check(true, 'PIN set; the app opens');

  /* ---------- scan combinations ---------- */
  await nav('scan');
  await page.click('[data-a=scanmode][data-m=deep]'); await ev(() => { const st = scanSetup(); st.drives = new Set(); st.folders = []; render(false) });
  check(await page.isDisabled('[data-a=scan-start]') && /Pick at least one drive or folder\./.test(await page.textContent('#view')),
    'Deep Scan with nothing picked: Start is disabled and says "Pick at least one drive or folder."');
  await ev(() => startScan()); await page.waitForTimeout(300);
  check((await ev(() => window.__errToasts.splice(0))).some(t => /Pick at least one drive or folder/.test(t)), 'starting anyway (e.g. from the folder picker) is refused on the page, before any request');

  const drives = await ev(() => S.drives.filter(d => d.ready).map(d => d.root));
  if (drives.length) {   // ticking a drive sends a real estimate request (reads names for ~2 s); a whole-drive scan is not started here
    const est = page.waitForResponse(r => r.url().endsWith('/api/scan/estimate'), { timeout: 20000 });
    await page.click(`[data-a=drive][data-r="${drives[0].replace(/\\/g, '\\\\')}"]`);
    const r = await est;
    check(r.status() === 200 && JSON.parse(r.request().postData()).roots.includes(drives[0]), `ticking drive ${drives[0]} sends a valid request (estimate ${r.status()})`);
    await page.click(`[data-a=drive][data-r="${drives[0].replace(/\\/g, '\\\\')}"]`);
  }

  let r = await startScanWith('deep', [P('Music'), P('Downloads')]);
  check(r.s.state === 'done' && r.s.found > 0 && !r.body.drives && r.body.roots.length === 2,
    `THE REPORTED CASE: Deep Scan, 0 drives, 2 folders -> done, ${r.s.found} files`, JSON.stringify(r.s.errors));
  r = await startScanWith('deep', [P('Documents')], [P('Documents', 'MyWebsite')]);
  check(r.s.state === 'done' && r.body.skip.length === 1, `folders + skip folders -> done (${r.s.found} files)`);
  r = await startScanWith('deep', [P('Pictures'), P('No such folder')]);
  check(r.s.state === 'done' && (r.s.skipped || {}).missing_root === 1, 'a missing folder next to a real one is skipped and counted, the scan continues');
  r = await startScanWith('deep', [P('Pictures') + path.sep]);
  check(r.s.state === 'done', 'a folder with a trailing separator works');
  r = await startScanWith('deep', [HOME]);
  check(r.s.state === 'done' && r.s.found > 300, `the whole fake home (unicode, spaces, very long names) -> ${r.s.found} files`);
  r = await startScanWith('quick', []);
  check(r.s.state === 'done' && r.s.found > 0 && r.body.mode === 'quick', `Quick Scan -> ${r.s.found} files`);
  check((await toasts()).length === 0, 'no error toast during the scans');
  await page.screenshot({ path: path.join(OUT, 'pw-01-after-scans.png') });

  /* ---------- the error path, on purpose: a protected folder ---------- */
  await page.waitForTimeout(Math.max(0, lastStart + SCAN_SPACING_MS - Date.now()));
  expecting = 'protected folder refused';
  const prot = process.platform === 'win32' ? 'C:\\Windows' : '/usr';
  await nav('scan');
  await ev(f => { const st = scanSetup(); st.mode = 'deep'; st.drives = new Set(); st.folders = [f]; render(false) }, prot);
  await page.click('[data-a=scan-start]');
  await page.waitForSelector('#toast.err:not([hidden]) [data-a=err-details]');
  const tt = await page.textContent('#toast');
  check(/protected system folder/.test(tt) && !/Error\b|KeyError|Traceback/.test(tt), 'a refused scan shows a short human message', tt);
  check(await page.isVisible('#toast [data-a=err-retry]'), 'the error offers "Try again"');
  await page.click('#toast [data-a=err-details]');
  await page.waitForSelector('#err-text');
  let rep = await page.textContent('#err-text');
  check(/App version: \d/.test(rep) && /code protected/.test(rep) && /logs[\\/]server\.log/.test(rep) && !rep.includes(prot), '"Copy details" report: version, code, log file, and no folder paths', rep);
  await page.check('#err-paths'); rep = await page.textContent('#err-text');
  check(rep.includes(prot), 'folder paths are included only when ticked');
  await ev(() => { const w = navigator.clipboard.writeText.bind(navigator.clipboard); navigator.clipboard.writeText = t => { window.__copied = t; return w(t) } });
  await page.click('[data-a=err-copy]'); await page.waitForTimeout(400);   // (reading the clipboard back is blocked by the app's own Permissions-Policy)
  check((await ev(() => window.__copied || '')).startsWith('AuraSort error report') && /Details copied/.test(await page.textContent('#toast')), 'Copy details puts the report on the clipboard');
  await page.click('[data-a=err-close]');
  await ev(() => window.__errToasts.splice(0));
  expecting = null;
  check(expected.some(x => /HTTP 400/.test(x)) && expected.every(x => /HTTP 400|error toast|console/.test(x)), 'the only errors in that block are the expected 400 and its toast', expected.join(' | '));

  /* ---------- every page ---------- */
  await ev(() => go('dashboard')); await page.waitForTimeout(400);
  const ids = await ev(() => NAV.filter(n => n.id).map(n => n.id));
  for (const v of [...ids, 'extensions', 'folders', 'search', 'timeline']) {
    if (ids.includes(v)) await nav(v); else { await ev(v => go(v), v); await waitFor(v => S.view === v, v).catch(() => {}); await page.waitForTimeout(600) }
    const txt = await page.textContent('#view');
    check(await ev(v => S.view === v, v) && txt.trim().length > 40 && !/undefined|NaN|\[object Object\]/.test(txt), `page "${v}" renders real content`, txt.slice(0, 120));
  }
  check((await toasts()).length === 0, 'no error toast on any page');

  /* ---------- theme ---------- */
  await nav('settings');
  await page.click('[data-a=theme][data-t=light]'); const light = await ev(() => document.documentElement.dataset.theme);
  await page.click('[data-a=theme][data-t=dark]'); const dark = await ev(() => document.documentElement.dataset.theme);
  check(light === 'light' && dark === 'dark', 'theme switches light and dark', `${light}/${dark}`);

  /* ---------- search, format and date filters ---------- */
  await page.fill('#gq', 'concert'); await page.waitForTimeout(800);
  await waitFor(() => S.view === 'search' && !!document.querySelector('#sres .fn-text b'));
  check((await page.$$eval('#sres .fn-text b', b => b.map(x => x.textContent))).some(n => /concert/i.test(n)), 'search finds files by name');
  await page.fill('#gq', ''); await nav('media');
  await page.click('[data-a=tab][data-k="Images"]').catch(() => {}); await page.waitForTimeout(500);
  await page.click('[data-a=fmt][data-x="png"]'); await page.waitForTimeout(800);
  const exts = await page.$$eval('#list .fn-text b, #list .gname', b => b.map(x => x.textContent.split('.').pop().toLowerCase()));
  check(exts.length > 0 && exts.every(x => x === 'png'), `format filter .png shows only png files (${exts.length})`);
  await page.click('[data-a=fmt][data-x="png"]'); await page.waitForTimeout(400);
  await page.click('[data-a=datepop]'); await page.fill('#d-y', '2025'); await page.click('[data-a=dapply][data-m=year]'); await page.waitForTimeout(800);
  check(await ev(() => S.F.date === 'year' && /2025/.test(document.querySelector('[data-a=datepop]').textContent)), 'date filter (year 2025) applies');
  await page.click('[data-a=rmf][data-k=date]').catch(() => ev(() => { S.F.date = ''; S.refresh && S.refresh() }));

  /* ---------- select, preview, move picker, move + undo ---------- */
  const pick = async q => { await page.fill('#gq', q); await page.waitForTimeout(800); await page.waitForSelector('#sres input[data-a=sel]'); await page.click('#sres input[data-a=sel]'); await page.waitForTimeout(200) };
  await page.fill('#gq', 'concert'); await page.waitForTimeout(800);
  await page.click('#sres [data-a=preview]'); await page.waitForSelector('#pv:not([hidden]) .pv-head');
  check(true, 'preview opens'); await page.keyboard.press('Escape'); await page.waitForTimeout(300);
  await pick('concert');
  check(await page.isVisible('#selbar'), 'selecting a file shows the selection bar');
  await page.click('#selbar [data-a=act-move]'); await page.waitForSelector('[data-a=pk-new]:not([disabled])');
  check(/AuraSortFiles.+does not exist yet/.test(await page.textContent('#modal')), 'the move picker opens before the first move, names the missing AuraSortFiles folder, and New folder works');
  await page.click('[data-a=pk-new]'); await page.fill('#pk-name', 'PW picked'); await page.click('[data-a=pk-create]');
  await waitFor(() => Picker.st && /PW picked$/.test(Picker.st.data.path));
  const target = await ev(() => Picker.st.data.path);   // created inside the folder the picker opened (the nearest existing one)
  await page.click('[data-a=pk-here]'); await page.waitForSelector('#ad-ok:not([disabled])'); await page.click('#ad-ok');
  await page.waitForSelector('#pinbox:not([hidden]) #pin-x');
  check(/move or copy these files/.test(await page.textContent('#pinbox')), 'the PIN is asked before the move');
  expecting = 'wrong PIN on purpose';
  await page.fill('#pin-x', '9999'); await page.click('#pin-ok');
  await waitFor(() => /Wrong PIN/.test(document.querySelector('#pinbox #pin-msg').textContent));
  check(await ev(() => document.querySelector('#pal2').classList.contains('is-shake')), 'a wrong PIN: the bear shakes its head and says so');
  await page.waitForTimeout(300); expecting = null;
  await page.fill('#pin-x', PIN); await page.click('#pin-ok');
  await waitFor(() => Stage.finished && !document.querySelector('#st-final').hidden, null, 30000);
  const moved = walk(target);
  check(moved.length === 1 && /concert/i.test(moved[0]), 'move: the selected file is in the new folder', JSON.stringify(moved));
  await page.click('[data-a=st-undo]'); await page.click('[data-a=cf-yes]'); await enterPin();
  await waitFor(() => S.view === 'history', null, 15000);
  check(walk(target).length === 0, 'undo (after the PIN) puts it back (the Undo confirmation is clickable above the move screen)');

  /* ---------- "a file with this name already exists": Replace, then Undo ---------- */
  const name = path.basename(moved[0]);
  fs.writeFileSync(path.join(target, name), 'an older file with the same name');
  await pick('concert');
  await page.click('#selbar [data-a=act-move]'); await page.waitForSelector('[data-a=pk-here]');
  await ev(t => Picker.go(t), target); await waitFor(t => Picker.st && Picker.st.data.path === t, target);
  await page.click('[data-a=pk-here]'); await page.waitForSelector('#ad-ok:not([disabled])'); await page.click('#ad-ok');
  await page.waitForSelector('[data-a=clash-ok]');
  check(/1 file already exists in this folder/.test(await page.textContent('#modal')) && /Coming in/.test(await page.textContent('#modal')), 'the clash is shown side by side before anything moves');
  await page.click('[data-a=clash-all][data-k=replace]'); await page.click('[data-a=clash-ok]'); await enterPin();
  await waitFor(() => Stage.finished && !document.querySelector('#st-final').hidden, null, 30000);
  check(fs.readFileSync(path.join(target, name)).length !== 'an older file with the same name'.length && /replaced/.test(await page.textContent('#st-final')), 'Replace: the new file is in place and the summary says one was replaced');
  await page.click('[data-a=st-undo]'); await page.click('[data-a=cf-yes]'); await enterPin();
  await waitFor(() => S.view === 'history', null, 15000);
  check(fs.readFileSync(path.join(target, name), 'utf8') === 'an older file with the same name', 'Undo after Replace puts the older file back in its place');
  fs.rmSync(path.join(target, name));   // the test's own file

  /* ---------- Recycle Bin (the test bin; the real Recycle Bin is never used) ---------- */
  await pick('setlist');
  await page.click('#selbar [data-a=act-trash]'); await page.waitForSelector('#ad-ok:not([disabled])'); await page.click('#ad-ok');
  await page.waitForSelector('#pinbox:not([hidden]) #pin-no'); await page.click('#pin-no'); await page.waitForTimeout(400);
  check(await page.isHidden('#pinbox') && (await ev(() => window.__errToasts.length)) === 0 && walk(HOME).some(f => f.endsWith('setlist.txt')), 'Cancel at the PIN prompt: nothing happens, no error');
  await page.click('#selbar [data-a=act-trash]'); await page.waitForSelector('#ad-ok:not([disabled])'); await page.click('#ad-ok'); await enterPin();
  await page.waitForSelector('[data-a=bp-done]', { timeout: 15000 });
  check(walk(path.join(HOME, '..', 'test-bin')).some(f => f.endsWith('setlist.txt')), 'Recycle Bin: the file went to the bin, not deleted');
  await page.click('[data-a=bp-done]');

  /* ---------- integrity check ---------- */
  await page.fill('#gq', ''); await nav('corrupted');
  await page.click('[data-a=ck-start]'); await page.waitForSelector('#ck-res .ftable', { timeout: 60000 });
  check(true, 'integrity check runs and lists results');

  /* ---------- Settings and Legal ---------- */
  await nav('settings'); await page.waitForSelector('#set-legal');
  await page.click('#set-legal [data-a=legal][data-doc=privacy]'); await page.waitForSelector('.legal-doc h2');
  check(/Privacy Policy/.test(await page.textContent('.legal-doc')), 'Settings > Legal opens the Privacy Policy');
  await page.click('[data-a=legal-close]');
  await page.click('[data-a=diag-run]'); await page.waitForSelector('#diag-out .diag-list', { timeout: 30000 });
  check(/Test scan/.test(await page.textContent('#diag-out')) && await page.isEnabled('[data-a=diag-copy]'), 'Settings > Diagnostics runs the checks and offers Copy diagnostics');

  /* ---------- lock and unlock ---------- */
  await page.click('[data-a=pin-lock-now]'); await page.waitForSelector('#pin-u');
  check(/Unlock AuraSort/.test(await page.textContent('#gate')), 'Lock now shows the unlock screen');
  expecting = 'wrong PIN on purpose';
  await page.fill('#pin-u', '0000'); await page.click('#pin-go');
  await waitFor(() => /Wrong PIN/.test(document.querySelector('#pin-msg').textContent));
  check(/tries left/.test(await page.textContent('#pin-msg')), 'a wrong PIN says how many tries are left');
  expecting = null;
  await page.fill('#pin-u', PIN); await page.click('#pin-go');
  await waitFor(() => document.querySelector('#gate').hidden && S.view === 'settings', null, 15000);
  check(true, 'the right PIN unlocks and returns to the same page');
  await page.screenshot({ path: path.join(OUT, 'pw-02-end.png') });
  await toasts();
} catch (e) {
  fails++; console.log('FAIL run aborted: ' + (e && e.stack || e));
  await page.screenshot({ path: path.join(OUT, 'pw-crash.png') }).catch(() => {});
} finally {
  await browser.close();
}
check(problems.length === 0, 'no console errors, no failed requests, no error toasts', '\n    ' + problems.join('\n    '));
console.log(`${passes}/${passes + fails} passed`);
process.exit(fails ? 1 : 0);
