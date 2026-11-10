/* AuraSort - the dashboard's "file manager" scene: a small window with six folder tabs and file chips.
   Chips stand for real data (types and proportions from the last scan, real names on hover); they lean away from the
   cursor, lift on hover, and every few seconds a few glide into their folder tab. During a scan they stream in from the
   left as files are found. Under 60 SVG elements; paused when the tab is hidden; static with reduced motion. */
'use strict';
const SCENE_TABS = [['Images', 'Images'], ['Videos', 'Videos'], ['Audio', 'Audio'], ['Documents', 'Docs'], ['PDFs', 'PDFs'], ['Archives', 'Archives']];
const SCENE_CHIPS = 13, SCENE_W = 320, SCENE_H = 220, SCENE_GLIDE_EVERY_MS = 4200, SCENE_GLIDE_MS = 900, SCENE_REPEL_PX = 64;
const CHIP_GLYPH = { // tiny glyphs drawn inside a 24x30 chip centred on 0,0
  Images: 'M-7 7 -2 1l3 3 2-2 4 5zM3-6a2 2 0 1 0 .01 0', Videos: 'M-3-5v10l8-5z', Audio: 'M-2 6V-6l7-1.5v9M-2 6a2.2 2.2 0 1 1-.01 0',
  Documents: 'M-6-6h12M-6-2h12M-6 2h12M-6 6h7', PDFs: 'M-7-3h14v7h-14zM-4 7h8', Archives: 'M0-12v4M0-6v4M0 0v4M-3 6h6v4h-6z'
};

const Scene = {
  st: null,
  html(cls = '') { // Why: the markup is static; mount() brings it to life
    const tabW = 46, gap = 4, x0 = (SCENE_W - (tabW * 6 + gap * 5)) / 2;
    const tabs = SCENE_TABS.map(([cat, label], i) => `<g class="sc-tab" data-a="nav-type" data-k="${esc(cat)}" data-i="${i}" role="button" tabindex="0" aria-label="Open ${esc(cat)}" data-css="--c:${(CAT[cat] || CAT.Other).c}">
      <rect x="${x0 + i * (tabW + gap)}" y="34" width="${tabW}" height="22" rx="5"/><text x="${x0 + i * (tabW + gap) + tabW / 2}" y="49" text-anchor="middle">${esc(label)}</text></g>`).join('');
    const chips = Array.from({ length: SCENE_CHIPS }, (_, i) => `<g class="sc-chip" data-n="${i}"><rect x="-12" y="-15" width="24" height="30" rx="4"/><path d=""/></g>`).join('');
    return `<svg class="scene ${cls}" viewBox="0 0 ${SCENE_W} ${SCENE_H}" preserveAspectRatio="xMinYMid meet" role="img" aria-label="Your files by type, as folders and file chips">
      <rect class="sc-win" x="4" y="4" width="${SCENE_W - 8}" height="${SCENE_H - 8}" rx="10"/><path class="sc-bar" d="M4 26h${SCENE_W - 8}M16 15h.01M25 15h.01M34 15h.01"/>${tabs}${chips}</svg>`;
  },
  mount(svg, mode, data) { // mode: 'idle' (before any scan), 'live' (dashboard), 'scan' (streams in during a scan)
    this.stop();
    const tabEls = $$('.sc-tab', svg), chips = $$('.sc-chip', svg).map((el, i) => ({ el, i, rect: el.firstElementChild, glyph: el.lastElementChild }));
    const st = this.st = { svg, mode, chips, tabEls, mx: -999, my: -999, last: 0, nextGlide: performance.now() + 1500, seen: {}, live: motion() && mode !== 'idle' };
    this.assign(data || {});
    chips.forEach(c => { c.x = c.hx; c.y = c.hy; c.r = 0; c.s = 1; c.o = mode === 'scan' ? 0 : 1; c.phase = mode === 'scan' ? 'hidden' : 'rest'; this.draw(c) });
    svg.addEventListener('pointermove', e => { const b = svg.getBoundingClientRect(); st.mx = (e.clientX - b.left) * SCENE_W / b.width; st.my = (e.clientY - b.top) * SCENE_H / b.height });
    svg.addEventListener('pointerleave', () => { st.mx = st.my = -999 });
    chips.forEach(c => { c.el.addEventListener('pointerenter', () => { c.hover = true }); c.el.addEventListener('pointerleave', () => { c.hover = false }) });
    tabEls.forEach(t => t.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ACT['nav-type'](t) } }));
    if (st.live) { st.raf = requestAnimationFrame(t => this.frame(t)) }
  },
  assign(d) { // Why: chips follow the real mix of file types (largest remainder), each with a real file name
    const st = this.st, by = d.by_cat || {}, total = SCENE_TABS.reduce((a, [c]) => a + ((by[c] || {}).n || 0), 0);
    let cats;
    if (!total) cats = Array.from({ length: SCENE_CHIPS }, (_, i) => SCENE_TABS[i % 6][0]);
    else {
      const want = SCENE_TABS.map(([c]) => { const q = ((by[c] || {}).n || 0) / total * SCENE_CHIPS; return { c, n: Math.floor(q), f: q % 1, has: (by[c] || {}).n > 0 } });
      want.forEach(w => { if (w.has && !w.n) { w.n = 1; w.f = -1 } });
      let left = SCENE_CHIPS - want.reduce((a, w) => a + w.n, 0);
      for (const w of [...want].sort((a, b) => b.f - a.f)) { if (left <= 0) break; if (w.has) { w.n++; left-- } }
      while (want.reduce((a, w) => a + w.n, 0) > SCENE_CHIPS) { const w = want.filter(x => x.n > 1).sort((a, b) => b.n - a.n)[0]; if (!w) break; w.n-- }
      cats = want.flatMap(w => Array(w.n).fill(w.c));
      while (cats.length < SCENE_CHIPS) cats.push(cats[cats.length % Math.max(1, cats.length)] || 'Documents');
    }
    const names = d.samples || {}, used = {};
    st.chips.forEach((c, i) => {
      const cat = cats[i] || 'Documents', k = used[cat] = (used[cat] || 0) + 1, list = names[cat] || [];
      c.cat = cat; c.name = list.length ? list[(k - 1) % list.length] : '';
      c.el.style.setProperty('--c', (CAT[cat] || CAT.Other).c); c.glyph.setAttribute('d', CHIP_GLYPH[cat] || CHIP_GLYPH.Documents);
      if (c.name) c.el.dataset.tipt = `${c.name}|${cat}`; else delete c.el.dataset.tipt;
      this.home(c, i);
    });
  },
  home(c, i) { // Why: resting places on a loose grid inside the window, slightly jittered so it doesn't look generated
    const col = i % 5, row = Math.floor(i / 5), j = (n => ((n * 9301 + 49297) % 233280) / 233280)(i * 7 + (c.gen || 0));
    c.hx = 46 + col * 57 + (j - .5) * 16; c.hy = 92 + row * 44 + (j - .5) * 10; c.hr = (j - .5) * 10;
  },
  feed(byCat) { // Why: during a scan, each newly found batch of a type sends one chip in from the left
    const st = this.st; if (!st || st.mode !== 'scan') return;
    for (const [cat] of SCENE_TABS) {
      const n = (byCat || {})[cat] || 0, before = st.seen[cat] || 0; if (n <= before) continue;
      st.seen[cat] = n;
      const c = st.chips.find(x => x.phase === 'hidden') || st.chips.reduce((a, b) => (a.born || 0) < (b.born || 0) ? a : b);
      c.cat = cat; c.el.style.setProperty('--c', (CAT[cat] || CAT.Other).c); c.glyph.setAttribute('d', CHIP_GLYPH[cat]);
      c.el.dataset.tipt = `${cat}|${fmt(n)} found so far`;
      Object.assign(c, { phase: 'enter', x: -20, y: c.hy, o: 0, born: performance.now() });
      if (!st.live) { Object.assign(c, { x: c.hx, y: c.hy, o: 1, phase: 'rest' }); this.draw(c) }
    }
  },
  frame(now) {
    const st = this.st; if (!st || !st.svg.isConnected) { this.stop(); return }
    if (document.hidden) { st.raf = requestAnimationFrame(t => this.frame(t)); st.last = now; return }   // paused while hidden
    const k = Math.min(1, (now - (st.last || now)) / 16.7) * .14; st.last = now;
    if (st.mode === 'live' && now > st.nextGlide) { st.nextGlide = now + SCENE_GLIDE_EVERY_MS; this.glide(now) }
    for (const c of st.chips) {
      if (c.phase === 'glide') {
        const u = clamp((now - c.t0) / SCENE_GLIDE_MS, 0, 1), e = easeIO(u);
        c.x = c.fx + (c.tx - c.fx) * e; c.y = c.fy + (c.ty - c.fy) * e - Math.sin(u * Math.PI) * 26; c.s = 1 - .6 * e; c.o = u > .8 ? (1 - u) * 5 : 1; c.r = c.hr * (1 - e);
        if (u >= 1) { const t = st.tabEls[c.tab]; t.classList.add('hit'); setTimeout(() => t.classList.remove('hit'), 220); c.gen = (c.gen || 0) + 1; this.home(c, c.i); Object.assign(c, { phase: 'enter', x: c.hx, y: c.hy + 14, s: 1, o: 0 }) }
      } else if (c.phase === 'enter') {
        c.x += (c.hx - c.x) * k * 1.4; c.y += (c.hy - c.y) * k * 1.4; c.o = Math.min(1, c.o + k * 1.6);
        if (Math.abs(c.hx - c.x) < .5 && Math.abs(c.hy - c.y) < .5 && c.o >= 1) c.phase = 'rest';
      } else if (c.phase === 'rest') {
        const dx = c.hx - st.mx, dy = c.hy - st.my, d = Math.hypot(dx, dy) || 1, push = d < SCENE_REPEL_PX ? (SCENE_REPEL_PX - d) * .32 : 0;
        const tx = c.hx + dx / d * push, ty = c.hy + dy / d * push - (c.hover ? 5 : 0), tr = c.hr + (st.mx > -999 ? clamp((st.mx - c.x) / 30, -1, 1) * 6 : 0);
        c.x += (tx - c.x) * k; c.y += (ty - c.y) * k; c.r += (tr - c.r) * k; c.s += ((c.hover ? 1.12 : 1) - c.s) * k;
      }
      this.draw(c);
    }
    st.raf = requestAnimationFrame(t => this.frame(t));
  },
  glide(now) { // Why: a couple of chips at a time file themselves into their folder tab
    const st = this.st, rest = st.chips.filter(c => c.phase === 'rest' && !c.hover);
    for (let n = 0; n < 2 && rest.length; n++) {
      const c = rest.splice(Math.floor(Math.random() * rest.length), 1)[0], tab = SCENE_TABS.findIndex(([cat]) => cat === c.cat), r = st.tabEls[tab].firstElementChild;
      Object.assign(c, { phase: 'glide', t0: now + n * 160, fx: c.x, fy: c.y, tab, tx: +r.getAttribute('x') + 23, ty: 45 });
    }
  },
  draw(c) { c.el.setAttribute('transform', `translate(${c.x.toFixed(1)} ${c.y.toFixed(1)}) rotate(${(c.r || c.hr || 0).toFixed(1)}) scale(${c.s.toFixed(3)})`); c.el.style.opacity = c.o.toFixed(2) },
  stop() { if (this.st && this.st.raf) cancelAnimationFrame(this.st.raf); this.st = null }
};
