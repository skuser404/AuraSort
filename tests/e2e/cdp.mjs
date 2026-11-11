// Minimal Chrome DevTools Protocol driver for headless Edge (Node 22+: global WebSocket/fetch).
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

export const sleep = ms => new Promise(r => setTimeout(r, ms));
export const E2E_PIN = '4826';   // the PIN every browser suite sets on a fresh fixture (not a weak one, so no warning)

export async function launch({ port = 9333, profile, width = 1440, height = 900 }) {
  mkdirSync(profile, { recursive: true });
  const exe = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
  const proc = spawn(exe, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--disable-features=msEdgeSidebar', ...(process.env.GPU ? ['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=d3d11', '--enable-gpu-rasterization'] : []), `--window-size=${width},${height}`, 'about:blank'], { stdio: 'ignore' });
  let ver;
  for (let i = 0; i < 60; i++) { try { ver = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json(); break } catch { await sleep(250) } }
  if (!ver) throw new Error('edge did not start');
  const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = list.find(t => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej });
  let id = 0; const pending = new Map(), listeners = [];
  ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const { res, rej } = pending.get(m.id); pending.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result) } else listeners.forEach(l => l(m)) };
  let gone = '';
  const dropAll = why => { gone = gone || why; for (const { rej } of pending.values()) rej(new Error(gone)); pending.clear() };
  ws.onclose = ev => dropAll(`browser connection closed (code ${ev.code}${ev.reason ? ', ' + ev.reason : ''})`);  // Why: otherwise awaits hang and Node exits with "unsettled top-level await"
  const send = (method, params = {}) => new Promise((res, rej) => { if (gone) return rej(new Error(gone)); const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })) });
  proc.on('exit', (code, sig) => dropAll(`browser exited (code ${code}, signal ${sig})`));
  const errors = [];
  listeners.push(m => {
    if (m.method === 'Runtime.exceptionThrown') errors.push('EXCEPTION ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
    if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning', 'assert'].includes(m.params.type)) errors.push('CONSOLE.' + m.params.type + ' ' + m.params.args.map(a => a.value ?? a.description).join(' '));
    if (m.method === 'Log.entryAdded' && ['error', 'warning'].includes(m.params.entry.level)) errors.push('LOG.' + m.params.entry.level + ' ' + m.params.entry.text + ' ' + (m.params.entry.url || ''));
    if (m.method === 'Inspector.targetCrashed') dropAll('the page crashed (renderer process died)');
    if (m.method === 'Page.javascriptDialogOpening') { send('Page.handleJavaScriptDialog', { accept: true }); dialogs.push(m.params.message) }
  });
  const dialogs = [];
  await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable'); await send('Inspector.enable');
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
  // Every per-action PIN prompt (#pinbox) is answered like a person would: type the PIN, press Confirm.
  await send('Page.addScriptToEvaluateOnNewDocument', { source: `(() => {
    const PIN = ${JSON.stringify(E2E_PIN)};
    new MutationObserver(() => { const i = document.querySelector('#pinbox:not([hidden]) #pin-x'), ok = document.querySelector('#pin-ok');
      if (i && ok && !i.dataset.e2e && !window.__e2eNoAutoPin) { i.dataset.e2e = 1; i.value = PIN; i.dispatchEvent(new Event('input')); setTimeout(() => ok.click(), 60) } })
      .observe(document, { childList: true, subtree: true });
  })()` });
  const api = {
    send, errors, dialogs, proc,
    async eval(expr, awaitPromise = true) {
      const r = await send('Runtime.evaluate', { expression: expr, awaitPromise, returnByValue: true });
      if (r.exceptionDetails) throw new Error('eval failed: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text) + '\n  in: ' + expr.slice(0, 200));
      return r.result.value;
    },
    async goto(url) { const done = new Promise(res => { const l = m => { if (m.method === 'Page.loadEventFired') { listeners.splice(listeners.indexOf(l), 1); res() } }; listeners.push(l) }); await send('Page.navigate', { url }); await done; await sleep(300) },
    async reload() { const done = new Promise(res => { const l = m => { if (m.method === 'Page.loadEventFired') { listeners.splice(listeners.indexOf(l), 1); res() } }; listeners.push(l) }); await send('Page.reload', {}); await done; await sleep(300) },
    async waitFor(expr, ms = 15000, label = expr) { const t0 = Date.now(); while (Date.now() - t0 < ms) { try { if (await api.eval(expr)) return true } catch { } await sleep(120) } throw new Error('timeout waiting for: ' + label) },
    async shot(file, opts = {}) { const r = await send('Page.captureScreenshot', { format: 'png', ...opts }); writeFileSync(file, Buffer.from(r.data, 'base64')); return file },
    async acceptTerms() { // the first-run "Before you start" gate: tick and continue, through the real UI
      await api.waitFor(`(document.querySelector('#gate') && !document.querySelector('#gate').hidden) || (typeof S !== 'undefined' && !!S.info)`, 15000, 'gate or app');
      if (await api.eval(`!!document.querySelector('#gate') && !document.querySelector('#gate').hidden`)) {
        await api.eval(`(() => { const c = document.querySelector('#gate-ok'); c.checked = true; c.dispatchEvent(new Event('change')); document.querySelector('#gate-go').click(); return true })()`);
        await sleep(300);
      }
      await api.passPin();
    },
    async passPin() { // "This computer" -> "Set your PIN" on first run, or the unlock screen: through the real UI
      for (let i = 0; i < 4; i++) {
        await api.waitFor(`!!document.querySelector('#pin-next, #pin-a, #pin-u') || (typeof S !== 'undefined' && !!S.info)`, 15000, 'PIN screen or app');
        const step = await api.eval(`document.querySelector('#pin-next') ? 'device' : document.querySelector('#pin-a') ? 'set' : document.querySelector('#pin-u') ? 'unlock' : ''`);
        if (!step) return;
        const type = (sel) => `(() => { const e = document.querySelector('${sel}'); e.value = ${JSON.stringify(E2E_PIN)}; e.dispatchEvent(new Event('input')); return true })()`;
        if (step === 'device') await api.eval(`document.querySelector('#pin-next').click()`);
        if (step === 'set') { await api.eval(type('#pin-a')); await api.eval(type('#pin-b')); await api.eval(`document.querySelector('#pin-start').click()`) }
        if (step === 'unlock') { await api.eval(type('#pin-u')); await api.eval(`document.querySelector('#pin-go').click()`) }
        const sel = { device: '#pin-next', set: '#pin-a', unlock: '#pin-u' }[step];   // one submit per screen: wait until it is gone
        await api.waitFor(`!document.querySelector('${sel}')`, 10000, step + ' screen closes');
        await sleep(200);
      }
    },
    async size(width, height, mobile = false) { await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile }) },
    async close() { try { ws.close() } catch { } proc.kill() }
  };
  return api;
}
