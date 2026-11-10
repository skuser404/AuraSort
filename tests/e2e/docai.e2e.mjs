// Document Insights end-to-end, against a mock Ollama on 127.0.0.1 (no real engine needed). Run after app.e2e.mjs.
// Usage: node tests/e2e/docai.e2e.mjs --out <dir> [--url http://localhost:8799]
import { launch, sleep } from './cdp.mjs';
import http from 'node:http';
import path from 'node:path';

const arg = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d };
const OUT = arg('out', '.'), B = arg('url', 'http://localhost:8799');
const res = []; let fails = 0;
const check = (ok, msg, extra = '') => { res.push(msg); if (!ok) fails++; console.log((ok ? 'PASS ' : 'FAIL ') + msg + (extra && !ok ? '  -> ' + extra : '')) };
const seen = [];
const mock = http.createServer((req, rsp) => { // a tiny Ollama: /api/tags and /api/chat
  let body = ''; req.on('data', c => { body += c }); req.on('end', () => {
    seen.push(req.method + ' ' + req.url);
    const send = o => { rsp.writeHead(200, { 'Content-Type': 'application/json' }); rsp.end(JSON.stringify(o)) };
    if (req.url === '/api/tags') return send({ models: [{ name: 'mock:3b', size: 2e9 }] });
    const doc = JSON.parse(JSON.parse(body).messages[1].content), ex = doc.excerpt.toLowerCase();
    const t = ex.includes('statement') ? 'bank statement' : ex.includes('curriculum') ? 'resume' : ex.includes('invoice') ? 'invoice' : 'notes';
    send({ message: { content: JSON.stringify({ doc_type: t, description: `A ${t} named ${doc.file_name}.`, key_fields: ['dates'], junk_likelihood: ex.includes('ignore previous') ? 'high' : 'low',
      suggested_action: ex.includes('ignore previous') ? 'delete-candidate' : 'keep', sensitivity: 'normal', sensitivity_reason: '' }) } });
  });
});
await new Promise(r => mock.listen(0, '127.0.0.1', r));
const MOCK = `http://127.0.0.1:${mock.address().port}`;
const T = await launch({ profile: path.join(OUT, 'profile-docai'), port: 9357 });
const ev = e => T.eval(e), J = JSON.stringify;
const click = sel => ev(`(() => { const e = document.querySelector(${J(sel)}); if (!e) throw new Error('no element ' + ${J(sel)}); e.click(); return true })()`);
const api = (p, b) => ev(`fetch('/api/${p}', { method: ${b ? "'POST'" : "'GET'"}, headers: { 'X-AuraSort-Token': TOKEN, 'Content-Type': 'application/json' }${b ? `, body: ${J(J(b))}` : ''} }).then(r => r.json())`);
try {
  await T.goto(B + '/?view=insights'); await T.acceptTerms(); await T.waitFor('!!S.info && S.hasIndex', 15000, 'index');
  await api('ai/reset', {});
  await click('[data-a=instab][data-k=documents]'); await T.waitFor(`!!document.querySelector('#ai-enable')`, 8000);
  check(await ev(`document.querySelector('#ai-enable').disabled`), 'off by default: the turn-on button needs the consent tick');
  check(await ev(`/only suggests/.test(document.querySelector('#ins').textContent) && /Nothing is read or sent/.test(document.querySelector('#ins').textContent)`), 'first-run screen explains what it reads and that it only suggests');
  await T.shot(path.join(OUT, 'd1-docai-first-run.png'));
  await ev(`(() => { const c = document.querySelector('#ai-consent'); c.checked = true; c.dispatchEvent(new Event('change', { bubbles: true })) })()`);
  await click('#ai-enable'); await T.waitFor(`!!document.querySelector('#ai-run')`, 8000);
  check(await ev(`/No engine found|not running/.test(document.querySelector('#ins').textContent)`), 'without an engine it shows setup steps and download links');
  await api('ai/settings', { settings: { local_url: MOCK } });
  await T.reload(); await T.waitFor('!!S.info', 8000); await click('[data-a=instab][data-k=documents]');
  await T.waitFor(`!!document.querySelector('[data-c=ai-model]')`, 8000);
  await ev(`(() => { const s = document.querySelector('[data-c=ai-model]'); s.value = 'mock:3b'; s.dispatchEvent(new Event('change', { bubbles: true })) })()`);
  await T.waitFor(`!!document.querySelector('input[name=ai-mode][value=local]:not([disabled])')`, 8000);
  check(true, 'engine detected on 127.0.0.1 and the installed model can be chosen');
  await ev(`document.querySelector('input[name=ai-mode][value=local]').checked = true`); await click('#ai-go');
  await T.waitFor(`!!document.querySelector('.ai-banner')`, 60000, 'results');
  await sleep(500);
  const banner = await ev(`document.querySelector('.ai-banner').textContent`);
  check(/Completed\. \d+ documents read, \d+ confidential/.test(banner), 'banner: "Completed. N documents read, K confidential."', banner);
  check(await ev(`/Results clear in \\d+:\\d\\d/.test(document.querySelector('#ai-clock').textContent)`), 'visible countdown until results clear');
  const rows = await ev(`[...document.querySelectorAll('.ai-table tbody tr')].map(r => ({ name: r.querySelector('.fn-text b').textContent, cls: r.className, txt: r.textContent }))`);
  const by = n => rows.find(r => r.name === n) || { cls: '', txt: '' };
  check(/lvl-confidential/.test(by('march_bank_statement.docx').cls) && /Card number/.test(by('march_bank_statement.docx').txt), 'bank statement flagged Confidential with reason chips');
  check(/lvl-confidential/.test(by('id_copies.pdf').cls) && /PAN number/.test(by('id_copies.pdf').txt), 'ID copies flagged Confidential even though the model said "normal"');
  check(!rows.some(r => /4111 ?1111 ?1111 ?1111|ABCPE1234F/.test(r.txt)), 'matched values are masked, never shown');
  check(/lvl-normal/.test(by('furniture_invoice.txt').cls), 'a normal invoice is not flagged');
  check(/likely junk/.test(by('read_me_first.txt').txt), 'the prompt-injection note is just labelled; nothing else happens');
  await ev(`document.querySelector('.ai-banner').scrollIntoView()`); await sleep(300); await T.shot(path.join(OUT, 'd2-docai-results.png'));
  await click('[data-a=ai-sens][data-k=confidential]'); await sleep(800);
  check(/sens=confidential/.test(await ev('location.search')) && await ev(`[...document.querySelectorAll('.ai-table tbody tr')].every(r => r.classList.contains('lvl-confidential'))`), 'sensitivity filter works and is in the URL');
  await ev(`setTheme('light')`); await sleep(400); await T.shot(path.join(OUT, 'd3-docai-results-light.png')); await ev(`setTheme('dark')`);
  await click('[data-a=ai-connect]'); await T.waitFor(`!!document.querySelector('#cl-key')`, 5000);
  check(await ev(`document.querySelector('#cl-key').type === 'password' && /API keys/.test(document.querySelector('#modal').textContent) && /China/.test(document.querySelector('#modal').textContent)`), 'cloud connect: API key (not a password), privacy warning shown');
  await T.shot(path.join(OUT, 'd4-docai-connect.png'));
  await click('[data-a=cf-no]');
  check(seen.every(s => /^(GET \/api\/tags|POST \/api\/chat)$/.test(s)), 'only the local engine was contacted', J([...new Set(seen)]));
  await click('[data-a=ai-clear]'); await sleep(800);
  check(await ev(`!document.querySelector('.ai-banner')`), 'Clear now removes every result');
  await api('ai/reset', {});
} catch (e) { check(false, 'test crashed', e.stack) }
console.log('\nCONSOLE/LOG ERRORS:', T.errors.length ? '\n  ' + T.errors.join('\n  ') : 'none');
if (T.errors.length) fails++;
console.log(`\n${res.length - fails}/${res.length} passed`);
await T.close(); mock.close(); process.exit(fails ? 1 : 0);
