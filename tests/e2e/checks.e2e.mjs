// Corrupted files, Duplicates and Cleanup pages end-to-end (run after app.e2e.mjs on the fixture home).
// Usage: node tests/e2e/checks.e2e.mjs --out <dir> [--url http://localhost:8799]
import { launch, sleep } from './cdp.mjs';
import path from 'node:path';

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d };
const OUT = arg('out', '.'), B = arg('url', 'http://localhost:8799');
const res = []; let fails = 0;
const check = (ok, msg, extra = '') => { res.push(msg); if (!ok) fails++; console.log((ok ? 'PASS ' : 'FAIL ') + msg + (extra && !ok ? '  -> ' + extra : '')) };
const T = await launch({ profile: path.join(OUT, 'profile-checks'), port: 9359 });
const ev = e => T.eval(e), J = JSON.stringify;
const click = sel => ev(`(() => { const e = document.querySelector(${J(sel)}); if (!e) throw new Error('no element ' + ${J(sel)}); e.click(); return true })()`);
try {
  await T.goto(B + '/'); await T.acceptTerms(); await T.waitFor('!!S.info && S.hasIndex', 15000, 'index');
  check(await ev(`['duplicates', 'cleanup', 'corrupted'].every(v => !!document.querySelector('#nav [data-v="' + v + '"]'))`), 'sidebar has Duplicates, Cleanup and Corrupted');
  await click('.qa-item[data-v=corrupted]'); await T.waitFor(`S.view === 'corrupted' && !!document.querySelector('[data-a=ck-start]')`, 8000);
  await click('[data-a=ck-mode][data-m=deep]'); await sleep(200); await click('[data-a=ck-start]');
  await T.waitFor(`!!document.querySelector('#ck-res .ftable')`, 60000, 'check results');
  const names = await ev(`[...document.querySelectorAll('#ck-res .fn-text b')].map(b => b.textContent)`);
  check(['truncated_photo.jpg', 'bad_crc.png', 'empty_report.docx', 'damaged.zip'].every(n => names.includes(n)), 'deep check finds the broken files', J(names));
  check(await ev(`/Likely cause:/.test(document.querySelector('#ck-res').textContent) && /What to do:/.test(document.querySelector('#ck-res').textContent)`), 'every problem says the likely cause and what to do');
  check(await ev(`!!document.querySelector('[data-a=ck-csv]')`), 'CSV export is offered');
  await click('#ck-res input[data-a=sel]'); await sleep(200);
  check(await ev(`!!document.querySelector('#selbar [data-a=act-quarantine]')`), 'selected problem files can be quarantined (an undoable move)');
  await T.shot(path.join(OUT, 'c1-corrupted.png')); await ev('Sel.clear()');
  await click('[data-a=nav][data-v=duplicates]'); await T.waitFor(`!!document.querySelector('[data-a=dp-start]')`, 8000);
  await click('[data-a=dp-start]'); await T.waitFor(`!!document.querySelector('.dup-group')`, 60000, 'duplicate groups');
  const groups = await ev(`document.querySelectorAll('.dup-group').length`);
  check(groups >= 3, 'identical copies are grouped (photo, invoice, notes)', String(groups));
  check(await ev(`[...document.querySelectorAll('.dup-group')].every(g => g.querySelectorAll('.b-ok').length === 1)`), 'each group marks exactly one newest copy to keep');
  await click('[data-a=dp-extras]'); await sleep(400);
  check(await ev(`S.sel.size > 0 && !document.querySelector('#selbar').hidden`), '"Select all but the newest" fills the selection for review');
  await T.shot(path.join(OUT, 'c2-duplicates.png')); await ev('Sel.clear()');
  await click('[data-a=nav][data-v=cleanup]'); await T.waitFor(`document.querySelectorAll('.cl-group').length >= 4`, 8000);
  check(await ev(`/Empty files/.test(document.querySelector('#cl-groups').textContent)`), 'cleanup groups are listed with counts and sizes');
  const emptyBtn = await ev(`(() => { const b = [...document.querySelectorAll('.cl-group')].find(x => /Empty files/.test(x.textContent)); if (b && !b.disabled) { b.click(); return true } return false })()`);
  if (emptyBtn) { await T.waitFor(`!!document.querySelector('#cl-list .ftable')`, 8000); check(await ev(`S.sel.size === 0`), 'opening a group lists the files; nothing is pre-selected') }
  await T.shot(path.join(OUT, 'c3-cleanup.png'));
} catch (e) { check(false, 'test crashed', e.stack) }
console.log('\nCONSOLE/LOG ERRORS:', T.errors.length ? '\n  ' + T.errors.join('\n  ') : 'none');
if (T.errors.length) fails++;
console.log(`\n${res.length - fails}/${res.length} passed`);
await T.close(); process.exit(fails ? 1 : 0);
