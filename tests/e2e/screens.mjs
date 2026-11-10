// Screenshots of every page in both themes at 1440x900 and 1100x700 (run after app.e2e.mjs so an index exists).
// Usage: node tests/e2e/screens.mjs --out <dir> [--url http://localhost:8799]
import { launch, sleep } from './cdp.mjs';
import path from 'node:path';

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d };
const OUT = arg('out', '.'), B = arg('url', 'http://localhost:8799');
const PAGES = ['dashboard', 'storage', 'extensions', 'folders', 'media', 'search', 'timeline', 'duplicates', 'large', 'cleanup', 'corrupted', 'move', 'insights', 'history', 'settings', 'help', 'scan'];
const SIZES = [[1440, 900], [1100, 700]];
const T = await launch({ profile: path.join(OUT, 'profile-screens'), port: 9355 });
const ev = e => T.eval(e);
let n = 0, problems = [];
try {
  await T.goto(B + '/'); await T.acceptTerms(); await T.waitFor('!!S.info && S.hasIndex', 15000, 'index (run app.e2e.mjs first)');
  for (const theme of ['dark', 'light']) {
    await ev(`setTheme(${JSON.stringify(theme)})`);
    for (const [w, h] of SIZES) {
      await T.size(w, h);
      for (const p of PAGES) {
        await T.goto(`${B}/?view=${p}${p === 'search' ? '&q=light' : ''}`); await T.waitFor('!!S.info', 10000); await sleep(1300);
        const txt = await ev(`document.body.innerText`);
        if (/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}]/u.test(txt)) problems.push(`emoji on ${p}`);
        if (await ev(`!!document.querySelector('use[href*="sparkle"]')`)) problems.push(`sparkle on ${p}`);
        if (await ev(`document.documentElement.scrollWidth > innerWidth + 1`)) problems.push(`horizontal scroll on ${p} at ${w}`);
        await T.shot(path.join(OUT, `p-${theme}-${w}-${p}.png`)); n++;
      }
    }
  }
} catch (e) { problems.push('crashed: ' + e.message) }
console.log(`${n} screenshots`); console.log(problems.length ? 'PROBLEMS:\n  ' + problems.join('\n  ') : 'no emoji, no sparkle, no horizontal scroll');
console.log('CONSOLE/LOG ERRORS:', T.errors.length ? T.errors.join(' | ') : 'none');
await T.close(); process.exit(problems.length || T.errors.length ? 1 : 0);
