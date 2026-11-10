/* AuraSort - count-ups, ring/gauge animation and the cinematic move stage (real files, real numbers). */
'use strict';
function countUps(root) { // Why: numbers count up to their real value (instant with reduced motion)
  $$('[data-count]', root).forEach(el => {
    const to = Number(el.dataset.count), f = el.dataset.f === 'sz' ? sz : el.dataset.f === 'pct' ? (n => Math.round(n) + '%') : fmt;
    if (!motion() || !isFinite(to)) { el.textContent = f(to); return }
    const t0 = performance.now(), D = 250;
    const step = n => { const k = Math.min(1, (n - t0) / D); el.textContent = f(to * easeOut(k)); if (k < 1 && el.isConnected) requestAnimationFrame(step) };
    requestAnimationFrame(step);
  });
  $$('[data-to]', root).forEach(el => { const go = () => { el.style.strokeDashoffset = el.dataset.to }; if (!motion()) go(); else requestAnimationFrame(() => requestAnimationFrame(go)) });
}
const ringSvg = (cls, id, to = 100) => `<svg class="${cls}" viewBox="0 0 120 120" aria-hidden="true"><circle class="trk" cx="60" cy="60" r="52"/><circle class="val" ${id ? `id="${id}"` : ''} cx="60" cy="60" r="52" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100" data-to="${to}"/></svg>`;

/* ---------------- cinematic move stage ---------------- */
const POOL = 40;   // simultaneous flying tiles (recycled)
const Stage = {
  open(plan, jid, opts) { // Why: full-screen stage synced to the real job (names, thumbnails, per-category counters)
    const st = $('#stage');
    Object.assign(this, { plan, jid, mode: opts.mode, dest: opts.dest, predicted: opts.predicted || null, back: opts.back || 'dashboard', fromSelection: !!opts.fromSelection,
      alive: true, finished: false, queue: [], lastSeq: 0, prev: 0, lastSpawn: 0, doneAt: 0, last: {}, tickQ: null, tickAt: 0, hiddenTab: false });
    this.used = CATS.filter(c => plan.by_cat[c.key]);
    this.job = { state: 'running', total: plan.n, done: 0, moved: 0, bytes: 0, skipped: 0, by_cat: {}, current: [], errors: [] };
    this.disp = { done: 0, bytes: 0 };
    $('#st-brand').textContent = `${APP.name} · ${this.mode === 'move' ? 'Move' : 'Copy'}`;
    $('#st-title').textContent = `${this.mode === 'move' ? 'Moving' : 'Copying'} ${fmt(plan.n)} files`;
    $('#st-stats').innerHTML = `<div><small>Files</small><b class="num"><span id="st-done">0</span> / ${fmt(plan.n)}</b></div><div><small>Data</small><b class="num" id="st-data">0 B</b></div><div><small>Speed</small><b class="num" id="st-speed">—</b></div><div><small>Verified</small><b class="num" id="st-ver">0</b></div><div><small>Elapsed</small><b class="num" id="st-el">0 s</b></div><div><small>Remaining</small><b class="num" id="st-rem">estimating…</b></div>
      <div class="st-ctl"><button class="btn sm ghost" data-a="st-pause" id="st-pause">${ic('pause')} Pause</button><button class="btn sm danger" data-a="st-cancel">${ic('stop')} Cancel</button></div>`;
    this.rates = []; $('#st-route').innerHTML = '';
    $('#st-final').hidden = true; $('#st-final').innerHTML = ''; $('#ticker').innerHTML = ''; $('#st-bar').style.transform = 'scaleX(0)';
    $('#vaults').innerHTML = this.used.map(c => `<div class="vault" data-k="${esc(c.key)}" data-css="--c:${c.c}"><div class="v-ring"><svg viewBox="0 0 60 60" aria-hidden="true"><circle class="trk" cx="30" cy="30" r="26"/><circle class="val" cx="30" cy="30" r="26" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100"/></svg><span class="v-ic">${ic(c.ic)}</span></div>
      <div class="v-txt"><b>${esc(c.key)}</b><span class="num"><span class="v-n">0</span> / ${fmt(plan.by_cat[c.key].n)}</span><small class="num v-s">0 B</small></div></div>`).join('');
    applyCss($('#vaults'));
    this.V = {};
    this.used.forEach(c => { const el = $(`.vault[data-k="${CSS.escape(c.key)}"]`); this.V[c.key] = { el, ring: el.querySelector('.val'), n: el.querySelector('.v-n'), s: el.querySelector('.v-s'), total: plan.by_cat[c.key].n, shown: 0, hitAt: 0 } });
    st.hidden = false; document.body.style.overflow = 'hidden'; requestAnimationFrame(() => st.classList.add('in'));
    this.initFx(); this.initPool(); this.measure();
    this.onResize = () => { this.sizeFx(); this.measure() }; addEventListener('resize', this.onResize);
    this.onVis = () => { this.hiddenTab = document.hidden; if (!this.hiddenTab && this.alive && !this.finished) this.raf = requestAnimationFrame(t => this.frame(t)) };
    document.addEventListener('visibilitychange', this.onVis);
    this.poll(); this.raf = requestAnimationFrame(t => this.frame(t));
  },
  measure() {
    const s = $('#spot .orb').getBoundingClientRect(); this.src = { x: s.left + s.width / 2, y: s.top + s.height / 2, r: s.width / 2 };
    for (const k in this.V) { const r = this.V[k].el.querySelector('.v-ring').getBoundingClientRect(); this.V[k].x = r.left + r.width / 2; this.V[k].y = r.top + r.height / 2 }
    this.measuredAt = performance.now();
  },
  initFx() { this.cv = $('#fx'); this.g = this.cv.getContext('2d'); this.sizeFx();
    this.parts = motion() ? Array.from({ length: 48 }, () => ({ x: Math.random() * innerWidth, y: Math.random() * innerHeight, vx: rnd(-.08, .08), vy: rnd(-.25, -.05), r: rnd(.5, 1.8) })) : [] },
  sizeFx() { const dpr = Math.min(2, devicePixelRatio || 1); this.cv.width = innerWidth * dpr; this.cv.height = innerHeight * dpr; this.g.setTransform(dpr, 0, 0, dpr, 0, 0) },
  initPool() {
    const box = $('#flyers'); box.innerHTML = Array.from({ length: POOL }, () => '<div class="fly"><div class="fc"><span class="fi"></span><img alt="" hidden></div><span class="fn"></span></div>').join('');
    this.pool = $$('.fly', box).map(el => { const img = el.querySelector('img'); img.onerror = () => { img.hidden = true }; return { el, img, fi: el.querySelector('.fi'), fn: el.querySelector('.fn'), busy: false, tr: [] } });
  },
  async poll() { // Why: progress comes from the real server job, never from a timer
    while (this.alive) {
      try { const j = await API.job(this.jid); if (!this.alive) return; this.job = j; this.ingest(j); this.route(j) }
      catch (e) { this.job = Object.assign({}, this.job, { state: 'error', errors: [...(this.job.errors || []), friendly(e)] }) }
      if (this.job.state !== 'running' && this.job.state !== 'paused') { this.doneAt = performance.now(); break }
      await sleep(POLL_JOB_MS);
    }
  },
  route(j) { // Why: source drive -> destination drive, a copy glyph on the way, and a live MB/s sparkline (real samples)
    const box = $('#st-route'); if (!box || !j.dest_drive) return;
    if (j.state === 'running' && j.bytes_rate) { this.rates.push(j.bytes_rate); if (this.rates.length > 60) this.rates.shift() }
    const src = (j.src_drives || []).map(d => driveName(d)).join(', ') || '?', dst = driveName(j.dest_drive), same = src === dst, pct = (j.done || 0) / Math.max(1, j.total || 1);
    const mx = Math.max(1, ...this.rates), pts = this.rates.map((r, i) => `${(i / Math.max(1, this.rates.length - 1) * 200).toFixed(1)},${(38 - r / mx * 34).toFixed(1)}`).join(' ');
    if (!box.firstElementChild) box.innerHTML = `<span class="rt-drive">${ic('drive')}<b id="rt-src"></b></span><span class="rt-path"><i class="rt-glyph">${ic('file')}</i></span><span class="rt-drive">${ic('drive')}<b id="rt-dst"></b></span>
      <svg class="rt-spark" viewBox="0 0 200 40" preserveAspectRatio="none" aria-label="Speed over time"><polyline id="rt-line" points=""/></svg><span class="mut num" id="rt-note"></span>`;
    $('#rt-src').textContent = src; $('#rt-dst').textContent = dst;
    box.querySelector('.rt-glyph').style.left = `calc(${(pct * 100).toFixed(1)}% - 10px)`;
    box.classList.toggle('moving', j.state === 'running' && motion());
    $('#rt-line').setAttribute('points', pts);
    $('#rt-note').textContent = same && this.mode === 'move' ? 'Same drive: files are renamed, nothing is copied' : `${j.verify === 'full' ? 'Every copy checked byte for byte (BLAKE2b)' : j.verify === 'fast' ? 'Fast check: size and sampled blocks' : 'Size check'} before ${this.mode === 'move' ? 'the original is removed' : 'it counts as done'}`;
    this.text('#st-ver', fmt(j.verified || 0));
    const pb = $('#st-pause'); if (pb) { const paused = j.state === 'paused'; if (pb.dataset.p !== String(paused)) { pb.dataset.p = String(paused); pb.innerHTML = paused ? `${ic('play')} Resume` : `${ic('pause')} Pause` } }
  },
  ingest(j) {
    const fresh = (j.current || []).filter(x => x.seq > this.lastSeq); if (!fresh.length) return;
    this.lastSeq = fresh[fresh.length - 1].seq;
    if (motion()) { this.queue.push(...fresh); if (this.queue.length > 48) this.queue.splice(0, this.queue.length - 48) }
    this.tickQ = (this.tickQ || []).concat(fresh).slice(-6);
  },
  tick(now, all) { // Why: the live ticker shows REAL names ("IMG_2031.jpg → Images/Camera") at a readable pace
    if (!this.tickQ || !this.tickQ.length || (!all && now - (this.tickAt || 0) < 380)) return;
    const fresh = this.tickQ.splice(0, all ? 6 : 2); this.tickAt = now; const tk = $('#ticker');
    for (const x of fresh) { const c = CAT[x.cat] || CAT.Other, row = document.createElement('div'); row.className = 'tk'; row.style.setProperty('--c', c.c);
      row.innerHTML = `${ic(c.ic)}<b title="${esc(x.name)}">${esc(x.name)}</b><span class="ar">→</span><span class="to">${esc(x.to)}</span>`; tk.prepend(row) }
    while (tk.children.length > 7) tk.lastChild.remove();
  },
  spawn(x, now) {
    const it = this.pool.find(p => !p.busy), V = this.V[x.cat]; if (!it || !V) return false;
    const c = CAT[x.cat] || CAT.Other;
    it.el.style.setProperty('--c', c.c); it.fi.innerHTML = ic(c.ic); it.fn.textContent = x.name;
    const src = DEMO ? API.thumb(x.id) : x.thumb;
    if (x.cat === 'Images' && src) { it.img.hidden = false; it.img.src = src } else { it.img.hidden = true; it.img.removeAttribute('src') }
    const a = Math.random() * 6.283, r = this.src.r * rnd(.1, .55);
    Object.assign(it, { busy: true, t0: now, dur: rnd(950, 1350), x0: this.src.x + Math.cos(a) * r, y0: this.src.y + Math.sin(a) * r, x1: V.x, y1: V.y, rot: rnd(-18, 18), key: x.cat, tr: [], color: c.c });
    it.cx = (it.x0 + it.x1) / 2 + rnd(-120, 120); it.cy = Math.min(it.y0, it.y1) - 60 - Math.abs(it.y1 - it.y0) * .25 - rnd(0, 60);
    return true;
  },
  frame(now) {
    if (!this.alive || this.hiddenTab) return;
    const dt = Math.min(50, now - (this.prev || now)); this.prev = now; const j = this.job, g = this.g, W = innerWidth, H = innerHeight;
    if (now - this.measuredAt > 1000) this.measure();
    this.tick(now);
    const gap = Math.max(18, 110 - this.queue.length * 4);
    while (this.queue.length && now - this.lastSpawn > gap) { if (!this.spawn(this.queue.shift(), now)) break; this.lastSpawn = now }
    const fx = this.parts.length > 0;
    if (fx) {
      g.clearRect(0, 0, W, H);
      g.fillStyle = currentTheme() === 'light' ? 'rgba(91,33,182,.22)' : 'rgba(196,181,253,.38)'; g.beginPath();
      for (const p of this.parts) { p.x += p.vx * dt * .06; p.y += p.vy * dt * .06; if (p.y < -5) { p.y = H + 5; p.x = Math.random() * W } if (p.x < -5) p.x = W + 5; if (p.x > W + 5) p.x = -5; g.moveTo(p.x + p.r, p.y); g.arc(p.x, p.y, p.r, 0, 6.283) }
      g.fill();
    }
    let busy = 0;
    for (const it of this.pool) {
      if (!it.busy) continue; busy++;
      const u = (now - it.t0) / it.dur;
      if (u >= 1) { it.busy = false; it.el.style.opacity = 0; const V = this.V[it.key]; if (V && now - V.hitAt > 260) { V.hitAt = now; V.el.classList.remove('hit'); void V.el.offsetWidth; V.el.classList.add('hit') } continue }
      const e = easeIO(u), k = 1 - e, x = k * k * it.x0 + 2 * k * e * it.cx + e * e * it.x1, y = k * k * it.y0 + 2 * k * e * it.cy + e * e * it.y1;
      it.el.style.transform = `translate3d(${x.toFixed(1)}px,${y.toFixed(1)}px,0) translate(-50%,-50%) scale(${(1 - .62 * e).toFixed(3)}) rotate(${(it.rot * (1 - e)).toFixed(1)}deg)`;
      it.el.style.opacity = u < .08 ? u / .08 : u > .86 ? (1 - u) / .14 : 1;
      if (fx) { const tr = it.tr; tr.push(x, y); if (tr.length > 12) tr.splice(0, 2); g.strokeStyle = it.color; g.lineWidth = 2 * (1 - e * .5);
        for (let q = 2; q < tr.length; q += 2) { g.globalAlpha = (q / tr.length) * .55; g.beginPath(); g.moveTo(tr[q - 2], tr[q - 1]); g.lineTo(tr[q], tr[q + 1]); g.stroke() } g.globalAlpha = 1 }
    }
    const kk = Math.min(1, dt / 160), D = this.disp;
    D.done += ((j.done || 0) - D.done) * kk; D.bytes += ((j.bytes || 0) - D.bytes) * kk;
    if (j.state !== 'running') { D.done = j.done || 0; D.bytes = j.bytes || 0 }
    this.text('#st-done', fmt(D.done)); this.text('#st-data', sz(D.bytes)); this.text('#st-left', fmt(Math.max(0, (j.total || 0) - D.done)));
    this.text('#st-speed', j.bytes_rate ? sz(j.bytes_rate) + '/s' : '—'); this.text('#st-el', dur(j.elapsed)); this.text('#st-rem', j.remaining == null ? 'estimating…' : '~' + dur(j.remaining));
    this.text('#st-bar', `scaleX(${((j.done || 0) / Math.max(1, j.total || 1)).toFixed(4)})`, 'transform');
    for (const key in this.V) { const V = this.V[key], real = j.by_cat?.[key]?.moved || 0; V.shown += (real - V.shown) * kk; if (j.state !== 'running' || Math.abs(real - V.shown) < .5) V.shown = real;
      const p = Math.min(100, pct(V.shown, V.total)); if (Math.abs((V.lastP || 0) - p) > .05) { V.ring.style.strokeDashoffset = (100 - p).toFixed(2); V.lastP = p }
      if (V.lastN !== Math.round(V.shown)) { V.lastN = Math.round(V.shown); V.n.textContent = fmt(V.shown); V.s.textContent = sz(j.by_cat?.[key]?.bytes || 0) } }
    if (!this.finished && j.state !== 'running' && j.state !== 'paused' && ((!this.queue.length && !busy) || now - this.doneAt > 2500)) { this.finish(); this.finAt = now }
    if (this.finished && now - this.finAt > 1600) { if (fx) g.clearRect(0, 0, W, H); return }
    this.raf = requestAnimationFrame(t => this.frame(t));
  },
  text(sel, v, how) { if (this.last[sel] === v) return; this.last[sel] = v; const e = $(sel); if (!e) return; if (how === 'transform') e.style.transform = v; else e.textContent = v },
  finish() { // Why: the "completed" moment: real totals, actual vs predicted time, Done / Undo / Open destination
    this.tick(performance.now(), true); this.finished = true; this.queue = []; for (const it of this.pool) { it.busy = false; it.el.style.opacity = 0 }
    const j = this.job, ok = j.state === 'done', moved = this.mode === 'move';
    const delta = j.free_after != null && j.free_before != null ? j.free_after - j.free_before : null, d0 = delta != null && Math.abs(delta) < 1048576 ? 0 : delta;
    const errs = (j.errors || []).slice(0, 6);
    $('#st-final').innerHTML = `<div class="card fin" role="dialog" aria-modal="true" aria-label="Completed"><div class="fin-mark">${ic(ok ? 'check' : 'alert')}</div><p class="eyebrow">${ok ? 'Completed' : 'Stopped'}</p>
      <h2>${ok && !j.skipped ? 'Done.' : ok ? 'Done, with a few files skipped.' : 'The job stopped early.'}</h2>
      <div class="fin-stats"><div><b class="num" data-count="${j.moved || 0}">0</b><small>files ${moved ? 'moved' : 'copied'}</small></div><div><b class="num" data-count="${j.bytes || 0}" data-f="sz">0</b><small>data ${moved ? 'moved' : 'copied'}</small></div>
        <div><b class="num" ${d0 == null ? '>—' : `data-count="${Math.abs(d0)}" data-f="sz">0`}</b><small>${d0 != null && d0 < 0 ? 'space used' : 'space freed'}</small></div>
        <div><b class="num">${dur(j.elapsed)}</b><small>${this.predicted ? `took (predicted ${durRange(this.predicted[0], this.predicted[1])})` : 'took'}</small></div></div>
      <p class="mut">${d0 === 0 && moved ? 'Same drive: files were reorganised in place, so free space is unchanged.' : d0 > 0 ? 'Measured on the drives involved, before and after.' : d0 < 0 ? 'Copies take extra room; the originals are untouched.' : ''}</p>
      <dl class="fin-report"><div><dt>Average speed</dt><dd class="num">${j.elapsed ? sz((j.bytes || 0) / j.elapsed) + '/s' : '—'}</dd></div>
        <div><dt>Verification</dt><dd>${j.verified ? `${fmt(j.verified)} ${j.verified === 1 ? 'copy' : 'copies'} verified (${j.verify === 'full' ? 'full BLAKE2b hash' : j.verify === 'fast' ? 'size + sampled blocks' : 'size'})` : moved ? 'Not needed: same-drive renames' : 'None'}</dd></div></dl>
      ${j.skipped || errs.length ? `<div class="note warn">${ic('alert')}<div><b>${fmt(j.skipped || 0)}</b> skipped (changed, missing or protected):<br><small>${errs.map(esc).join('<br>')}</small></div></div>` : ''}
      <div class="row"><button class="btn pri" data-a="st-done">${ic('check')} Done</button>${moved && j.moved ? `<button class="btn" data-a="st-undo">${ic('undo')} Undo</button>` : ''}<button class="btn ghost" data-a="st-open">${ic('external')} Open destination</button></div></div>`;
    $('#st-final').hidden = false; countUps($('#st-final'));
    notify(ok ? `${moved ? 'Moved' : 'Copied'} ${fmt(j.moved || 0)} files` : 'Move stopped early', `${sz(j.bytes || 0)} → ${base(this.dest)}`, 'moveto');
    setTimeout(() => $('#st-final .btn.pri')?.focus(), 50);
  },
  close(next) {
    this.alive = false; cancelAnimationFrame(this.raf); removeEventListener('resize', this.onResize); document.removeEventListener('visibilitychange', this.onVis);
    const st = $('#stage'); st.classList.remove('in'); $('#st-final').hidden = true;
    setTimeout(() => { st.hidden = true; $('#flyers').innerHTML = '' }, motion() ? 450 : 0); document.body.style.overflow = '';
    if (this.fromSelection) Sel.clear();
    refreshIndex().then(() => go(next));   // lists re-load from the updated index: no rescan needed
  }
};
