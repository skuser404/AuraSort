/* AuraSort - PIN lock: "This computer" + "Set your PIN" on first run, the unlock screen, the PIN prompt before every
   move, copy, delete, undo, replace, data wipe and API-key change, and the idle auto-lock. The server enforces all of it
   (core/pin.py, core/web.py); this file is only the screens. The PIN is sent in a POST body only: never in a URL,
   never in browser storage. */
'use strict';
const PIN_LABELS = { transfer: 'move or copy these files', trash: 'send these files to the Recycle Bin', undo: 'undo this move', delete_data: 'delete AuraSort\'s data',
  ai_key: 'change the API key', settings: 'change security settings' };
const PIN_WEAK = new Set(['1234', '0000', '1111', '1212', '7777', '1004', '2000', '4444', '2222', '6969', '2580', '0852', '123456', '654321', '111111', '000000', '121212', '112233', '159753', '246810', '135790']);
function pinWeak(p) { // Why: the same rule as core/pin.py is_weak: the UI warns, it does not refuse
  if (!/^\d{4}(\d{2})?$/.test(p)) return true;
  const d = [...p].map(Number), steps = new Set(d.slice(1).map((x, i) => x - d[i]));
  return PIN_WEAK.has(p) || new Set(d).size <= 2 || (steps.size === 1 && (steps.has(1) || steps.has(-1)));
}

/* ---------------- the padlock above each PIN form ---------------- */
function pinPal(id) { return `<span class="pin-lock" id="${id}" aria-hidden="true">${ic('lock')}</span>` }
const Pal = { // Why: one short shake on a wrong PIN says "not accepted"; nothing else moves
  set() {}, look() {}, up() {},
  shake(id) { const s = $('#' + id); if (!s) return; s.classList.remove('is-shake'); void s.offsetWidth; s.classList.add('is-shake'); setTimeout(() => s.classList.remove('is-shake'), 400) }
};

/* ---------------- shared PIN field ---------------- */
function pinField(id, label, digits) {
  return `<label class="pin-lbl" for="${id}">${esc(label)}</label>
    <input id="${id}" class="pin-in" type="password" inputmode="numeric" pattern="[0-9]*" autocomplete="off" autocorrect="off" spellcheck="false" maxlength="${digits || 6}" aria-describedby="pin-msg">`;
}
function bindPinInput(input, palId, onEnter) { // Why: digits only; Enter submits
  input.addEventListener('input', () => { input.value = input.value.replace(/\D/g, '').slice(0, +input.maxLength || 6); Pal.set(palId, input.type === 'text' ? 'peek' : input.value ? 'cover' : '') });
  input.addEventListener('focus', () => Pal.set(palId, input.type === 'text' ? 'peek' : 'cover'));
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); onEnter() } });
}
function showToggle(palId, inputs) {
  return el => { el.addEventListener('change', () => { inputs().forEach(i => { i.type = el.checked ? 'text' : 'password' }); Pal.set(palId, el.checked ? 'peek' : 'cover') }) };
}

const Pin = {
  status: null, gateOpen: false, lastActive: Date.now(), idleTimer: null,

  starting: true,   // until the start-up gate is done: a 423 from an early request must not reload the page mid-setup
  async gate() { // Why: nothing else starts until a PIN exists and the app is unlocked
    if (DEMO) { this.starting = false; return }
    try {
      try { this.status = await API.pinStatus() } catch (e) { this.status = null; return }
      if (!this.status.set) await this.firstRun();
      else if (!this.status.unlocked) await this.unlockScreen();
      this.watch();
    } finally { this.starting = false }
  },

  open(html) { const g = $('#gate'); g.innerHTML = html; applyCss(g); g.hidden = false; document.body.classList.add('gated'); this.gateOpen = true; return g },
  close() { const g = $('#gate'); g.hidden = true; g.innerHTML = ''; document.body.classList.remove('gated'); this.gateOpen = false; document.onpointermove = null },

  firstRun() { // Why: (1) Terms (legal.js), (2) this computer, (3) set your PIN, (4) start
    const st = this.status;
    return new Promise(res => {
      this.open(`<div class="gate-card pin-card" role="dialog" aria-modal="true" aria-labelledby="pin-h">
        <div class="pin-hero">${pinPal('pal')}</div><p class="eyebrow">Step 2 of 3</p><h1 id="pin-h">This computer</h1>
        <dl class="pin-facts"><div><dt>Device</dt><dd>${esc(st.device || 'this computer')}</dd></div><div><dt>Signed in as</dt><dd>${esc(st.os_user || '')}</dd></div><div><dt>System</dt><dd>${esc(st.os_name || '')}</dd></div></dl>
        <p>${esc(APP.name)} will ask for your PIN here: when it opens, and before every move, copy, delete, undo or replace.</p>
        <button class="btn pri lg" id="pin-next">Continue</button></div>`);
      $('#pin-next').onclick = () => this.setScreen(res);
      setTimeout(() => $('#pin-next') && $('#pin-next').focus(), 30);
    });
  },

  setScreen(done) {
    let digits = 4;
    const draw = () => {
      this.open(`<div class="gate-card pin-card" role="dialog" aria-modal="true" aria-labelledby="pin-h">
        <div class="pin-hero">${pinPal('pal')}</div><p class="eyebrow">Step 3 of 3</p><h1 id="pin-h">Set your PIN</h1>
        <p class="mut">It protects ${esc(APP.name)} on this computer. It is stored only as a salted, slow hash, never as the PIN itself.</p>
        <div class="seg" role="group" aria-label="PIN length" data-css="margin:12px 0">${[4, 6].map(n => `<button class="${n === digits ? 'on' : ''}" data-n="${n}" aria-pressed="${n === digits}">${n} digits</button>`).join('')}</div>
        ${pinField('pin-a', 'New PIN', digits)}${pinField('pin-b', 'Type it again', digits)}
        <label class="row pin-show"><input type="checkbox" id="pin-showbox"> Show PIN</label>
        <p id="pin-msg" class="pin-msg" role="status"></p>
        <button class="btn pri lg" id="pin-start" disabled>Start ${esc(APP.name)}</button></div>`);
      $$('.pin-card .seg button').forEach(b => b.onclick = () => { digits = +b.dataset.n; draw() });
      const a = $('#pin-a'), b = $('#pin-b'), go = $('#pin-start'), msg = $('#pin-msg');
      let busy = false;   // one submit at a time (typing during it must not re-enable Start)
      const check = () => {
        const ok = a.value.length === digits && b.value === a.value;
        go.disabled = !ok || busy;
        msg.className = 'pin-msg' + (a.value.length === digits && pinWeak(a.value) ? ' warn' : '');
        msg.textContent = b.value && b.value.length >= digits && b.value !== a.value ? 'The two PINs are different.' : a.value.length === digits && pinWeak(a.value) ? 'This PIN is easy to guess (like 1234 or 0000). You can still use it, but a less obvious one is safer.' : '';
      };
      const submit = async () => {
        if (go.disabled || busy) return;
        busy = true; go.disabled = true;
        try { await API.pinSet({ pin: a.value }); Pal.set('pal', 'happy'); Pal.up('pal'); setTimeout(() => { this.close(); done() }, 650) }
        catch (e) { busy = false; msg.className = 'pin-msg err'; msg.textContent = friendly(e); Pal.shake('pal'); go.disabled = false }
      };
      [a, b].forEach(i => { bindPinInput(i, 'pal', submit); i.addEventListener('input', check) });
      showToggle('pal', () => [a, b])($('#pin-showbox'));
      go.onclick = submit;
      setTimeout(() => a.focus(), 30);
    };
    draw();
  },

  unlockScreen() {
    return new Promise(res => {
      const st = this.status || {};
      this.open(`<div class="gate-card pin-card" role="dialog" aria-modal="true" aria-labelledby="pin-h">
        <div class="pin-hero">${pinPal('pal')}</div><h1 id="pin-h">Enter PIN</h1>
        <p class="mut">${esc(st.device || 'This computer')}${st.os_user ? ' · ' + esc(st.os_user) : ''}</p>
        ${pinField('pin-u', 'PIN', st.digits)}
        <label class="row pin-show"><input type="checkbox" id="pin-showbox"> Show PIN</label>
        <p id="pin-msg" class="pin-msg" role="status"></p>
        <div class="row"><button class="btn pri lg" id="pin-go">Unlock</button><button class="btn ghost" id="pin-forgot">Forgot PIN?</button></div></div>`);
      const inp = $('#pin-u'), msg = $('#pin-msg'), go = $('#pin-go');
      let timer = null;
      const wait = s => { // Why: the lockout is real (server-side, kept across restarts); show its countdown
        clearInterval(timer); let left = s; go.disabled = true; inp.disabled = true;
        const tick = () => { msg.className = 'pin-msg err'; msg.textContent = `Too many wrong PINs. Try again in ${left} s.`; if (left-- <= 0) { clearInterval(timer); go.disabled = false; inp.disabled = false; msg.textContent = ''; inp.focus() } };
        tick(); timer = setInterval(tick, 1000);
      };
      const submit = async () => {
        if (go.disabled || !inp.value) return;
        go.disabled = true;
        try {
          await API.pinUnlock({ pin: inp.value }); clearInterval(timer);
          Pal.set('pal', 'happy'); Pal.up('pal'); this.lastActive = Date.now();
          setTimeout(() => { this.close(); res() }, 600);
        } catch (e) {
          inp.value = ''; Pal.shake('pal'); go.disabled = false;
          if (e.code === 'locked_out') wait(e.retry_after || 30); else { msg.className = 'pin-msg err'; msg.textContent = friendly(e) }
        }
      };
      bindPinInput(inp, 'pal', submit);
      showToggle('pal', () => [inp])($('#pin-showbox'));
      go.onclick = submit;
      $('#pin-forgot').onclick = () => this.forgot();
      if (st.locked_for) wait(st.locked_for);
      setTimeout(() => inp.focus(), 30);
    });
  },

  async forgot() { // Why: honest reset: AuraSort's own data is wiped (never your files) and setup starts again
    const ok = await confirmDialog({ title: 'Reset your PIN?', danger: true, ok: 'Reset', typed: 'RESET',
      body: `<p>${esc(APP.name)} cannot recover a forgotten PIN. Resetting removes ${esc(APP.name)}'s own settings, History (including Undo) and file index, then asks for a new PIN.</p><p><b>Your files are not touched.</b> Type RESET to confirm.</p>` });
    if (!ok) return;
    try { await API.pinReset(); location.reload() } catch (e) { toastError(e) }
  },

  async onLocked() { // Why: the server answered 423 (idle lock, or locked in another tab): show the unlock screen, then refresh
    if (this.gateOpen || this.starting || DEMO) return;
    closeModal(); this.closeAsk();
    try { this.status = await API.pinStatus() } catch (e) { return }
    if (!this.status.set) { location.reload(); return }
    await this.unlockScreen();
    try { S.info = await API.info() } catch (e) { /* keep the old facts */ }
    render(false);
  },

  watch() { // Why: auto-lock after the idle time (default 10 minutes); the server applies the same limit
    if (DEMO || this.idleTimer) return;
    const mark = () => { this.lastActive = Date.now() };
    ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach(ev => addEventListener(ev, mark, { passive: true, capture: true }));
    this.idleTimer = setInterval(async () => {
      const mins = (this.status && this.status.idle_min) || 10;
      if (!this.gateOpen && Date.now() - this.lastActive > mins * 60000) { try { await API.pinLock() } catch (e) { /* server may already be locked */ } this.onLocked() }
    }, 15000);
  },

  /* ---------------- the PIN prompt before an action ---------------- */
  closeAsk() { const b = $('#pinbox'); if (b) { b.hidden = true; b.innerHTML = '' } },
  async confirm(action, body) { // Why: returns a single-use token for exactly this request; rejects with code 'pin_cancelled'
    if (DEMO) return 'demo';
    try { this.status = await API.pinStatus() } catch (e) { /* asked below anyway */ }
    if (this.status && this.status.remember_active) {
      try { return (await API.pinVerify({ action, request: body })).action_token } catch (e) { /* fall back to asking */ }
    }
    return new Promise((res, rej) => {
      let box = $('#pinbox');
      if (!box) { box = document.createElement('div'); box.id = 'pinbox'; document.body.appendChild(box) }
      const what = action === 'trash' ? `send these files to ${(S.info && S.info.trash_name) || 'the Recycle Bin'}` : PIN_LABELS[action] || 'continue';
      box.innerHTML = `<div class="pin-ask card" role="dialog" aria-modal="true" aria-labelledby="pin-ask-h"><div class="pin-hero sm">${pinPal('pal2')}</div>
        <h2 id="pin-ask-h">Enter your PIN</h2><p class="mut">to ${esc(what)}.</p>
        ${pinField('pin-x', 'PIN', this.status && this.status.digits)}
        <label class="row pin-show"><input type="checkbox" id="pin-showx"> Show PIN</label>
        <p id="pin-msg" class="pin-msg" role="status"></p>
        <div class="row" data-css="justify-content:flex-end"><button class="btn ghost" id="pin-no">Cancel</button><button class="btn pri" id="pin-ok">Confirm</button></div></div>`;
      applyCss(box); box.hidden = false;
      const inp = $('#pin-x'), msg = $('#pin-msg'), ok = $('#pin-ok');
      const cancel = () => { this.closeAsk(); const e = new Error('Cancelled.'); e.code = 'pin_cancelled'; rej(e) };
      const submit = async () => {
        if (ok.disabled || !inp.value) return;
        ok.disabled = true;
        try { const r = await API.pinVerify({ pin: inp.value, action, request: body }); Pal.set('pal2', 'happy'); Pal.up('pal2'); setTimeout(() => { this.closeAsk(); res(r.action_token) }, 350) }
        catch (e) { inp.value = ''; ok.disabled = false; Pal.shake('pal2'); msg.className = 'pin-msg err'; msg.textContent = friendly(e); if (e.status === 423) { this.closeAsk(); rej(e) } }
      };
      bindPinInput(inp, 'pal2', submit);
      showToggle('pal2', () => [inp])($('#pin-showx'));
      ok.onclick = submit; $('#pin-no').onclick = cancel;
      box.onkeydown = e => { if (e.key === 'Escape') cancel() };
      setTimeout(() => inp.focus(), 30);
    });
  }
};

async function guarded(action, path, body) { // Why: the server refuses these routes without a fresh PIN confirmation for this exact request
  const action_token = await Pin.confirm(action, body);
  return call(path, Object.assign({}, body, { action_token }));
}
