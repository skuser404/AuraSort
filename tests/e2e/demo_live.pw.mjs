// The public demo (GitHub Pages, or any static server): it must work with no AuraSort server at all.
// At desktop (1366x768) and phone (412x915) size: the "Demo mode, sample data only" strip is shown, the app never calls
// /api, a demo scan fills the dashboard with sample files, and there are no console errors and no 404s.
// Usage: node tests/e2e/demo_live.pw.mjs [--url https://skuser404.github.io/AuraSort/demo/] [--site https://skuser404.github.io/AuraSort/] [--pw <dir>]
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d };
const URL_ = arg('url', 'https://skuser404.github.io/AuraSort/demo/'), SITE = arg('site', '');
const pwPath = createRequire(import.meta.url).resolve('playwright', { paths: [process.cwd(), arg('pw', process.cwd())] });
const pwMod = await import(pathToFileURL(pwPath).href), chromium = pwMod.chromium || pwMod.default.chromium;
let fails = 0, passes = 0;
const check = (ok, msg, extra = '') => { ok ? passes++ : fails++; console.log((ok ? 'PASS ' : 'FAIL ') + msg + (!ok && extra ? '  -> ' + extra : '')) };
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined, headless: true });
try {
  if (SITE) {
    const page = await browser.newPage();
    const r = await page.goto(SITE);
    check(r && r.status() === 200 && /AuraSort/.test(await page.title()), `website ${SITE} answers 200 with the AuraSort title`, String(r && r.status()));
    check(await page.$('a[href*="demo/"]') !== null, 'the website links to the demo');
    await page.close();
  }
  for (const [w, h, name] of [[1366, 768, 'desktop'], [412, 915, 'phone']]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, isMobile: w < 900, hasTouch: w < 900 });
    const page = await ctx.newPage(), problems = [], api = [];
    page.on('console', m => { if (m.type() === 'error') problems.push('console: ' + m.text()) });
    page.on('pageerror', e => problems.push('page error: ' + e.message));
    page.on('response', r => { if (r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url()}`) });
    page.on('request', r => { if (/\/api\//.test(r.url())) api.push(r.url()) });
    const r = await page.goto(URL_);
    check(r && r.status() === 200, `${name}: ${URL_} answers 200`, String(r && r.status()));
    await page.waitForSelector('#gate-ok', { timeout: 20000 }); await page.check('#gate-ok'); await page.click('#gate-go');
    await page.waitForFunction(() => typeof S !== 'undefined' && S.info && document.querySelector('#gate').hidden, null, { timeout: 15000 });
    check(await page.isVisible('#demo-strip') && /sample data only/.test(await page.textContent('#demo-strip')), `${name}: "Demo mode, sample data only" is shown`);
    await page.evaluate(() => { go('scan') }); await page.waitForSelector('[data-a=scan-start]:not([disabled])');
    await page.click('[data-a=scan-start]');
    await page.waitForFunction(() => S.hasIndex && S.summary && S.summary.total > 0, null, { timeout: 60000 });
    const total = await page.evaluate(() => S.summary.total);
    await page.evaluate(() => { go('dashboard') }); await page.waitForTimeout(800);
    check(total > 0 && /Dashboard/.test(await page.textContent('#view')), `${name}: a demo scan shows the dashboard with ${total} sample files`);
    check(api.length === 0, `${name}: the demo never calls the AuraSort API`, api.slice(0, 3).join(', '));
    check(problems.length === 0, `${name}: no console errors and no failed requests (404s)`, problems.slice(0, 8).join(' | '));
    if (w < 900) {
      const o = await page.evaluate(() => document.scrollingElement.scrollWidth - innerWidth);
      check(o <= 0, `${name}: no sideways scrolling`, `${o}px too wide`);
    }
    await ctx.close();
  }
} catch (e) {
  fails++; console.log('FAIL run aborted: ' + (e && e.stack || e));
} finally {
  await browser.close();
}
console.log(`${passes}/${passes + fails} passed`);
process.exit(fails ? 1 : 0);
