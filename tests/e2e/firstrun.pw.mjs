// The first start, through the real UI: a brand-new home, its own server.py (automatic first scan left on).
//  - After Terms and PIN, a Quick Scan starts by itself (no clicks) and the dashboard shows real numbers.
//  - "Suggested organization: N files into M folders" with Apply; Apply opens the Sort preview and its confirm,
//    and cancelling there moves nothing.
// Usage: node tests/e2e/firstrun.pw.mjs [--pw <folder with node_modules>] [--python python] [--port 8791]
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d };
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const PORT = +arg('port', '8791'), B = `http://localhost:${PORT}`, PIN = '4826';
const pwPath = createRequire(import.meta.url).resolve('playwright', { paths: [process.cwd(), arg('pw', process.cwd())] });
const pwMod = await import(pathToFileURL(pwPath).href), chromium = pwMod.chromium || pwMod.default.chromium;
let fails = 0, passes = 0;
const check = (ok, msg, extra = '') => { ok ? passes++ : fails++; console.log((ok ? 'PASS ' : 'FAIL ') + msg + (!ok && extra ? '  -> ' + extra : '')) };

// a small home with the usual folders (outside AppData: the scanner rightly never enters AppData)
const base = process.env.RUNNER_TEMP || path.join(ROOT, '..');
const tmp = mkdtempSync(path.join(base, 'aurasort-firstrun-')), home = path.join(tmp, 'home');
const files = { Downloads: ['report.pdf', 'photo 1.jpg', 'photo 2.jpg', 'song.mp3', 'notes.docx'], Pictures: ['holiday.png', 'cat.jpg'], Documents: ['budget.xlsx', 'letter.docx'], Videos: ['clip.mp4'] };
for (const [d, names] of Object.entries(files)) { mkdirSync(path.join(home, d), { recursive: true }); for (const n of names) writeFileSync(path.join(home, d, n), 'x'.repeat(2048)) }
const env = { ...process.env, USERPROFILE: home, HOME: home, AURASORT_TEST_TRASH_DIR: path.join(tmp, 'bin'), PYTHONIOENCODING: 'utf-8' };
delete env.AURASORT_NO_AUTO_SCAN;
const srv = spawn(arg('python', 'python'), [path.join(ROOT, 'server.py'), '--no-browser', '--port', String(PORT)], { env, stdio: 'ignore' });
const problems = [];
let browser;
try {
  for (let i = 0; i < 120; i++) { try { if ((await fetch(B + '/')).ok) break } catch { } await new Promise(r => setTimeout(r, 250)) }
  browser = await chromium.launch({ channel: process.env.PW_CHANNEL || 'msedge', headless: true });
  const page = await (await browser.newContext({ viewport: { width: 1366, height: 768 } })).newPage();
  page.on('pageerror', e => problems.push(`page error: ${e.message}`));
  page.on('console', m => { if (m.type() === 'error') problems.push(`console.error: ${m.text()}`) });
  let scanStarts = 0;
  page.on('request', r => { if (r.url().endsWith('/api/scan/start')) scanStarts++ });
  await page.goto(B + '/');
  for (let i = 0; i < 6; i++) {   // the gates, as a person would: Terms, "This computer", set the PIN
    await page.waitForFunction(() => document.querySelector('#gate-ok, #pin-next, #pin-a') || (typeof S !== 'undefined' && S.info && !S.info.locked && document.querySelector('#gate').hidden), null, { timeout: 15000 });
    let sel = null;
    if (await page.$('#gate-ok')) { sel = '#gate-ok'; await page.check('#gate-ok'); await page.click('#gate-go') }
    else if (await page.$('#pin-next')) { sel = '#pin-next'; await page.click('#pin-next') }
    else if (await page.$('#pin-a')) { sel = '#pin-a'; await page.fill('#pin-a', PIN); await page.fill('#pin-b', PIN); await page.click('#pin-start', { timeout: 8000 }) }
    else break;
    await page.waitForFunction(s => !document.querySelector(s), sel, { timeout: 15000 });   // one action per screen
    await page.waitForTimeout(300);
  }
  await page.waitForFunction(() => S.scan && S.scan.state === 'done' && !pollScan.on, null, { timeout: 90000 });
  check(scanStarts === 1, `a Quick Scan started by itself, without a click (${scanStarts} start)`);
  await page.waitForFunction(() => S.view === 'dashboard' && S.summary && S.summary.total > 0, null, { timeout: 15000 }).catch(() => {});
  const total = await page.evaluate(() => S.summary && S.summary.total);
  check(total === 10, `the dashboard shows the files the scan found (${total} of 10)`);
  await page.waitForSelector('#suggest:not([hidden])', { timeout: 15000 }).catch(() => {});
  const sug = ((await page.textContent('#suggest').catch(() => '')) || '').replace(/\s+/g, ' ');
  check(/Suggested organization: \d+ files? into \d+ folders?/.test(sug), 'the dashboard suggests an organization with real numbers', sug.slice(0, 160));
  await page.click('[data-a=suggest-apply]');
  await page.waitForSelector('#modal:not([hidden])', { timeout: 15000 }).catch(() => {});
  const conf = ((await page.textContent('#modal').catch(() => '')) || '').replace(/\s+/g, ' ');
  check(await page.evaluate(() => S.view === 'move') && /Move \d+ files?/.test(conf), 'Apply opens the Sort preview and asks to confirm first', conf.slice(0, 160));
  await page.click('#modal [data-a=cf-no], #modal [data-a=mv-no], #modal .btn.ghost');
  await page.waitForTimeout(500);
  check(Object.entries(files).every(([d, ns]) => ns.every(n => existsSync(path.join(home, d, n)))), 'cancelling moves nothing (every file is still in place)');
  const again = await (await fetch(B + '/')).ok;
  check(again && problems.length === 0, 'no console errors or page errors', problems.join(' | '));
} catch (e) {
  fails++; console.log('FAIL run aborted: ' + (e && e.stack || e));
} finally {
  if (browser) await browser.close();
  srv.kill();
  await new Promise(r => setTimeout(r, 500));
  try { rmSync(tmp, { recursive: true, force: true }) } catch { }
}
console.log(`\n${passes}/${passes + fails} passed`);
process.exit(fails ? 1 : 0);
