// Minimal Chrome DevTools Protocol driver for headless Edge (Node 22+: global WebSocket/fetch).
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

export const sleep = ms => new Promise(r => setTimeout(r, ms));

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
  const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })) });
  const errors = [];
  listeners.push(m => {
    if (m.method === 'Runtime.exceptionThrown') errors.push('EXCEPTION ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
    if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning', 'assert'].includes(m.params.type)) errors.push('CONSOLE.' + m.params.type + ' ' + m.params.args.map(a => a.value ?? a.description).join(' '));
    if (m.method === 'Log.entryAdded' && ['error', 'warning'].includes(m.params.entry.level)) errors.push('LOG.' + m.params.entry.level + ' ' + m.params.entry.text + ' ' + (m.params.entry.url || ''));
    if (m.method === 'Page.javascriptDialogOpening') { send('Page.handleJavaScriptDialog', { accept: true }); dialogs.push(m.params.message) }
  });
  const dialogs = [];
  await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'no-preference' }] });
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
    },
    async size(width, height, mobile = false) { await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile }) },
    async close() { try { ws.close() } catch { } proc.kill() }
  };
  return api;
}
