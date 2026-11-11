// AuraSort on phones, tablets and laptops, through Playwright against the real server (fixture home).
//  - At 360x800, 412x915 (Pixel 7), 768x1024 and 1366x768, light and dark, every page: FAILS if the page scrolls
//    sideways (document.scrollingElement.scrollWidth > innerWidth) or a visible element sticks out past the right edge.
//    A screenshot of each goes to docs/screenshots/ (JPEG).
//  - Desktop and Pixel 7: a real Quick Scan from the UI must show files.
//  - The drawer menu (open, Esc, closes on navigation), the bottom tabs, and the error banner for a failed API call.
//  - Any console error or non-2xx response outside the block that causes one on purpose fails the run.
// Usage: node tests/e2e/responsive.pw.mjs [--url http://localhost:8799] [--out docs/screenshots] [--pw <folder with node_modules>]
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d };
const B = arg('url', 'http://localhost:8799'), OUT = arg('out', path.join('docs', 'screenshots')), PIN = '4826';
const pwPath = createRequire(import.meta.url).resolve('playwright', { paths: [process.cwd(), arg('pw', process.cwd())] });
const pwMod = await import(pathToFileURL(pwPath).href), chromium = pwMod.chromium || pwMod.default.chromium;
mkdirSync(OUT, { recursive: true });
let fails = 0, passes = 0;
const check = (ok, msg, extra = '') => { ok ? passes++ : fails++; console.log((ok ? 'PASS ' : 'FAIL ') + msg + (!ok && extra ? '  -> ' + extra : '')) };
const problems = []; let expecting = false;
const VIEWPORTS = [[360, 800, 'phone-360'], [412, 915, 'pixel7'], [768, 1024, 'tablet'], [1366, 768, 'desktop']];
const PAGES = ['dashboard', 'scan', 'storage', 'media', 'duplicates', 'large', 'cleanup', 'corrupted', 'move', 'insights', 'history', 'settings', 'help'];

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || 'msedge', headless: true });
async function openApp(w, h, mobile) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: mobile ? 2 : 1 });
  const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error' && !expecting) problems.push(`${w}px console.error: ${m.text()}`) });
  page.on('pageerror', e => problems.push(`${w}px page error: ${e.message}`));
  page.on('response', r => { if (r.status() >= 400 && !expecting) problems.push(`${w}px HTTP ${r.status()} ${r.request().method()} ${r.url().replace(B, '')}`) });
  await page.goto(B + '/');
  try {
    for (let i = 0; i < 6; i++) {   // the gates, through the real UI: Terms, "This computer", set or enter the PIN
      await page.waitForFunction(() => document.querySelector('#gate-ok, #pin-next, #pin-a, #pin-u') || (typeof S !== 'undefined' && S.info && !S.info.locked && document.querySelector('#gate').hidden), null, { timeout: 15000 });
      let sel = null;
      if (await page.$('#gate-ok')) { sel = '#gate-ok'; await page.check('#gate-ok'); await page.click('#gate-go'); }
      else if (await page.$('#pin-next')) { sel = '#pin-next'; await page.click('#pin-next'); }
      else if (await page.$('#pin-a')) { sel = '#pin-a'; await page.fill('#pin-a', PIN); await page.fill('#pin-b', PIN); await page.click('#pin-start', { timeout: 8000 }); }
      else if (await page.$('#pin-u')) { sel = '#pin-u'; await page.fill('#pin-u', PIN); await page.click('#pin-go', { timeout: 8000 }); }
      else break;
      await page.waitForFunction(s => !document.querySelector(s), sel, { timeout: 15000 });   // one action per screen, like a person
      await page.waitForTimeout(300);
    }
  } catch (e) {
    const st = await page.evaluate(() => ({ gate: [...document.querySelectorAll('#gate [id]')].map(x => x.id).join(','), hidden: document.querySelector('#gate').hidden, view: typeof S !== 'undefined' && S.view })).catch(() => ({}));
    await page.screenshot({ path: path.join(OUT, `gate-failure-${w}.png`) }).catch(() => {});
    throw new Error(`stuck at the start-up screens: ${JSON.stringify(st)}: ${e.message.split('\n')[0]}`);
  }
  await page.waitForFunction(() => typeof S !== 'undefined' && S.info && !S.info.locked && document.querySelector('#gate').hidden, null, { timeout: 15000 });
  return { ctx, page };
}
const overflow = page => page.evaluate(() => {
  const W = innerWidth, out = [];
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || el.closest('[hidden], #nav, #tip, #pop')) continue;
    // inside a strip that scrolls sideways on purpose (category tabs, wide tables): reachable by swiping, not a page overflow
    let p = el.parentElement, inScroller = false;
    while (p && p !== document.body) { const o = getComputedStyle(p).overflowX; if ((o === 'auto' || o === 'scroll') && p.getBoundingClientRect().right <= W + 1) { inScroller = true; break } p = p.parentElement }
    if (inScroller) continue;
    const r = el.getBoundingClientRect();
    if (r.width && r.height && r.right > W + 1) out.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}.${String(el.className.baseVal ?? el.className).split(' ').slice(0, 2).join('.')} right=${Math.round(r.right)}`);
  }
  return { scroll: document.scrollingElement.scrollWidth, W, out: out.slice(0, 6) };
});
const go = (page, v) => page.evaluate(v => { go(v); }, v).then(() => page.waitForFunction(v => S.view === v && !document.querySelector('#view .skel'), v, { timeout: 15000 }).catch(() => {})).then(() => page.waitForTimeout(350));

try {
  /* ---------- a real Quick Scan from the phone layout, then from the desktop layout ---------- */
  for (const [w, h, name, mobile] of [[412, 915, 'Pixel 7', true], [1366, 768, 'desktop', false]]) {
    const { ctx, page } = await openApp(w, h, mobile);
    if (mobile) {
      check(await page.isVisible('#tabs') && await page.isVisible('#nav-toggle') && !(await page.isVisible('#nav .nav-i')), `${name}: bottom tabs and a menu button; the sidebar is hidden`);
      await page.click('#nav-toggle'); await page.waitForTimeout(350);
      check(await page.isVisible('#nav .nav-i'), `${name}: the menu button opens the drawer`);
      await page.keyboard.press('Escape'); await page.waitForTimeout(350);
      check(!(await page.isVisible('#nav .nav-i')), `${name}: Esc closes the drawer`);
      await page.click('#nav-toggle'); await page.waitForTimeout(350); await page.click('#nav [data-a=nav][data-v=scan]'); await page.waitForTimeout(400);
      check(!(await page.evaluate(() => document.body.classList.contains('nav-open'))) && await page.evaluate(() => S.view === 'scan'), `${name}: picking a page in the drawer opens it and closes the drawer`);
    } else {
      check(await page.isVisible('#nav .nav-i') && !(await page.isVisible('#tabs')), `${name}: sidebar visible, no bottom tabs`);
      await go(page, 'scan');
    }
    await page.evaluate(() => { const st = scanSetup(); st.mode = 'quick'; render(false) });
    await page.waitForSelector('[data-a=scan-start]:not([disabled])');
    await page.click('[data-a=scan-start]');
    await page.waitForFunction(() => S.scan && !['running', 'paused'].includes(S.scan.state) && !pollScan.on, null, { timeout: 90000 });
    await page.waitForTimeout(600);
    const found = await page.evaluate(() => (S.summary && S.summary.total) || 0);
    check(found > 0, `${name}: a Quick Scan from the UI finds files (${found})`);
    await go(page, 'media');
    const rows = await page.evaluate(() => document.querySelectorAll('#list .ftable tbody tr, #list .grid-item, #list .card').length);
    check(rows > 0, `${name}: Media Explorer lists them (${rows} on the first page)`);
    if (mobile) {
      expecting = true;   // the failed refresh below is on purpose
      await page.route('**/api/summary', r => r.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: 'Something went wrong on our side.', code: 'internal', hint: '' }) }));
      await page.evaluate(() => refreshIndex());
      await page.waitForTimeout(300);
      const warn = await page.textContent('#apiwarn').catch(() => '');
      check(await page.isVisible('#apiwarn') && /HTTP 500/.test(warn), `${name}: a failed API call shows a banner with the status code (never silent zeros)`, warn);
      await page.unroute('**/api/summary'); await page.click('[data-a=apiwarn-close]'); expecting = false;
    }
    await ctx.close();
  }

  /* ---------- a scan that was refused folders: the card with counts and the three choices (360 px) ---------- */
  {
    const { ctx, page } = await openApp(360, 800, true);
    await go(page, 'scan');
    const refused = { state: 'done', found: 0, dirs: 1, bytes: 0, elapsed: 1, roots: ['C:\\'], skipped: { no_access: 1 }, skipped_total: 1,
      skipped_reasons: [{ code: 'no_access', label: 'no permission', n: 1 }], drives: [], notes_list: [],
      explain: [{ code: 'windows_blocked', title: 'Windows refused access to the folders.', body: 'Allow Python in Controlled Folder Access.' }] };
    const elevateCalls = [];
    page.on('request', r => { if (r.url().includes('/api/elevate')) elevateCalls.push(r.url()) });
    await page.route('**/api/scan/status', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(refused) }));
    await page.evaluate(() => pollScan());
    await page.waitForSelector('.scan-explain', { timeout: 15000 });
    const card = (await page.textContent('.scan-explain')).replace(/\s+/g, ' ');
    check(/Found no files in 1 folders/.test(card) && /Skipped: 1 no permission/.test(card), '360px: the card shows the exact counts (files, folders, skipped by reason)', card.slice(0, 200));
    check(await page.isVisible('[data-a=perm-pick]') && await page.isVisible('[data-a=perm-why]'), '360px: "Choose folders to scan" and "Why was access denied?" are offered');
    const info = await page.evaluate(() => ({ os: S.info.os, admin: S.info.admin }));
    check((await page.isVisible('[data-a=perm-elevate]')) === (info.os === 'windows' && !info.admin), `360px: "Restart with administrator permission" only on Windows without it (os ${info.os}, admin ${info.admin})`);
    await page.click('[data-a=perm-why]');
    const why = await page.textContent('#modal');
    check(info.os !== 'windows' || /Controlled Folder Access/.test(why), '360px: "Why was access denied?" names this system\'s usual causes', why.slice(0, 160));
    await page.click('#modal [data-a=cf-no]');
    if (info.os === 'windows' && !info.admin) {
      await page.click('[data-a=perm-elevate]');
      check(/administrator permission/.test(await page.textContent('#modal')), '360px: the administrator restart asks first');
      await page.click('#modal [data-a=cf-no]'); await page.waitForTimeout(300);
      check(elevateCalls.length === 0, '360px: cancelling the administrator restart changes nothing (no request sent)');
    }
    await page.click('[data-a=perm-pick]');
    check(await page.waitForSelector('#modal:not([hidden])', { timeout: 8000 }).then(() => true, () => false), '360px: "Choose folders to scan" opens the folder picker');
    await page.keyboard.press('Escape');
    const o = await overflow(page);
    check(o.scroll <= o.W && !o.out.length, '360px: the card fits without sideways scrolling', JSON.stringify(o.out));
    await page.unroute('**/api/scan/status');
    // Move / Copy / Delete are always offered on a phone: in the selection bar and in the preview, on screen and not covered
    await go(page, 'media');
    const reach = sel => page.evaluate(s => { const el = document.querySelector(s); if (!el) return 'missing';
      el.scrollIntoView({ block: 'center' }); const r = el.getBoundingClientRect(), top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth && top && (top === el || el.contains(top)) ? 'ok' : 'not reachable' }, sel);
    await page.check('#view input[data-a=sel]');
    const bar = await Promise.all(['act-move', 'act-copy', 'act-trash'].map(a => reach(`#selbar [data-a=${a}]`)));
    check(bar.every(x => x === 'ok'), '360px: the selection bar offers Move, Copy and Delete, on screen and clickable', bar.join(','));
    await page.click('[data-a=selclear]');
    await page.evaluate(() => ACT.preview({ dataset: { id: document.querySelector('#view input[data-a=sel]').dataset.id } }));
    await page.waitForSelector('#pv [data-a=pv-move]', { timeout: 10000 });
    const pv = await Promise.all(['pv-move', 'pv-copyto', 'pv-trash'].map(a => reach(`#pv [data-a=${a}]`)));
    check(pv.every(x => x === 'ok'), '360px: the preview offers Move, Copy and Delete, on screen and clickable', pv.join(','));
    await ctx.close();
  }

  /* ---------- every page, every size, both themes: no sideways scrolling ---------- */
  for (const [w, h, label] of VIEWPORTS) {
    const { ctx, page } = await openApp(w, h, w < 900);
    const bad = [];
    for (const theme of ['light', 'dark']) {
      await page.evaluate(t => setTheme(t), theme);
      for (const v of PAGES) {
        await go(page, v);
        const o = await overflow(page);
        if (o.scroll > o.W || o.out.length) bad.push(`${theme}/${v}: scrollWidth ${o.scroll} > ${o.W}${o.out.length ? '; sticking out: ' + o.out.join(', ') : ''}`);
        await page.screenshot({ path: path.join(OUT, `${label}-${theme}-${v}.jpg`), type: 'jpeg', quality: 62, fullPage: false });
      }
    }
    check(bad.length === 0, `${label} (${w}x${h}): ${PAGES.length} pages x 2 themes without sideways scrolling or clipped elements`, '\n    ' + bad.join('\n    '));
    await ctx.close();
  }
} catch (e) {
  fails++; console.log('FAIL run aborted: ' + (e && e.stack || e));
} finally {
  await browser.close();
}
check(problems.length === 0, 'no console errors and no failed requests', '\n    ' + problems.slice(0, 20).join('\n    '));
console.log(`${passes}/${passes + fails} passed`);
process.exit(fails ? 1 : 0);
