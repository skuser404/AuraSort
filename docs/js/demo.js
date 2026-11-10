/* AuraSort - demo backend for static hosting (GitHub Pages): fake data only, nothing real is read or touched.
   Implements the same API as server.py on top of query.js, so the demo behaves like the real app. */
'use strict';
const DemoApi = (() => {
  const U = 'C:\\Users\\Alex\\';
  const st = { T: null, ver: 1, scan: null, jobs: {}, hist: [], sprites: {}, settings: { roots: [], skip: [], dest: U + 'AuraSortFiles', dest_roots: [], optin: [], mode: 'quick', drives: [] } };
  const NAMES = {
    Images: [['Camera', ['jpg', 'heic'], n => `IMG_${2000 + n}`], ['Screenshots', ['png'], n => `Screenshot 2026-0${1 + n % 9}-1${n % 9} at 10.${n % 60}`], ['WhatsApp', ['jpg'], n => `IMG-2026${String(n % 12 + 1).padStart(2, '0')}12-WA${String(n).padStart(4, '0')}`], ['Graphics', ['png', 'webp', 'svg'], n => `design_${n}`], ['Photos', ['jpg', 'jpeg'], n => `holiday_${n}`]],
    Videos: [['Camera', ['mp4', 'mov'], n => `VID_${3000 + n}`], ['Screen recordings', ['mp4'], n => `Screen Recording ${n}`], ['Clips & movies', ['mkv', 'mp4', 'webm'], n => `clip_${n}`]],
    Audio: [['Music', ['mp3', 'flac', 'm4a'], n => `track_${n}`], ['Recordings', ['m4a', 'wav'], n => `Voice memo ${n}`], ['WhatsApp audio', ['opus'], n => `PTT-2026-${n}`]],
    Documents: [['Word docs', ['docx', 'doc', 'odt'], n => `report_${n}`], ['Notes & text', ['txt', 'md'], n => `notes_${n}`], ['eBooks', ['epub'], n => `book_${n}`]],
    PDFs: [['Invoices & receipts', ['pdf'], n => `invoice_${n}`], ['Resumes & certificates', ['pdf'], n => `certificate_${n}`], ['Other PDFs', ['pdf'], n => `paper_${n}`]],
    'Sheets & Slides': [['Spreadsheets', ['xlsx', 'csv', 'ods'], n => `budget_${n}`], ['Presentations', ['pptx', 'key'], n => `slides_${n}`]],
    Archives: [['Compressed', ['zip', 'rar', '7z', 'tar'], n => `backup_${n}`]],
    'Installers & Apps': [['Windows', ['exe', 'msi'], n => `setup_${n}`], ['Android', ['apk'], n => `app_${n}`], ['Mac & Linux', ['dmg', 'deb'], n => `installer_${n}`]],
    'Disk images': [['ISO', ['iso', 'img'], n => `disc_${n}`]], 'Code & Scripts': [['PY', ['py', 'js', 'ps1', 'sql'], n => `script_${n}`]],
    'Text & Logs': [['LOG', ['log', 'json', 'xml', 'yml'], n => `debug_${n}`]], Fonts: [['TTF', ['ttf', 'otf', 'woff2'], n => `Font${n}`]],
    Databases: [['DB', ['sqlite', 'db'], n => `store_${n}`]], Other: [['DAT', ['dat', 'bak', 'tmp', 'bin'], n => `blob_${n}`]]
  };
  const SIZE = { Images: [3e5, 7e6], Videos: [2e7, 1.4e9], Audio: [2e6, 1.4e7], Documents: [2e4, 3e6], PDFs: [8e4, 9e6], 'Sheets & Slides': [3e4, 6e6], Archives: [4e6, 9e8],
    'Installers & Apps': [3e7, 6e8], 'Disk images': [6e8, 5e9], 'Code & Scripts': [400, 6e4], 'Text & Logs': [300, 4e6], Fonts: [3e4, 9e5], Databases: [1e5, 2e8], Other: [1e3, 4e7] };
  const DIRS = [ // [path, kind, project, counts]
    ['Downloads', 'ok', -1, { Images: 140, Videos: 22, Audio: 30, Documents: 40, PDFs: 70, 'Sheets & Slides': 26, Archives: 34, 'Installers & Apps': 18, 'Disk images': 3, Other: 12, 'Text & Logs': 6 }],
    ['Downloads\\WhatsApp Images', 'ok', -1, { Images: 230, Videos: 20, Audio: 26 }], ['Pictures\\Goa Trip 2025', 'ok', -1, { Images: 180, Videos: 14 }],
    ['Pictures\\Camera Roll', 'ok', -1, { Images: 260, Videos: 32 }], ['Desktop', 'ok', -1, { Images: 34, PDFs: 14, Documents: 12, 'Code & Scripts': 4, Other: 3 }],
    ['Documents\\College\\Semester 7', 'ok', -1, { PDFs: 52, Documents: 34, 'Sheets & Slides': 20 }], ['Music\\Playlist', 'ok', -1, { Audio: 160 }],
    ['Videos\\Edits', 'ok', -1, { Videos: 44 }], ['Documents\\Fonts', 'ok', -1, { Fonts: 18 }], ['Documents\\Backups', 'ok', -1, { Archives: 9, Databases: 6 }],
    ['Documents\\Projects\\atelier-website\\assets\\img', 'project', 0, { Images: 180, 'Code & Scripts': 12 }], ['Documents\\Projects\\atelier-website\\public', 'project', 0, { Images: 60, Videos: 4, 'Text & Logs': 3 }],
    ['Documents\\Projects\\flutter-boutique\\assets', 'project', 1, { Images: 95, Audio: 6, 'Code & Scripts': 20 }], ['Documents\\Misc\\icons', 'assets', -1, { Images: 45 }]];
  const PROJECTS = ['Documents\\Projects\\atelier-website', 'Documents\\Projects\\flutter-boutique'].map(p => U + p);
  const SPECIAL = [['lighthouse_sunset.jpg', 2, 'Images', 'Photos'], ['Spotlight.png', 0, 'Images', 'Graphics'], ['light-mode.pdf', 0, 'PDFs', 'Other PDFs'],
    ['Flight_tickets_Goa.pdf', 0, 'PDFs', 'Invoices & receipts'], ['highlights_reel.mp4', 7, 'Videos', 'Clips & movies'], ['Twilight_piano.mp3', 6, 'Audio', 'Music'],
    ['candlelight_dinner.heic', 2, 'Images', 'Photos'], ['lightroom_presets.zip', 0, 'Archives', 'Compressed'], ['moonlight-sonata.flac', 6, 'Audio', 'Music'], ['Lighthouse_night.webp', 3, 'Images', 'Graphics']];

  function gen() { // Why: a believable PC: every category present, projects and asset folders included
    let seed = 7; const r = () => (seed = (seed * 16807) % 2147483647) / 2147483647, between = (a, b) => a + r() * (b - a);
    const T = { id: [], name: [], ext: [], cat: [], sub: [], size: [], mtime: [], ctime: [], atime: [], dir: [], dirs: [] };
    const now = Date.now() / 1000; let n = 0;
    const push = (name, ext, cat, sub, di) => { const mt = Math.floor(now - Math.pow(r(), 1.6) * 9e7), sz = Math.floor(Math.exp(between(Math.log(SIZE[cat][0]), Math.log(SIZE[cat][1]))));
      T.id.push(n + 1); T.name.push(name); T.ext.push(ext); T.cat.push(cat); T.sub.push(sub); T.size.push(sz); T.mtime.push(mt); T.ctime.push(mt - Math.floor(r() * 4e5)); T.atime.push(Math.floor(now - r() * 2e6)); T.dir.push(di); n++ };
    DIRS.forEach(([p, kind, proj, counts], di) => {
      T.dirs.push({ id: di + 1, path: U + p, kind, included: kind === 'ok', project: proj });
      for (const [cat, cnt] of Object.entries(counts)) for (let i = 0; i < cnt; i++) { const s = NAMES[cat][Math.floor(Math.pow(r(), 1.3) * NAMES[cat].length)], ext = s[1][Math.floor(r() * s[1].length)]; push(`${s[2](n)}.${ext}`, ext, cat, s[0], di) }
    });
    for (const [name, di, cat, sub] of SPECIAL) push(name, name.split('.').pop(), cat, sub, di);
    return T;
  }
  const table = () => st.T;
  const ensure = () => { if (!st.T) st.T = qTable(gen()) };
  const rowsOf = idx => idx.map(i => qRow(st.T, i));
  const sumBy = (idx, key) => { const m = {}; for (const i of idx) { const k = typeof key === 'function' ? key(i) : st.T[key][i]; (m[k] = m[k] || { n: 0, size: 0 }).n++; m[k].size += st.T.size[i] } return m };

  function summary() { // Why: same shape as /api/summary
    const T = st.T; if (!T) return { version: st.ver, scan: null, total: 0, total_size: 0, by_cat: Object.fromEntries(CATS.map(c => [c.key, { n: 0, size: 0, ready: 0, ready_size: 0 }])), ready: 0, ready_size: 0, left_alone: 0, projects: [], biggest_folders: [], biggest_files: [], project_count: 0, asset_dirs: 0 };
    const by = Object.fromEntries(CATS.map(c => [c.key, { n: 0, size: 0, ready: 0, ready_size: 0 }])), all = T.id.map((_, i) => i);
    for (const i of all) { const b = by[T.cat[i]]; b.n++; b.size += T.size[i]; if (T.dirs[T.dir[i]].included && !VIEW_ONLY.has(T.cat[i])) { b.ready++; b.ready_size += T.size[i] } }
    const total = all.length, ready = Object.values(by).reduce((a, b) => a + b.ready, 0);
    const dirSum = sumBy(all, 'dir'), bigDirs = Object.entries(dirSum).sort((a, b) => b[1].size - a[1].size).slice(0, 8).map(([d, v]) => ({ id: T.dirs[d].id, path: T.dirs[d].path, kind: T.dirs[d].kind, n: v.n, size: v.size }));
    const bigFiles = all.sort((a, b) => T.size[b] - T.size[a]).slice(0, 8);
    const projects = PROJECTS.map((p, pi) => { const idx = T.id.map((_, i) => i).filter(i => T.dirs[T.dir[i]].project === pi); return { path: p, n: idx.length, size: idx.reduce((a, i) => a + T.size[i], 0) } });
    return { version: st.ver, scan: { mode: 'quick', finished: st.scanDone || Date.now() / 1000, roots: [U + 'Downloads', U + 'Pictures', U + 'Documents'], noaccess: 2 },
      by_cat: by, total, total_size: Object.values(by).reduce((a, b) => a + b.size, 0), ready, ready_size: Object.values(by).reduce((a, b) => a + b.ready_size, 0), left_alone: total - ready,
      projects, project_count: 4, asset_dirs: 1, biggest_folders: bigDirs, biggest_files: rowsOf(bigFiles),
      samples: Object.fromEntries(['Images', 'Videos', 'Audio', 'Documents', 'PDFs', 'Archives'].map(c => [c, T.id.map((_, i) => i).filter(i => T.cat[i] === c).sort((a, b) => T.size[b] - T.size[a]).slice(0, 4).map(i => T.name[i])])) };
  }
  function scanStatus() { // Why: a 3.5 s simulated scan with realistic live counters
    const s = st.scan; if (!s) return { state: 'idle' };
    if (s.state === 'running') { const el = (Date.now() - s.t0) / 1000 - s.paused; s.f = Math.min(1, el / 3.5); if (s.f >= 1) { s.state = 'done'; st.scanDone = Date.now() / 1000; st.ver++; st.hist.unshift({ id: 'scan-' + Date.now(), kind: 'scan', time: Date.now() / 1000, count: st.T.id.length, size: st.T.size.reduce((a, b) => a + b, 0), label: s.mode === 'quick' ? 'Quick Scan' : 'Deep Scan', undoable: false }) } }
    const T = st.T, N = T.id.length, k = Math.floor(N * s.f), el = s.state === 'paused' ? s.pausedAt - s.t0 / 1000 - s.paused : (Date.now() - s.t0) / 1000 - s.paused;
    const by = {}; let bytes = 0; for (let i = 0; i < k; i++) { by[T.cat[i]] = (by[T.cat[i]] || 0) + 1; bytes += T.size[i] }
    const recent = T.dirs.slice(0, Math.max(1, Math.ceil(T.dirs.length * s.f))).slice(-6).map(d => d.path).reverse();
    return { state: s.state, mode: s.mode, found: k, bytes, dirs: Math.round(420 * s.f), queued: Math.round(60 * (1 - s.f)), noaccess: Math.round(2 * s.f), pct: Math.round(s.f * 1000) / 10,
      elapsed: Math.max(0, el), remaining: s.state === 'done' ? 0 : Math.max(0, 3.5 - el), rate: k / Math.max(el, .1), by_cat: by, recent, current_file: recent[0],
      drives: [{ root: 'C:\\', used: 389e9, scanned: bytes, pct: s.state === 'done' ? 100 : Math.round(s.f * 990) / 10 }] };
  }
  function runJob(job) { // Why: simulated move with real-looking per-file progress (and the demo table updated afterwards)
    const j = st.jobs[job], f = Math.min(1, (Date.now() - j.t0) / j.dur), done = Math.round(j.total * easeIO(f));
    while (j.k < done) {
      const op = j.ops[j.k++], i = st.T.pos ? st.T.pos.get(op) : st.T.id.indexOf(op); if (i == null || i < 0) continue;
      const cat = st.T.cat[i], sub = j.flat ? cat : `${cat}/${st.T.sub[i]}`;
      j.moved++; j.bytes += st.T.size[i]; const b = j.by_cat[cat] || (j.by_cat[cat] = { moved: 0, bytes: 0 }); b.moved++; b.bytes += st.T.size[i];
      j.current = (j.current.concat([{ seq: j.moved, id: st.T.id[i], name: st.T.name[i], cat, size: st.T.size[i], to: sub }])).slice(-12);
      j.moves.push([i, sub]);
    }
    if (f >= 1 && j.state === 'running') { j.state = 'done'; finishMove(j) }
    return { id: job, kind: 'move', state: j.state, total: j.total, done, moved: j.moved, skipped: 0, bytes: j.bytes, total_bytes: j.total_bytes, errors: [], current: j.current.slice(),
      by_cat: JSON.parse(JSON.stringify(j.by_cat)), free_before: 123e9, free_after: f >= 1 ? 123e9 : null, mode: j.mode, dest: j.dest, elapsed: (Date.now() - j.t0) / 1000,
      remaining: Math.max(0, (j.dur - (Date.now() - j.t0)) / 1000), bytes_rate: j.bytes / Math.max(.1, (Date.now() - j.t0) / 1000), pct: Math.round(1000 * done / Math.max(1, j.total)) / 10, current_file: j.current.length ? j.current[j.current.length - 1].name : '' };
  }
  function finishMove(j) { // Why: moved files really change folder in the demo, so lists update without a rescan
    const T = st.T;
    for (const [i, sub] of j.moves) {
      const path = j.dest + '\\' + sub.split('/').join('\\');
      let di = T.dirs.findIndex(d => d.path === path);
      if (di < 0) { T.dirs.push({ id: T.dirs.length + 1, path, kind: 'sorted', included: false, project: -1 }); di = T.dirs.length - 1 }
      if (j.mode === 'move') T.dir[i] = di;
    }
    st.T = qTable(T); st.ver++;
    st.hist.unshift({ id: j.id, kind: j.mode, time: Date.now() / 1000, dest: j.dest, count: j.moved, size: j.bytes, undoable: j.mode === 'move', undone: false, label: '', _moves: j.moves.map(([i]) => [i, j.from[i]]) });
  }
  function binJob(id) { // Why: simulated Recycle Bin job: the files really leave the demo table when it finishes
    const j = st.jobs[id], f = Math.min(1, (Date.now() - j.t0) / 1200), done = Math.round(j.ids.length * f), bytes = j.sizes.slice(0, done).reduce((a, b) => a + b, 0);
    if (f >= 1 && j.state === 'running') {
      j.state = 'done'; const gone = new Set(j.ids), T = st.T, keep = T.id.map((_, i) => i).filter(i => !gone.has(T.id[i]));
      const cols = ['id', 'name', 'ext', 'cat', 'sub', 'size', 'mtime', 'ctime', 'atime', 'dir'], src = { dirs: T.dirs };
      for (const c of cols) src[c] = keep.map(i => T[c][i]);
      st.T = qTable(src); st.ver++;
      st.hist.unshift({ id, kind: 'trash', time: Date.now() / 1000, dest: '', count: j.ids.length, size: bytes, undoable: false, undone: false, label: '', _ops: j.names.map((n, k) => ({ src: n, dst: '', size: j.sizes[k] })) });
    }
    return { id, kind: 'trash', state: j.state, total: j.ids.length, done, moved: done, skipped: 0, bytes, errors: [], by_cat: {}, current: j.ids.slice(Math.max(0, done - 12), done).map((x, k) => ({ id: x })) };
  }
  const planIdx = b => { ensure(); const T = st.T, types = new Set((b.types || []).filter(Boolean)), fm = new Set(b.formats || []);
    return T.id.map((_, i) => i).filter(i => T.dirs[T.dir[i]].included && !VIEW_ONLY.has(T.cat[i]) && (!types.size || types.has(T.cat[i])) && (!fm.size || fm.has(T.ext[i]))) };
  const sprite = id => { const k = Number(id) % 12; if (!st.sprites[k]) { const c = document.createElement('canvas'); c.width = 240; c.height = 170; const g = c.getContext('2d');
    const P = [['#2e1065', '#a78bfa'], ['#0c4a6e', '#22d3ee'], ['#4c0519', '#f472b6'], ['#14532d', '#34d399'], ['#1e3a8a', '#60a5fa'], ['#78350f', '#fbbf24']][k % 6];
    const gr = g.createLinearGradient(0, 0, 240, 170); gr.addColorStop(0, P[0]); gr.addColorStop(1, P[1]); g.fillStyle = gr; g.fillRect(0, 0, 240, 170);
    g.fillStyle = 'rgba(255,255,255,.28)'; g.beginPath(); g.arc(70 + k * 8, 55, 22 + k, 0, 7); g.fill();
    g.fillStyle = 'rgba(0,0,0,.3)'; g.beginPath(); g.moveTo(0, 170); g.lineTo(80, 85 + k * 3); g.lineTo(150, 140); g.lineTo(190, 105); g.lineTo(240, 170); g.fill(); st.sprites[k] = c.toDataURL('image/jpeg', .8) } return st.sprites[k] };
  const later = v => new Promise(r => setTimeout(() => r(v), 60));
  const DEMO_BLOCKED = new Set('exe msi apk dmg deb iso img py js ps1 sql bat cmd sh'.split(' ')), DEMO_MACRO = new Set(['xlsm', 'docm', 'pptm']);
  function dateGroups(p, byDay) { // Why: same day/month grouping as the server's calendar and timeline (local time)
    ensure(); const T = st.T, f = qNorm(p), m = new Map();
    for (let i = 0; i < T.id.length; i++) {
      if (!qPass(T, i, f) || !(T[f.dcol][i] > 0)) continue;
      const key = ymd(new Date(T[f.dcol][i] * 1000)).slice(0, byDay ? 10 : 7), v = m.get(key) || [0, 0]; v[0]++; v[1] += T.size[i]; m.set(key, v);
    }
    return [...m].sort((a, b) => a[0] < b[0] ? -1 : 1).map(([k, v]) => [k, v[0], v[1]]);
  }
  function nearest(p) { // Why: an empty date filter suggests the closest days with files (same as the server)
    const T = st.T, f = qNorm(Object.assign({}, p, { date: '' })), [a, b] = qDateRange(p.date, p.from, p.to); let before = null, after = null;
    for (let i = 0; i < T.id.length; i++) { if (!qPass(T, i, f)) continue; const v = T[f.dcol][i]; if (v < a && (before == null || v > before)) before = v; if (v >= b && (after == null || v < after)) after = v }
    const key = v => v == null ? null : ymd(new Date(v * 1000)); return { before: key(before), after: key(after) };
  }
  return {
    table, version: () => st.ver,
    info: async () => ({ app: APP.name, tagline: APP.tagline, subline: APP.subline, version: '1.0.0', home: 'C:\\Users\\Alex', sep: '\\', os: 'demo', user: 'Alex Morgan', admin: false,
      quick: ['Downloads', 'Documents', 'Desktop', 'Pictures', 'Videos', 'Music'].map(n => ({ name: n, path: U + n, exists: true })), dest: U + 'AuraSortFiles', created_supported: true, has_index: !!st.scanDone }),
    drives: async () => [{ id: 'C:\\', root: 'C:\\', name: 'Local Disk', type: 'internal', fs: 'NTFS', ready: true, total: 512e9, used: 389e9, free: 123e9 },
      { id: 'D:\\', root: 'D:\\', name: 'Backup', type: 'external', fs: 'exFAT', ready: true, total: 1e12, used: 420e9, free: 580e9 },
      { id: 'Z:\\', root: 'Z:\\', name: 'Network drive', type: 'network', fs: '', ready: false }],
    browse: async p => {
      if (!p) return { path: '', parent: null, crumbs: [], dirs: ['Downloads', 'Documents', 'Desktop', 'Pictures', 'Videos', 'Music'].map(n => ({ name: n, path: U + n, protected: false, quick: true })).concat([{ name: 'Local Disk (C:)', path: 'C:\\', protected: false, drive: true }, { name: 'Backup (D:)', path: 'D:\\', protected: false, drive: true }]) };
      const parts = p.split('\\').filter(Boolean), crumbs = parts.map((n, i) => ({ name: i ? n : n + '\\', path: parts.slice(0, i + 1).join('\\') + (i ? '' : '\\') }));
      const kids = p.length <= 3 ? [['Users', false], ['Windows', true, 'protected system location'], ['Program Files', true, 'protected system location'], ['Photos', false]] : [['Projects', false], ['College', false], ['Trips 2025', false], ['node_modules', true, "'node_modules' is a system or tool folder"], ['Misc', false]];
      return { path: p, parent: parts.length > 1 ? parts.slice(0, -1).join('\\') + (parts.length === 2 ? '\\' : '') : '', crumbs, dirs: kids.map(([n, prot, why]) => ({ name: n, path: p.replace(/\\$/, '') + '\\' + n, protected: prot, reason: why || '' })) };
    },
    settings: async () => st.settings, saveSettings: async d => Object.assign(st.settings, d),
    estimate: async b => later({ files_per_s: 18400, est_files: 2400, complete: b.mode === 'quick', sample_files: 2400, sample_seconds: .4, low_s: 2, high_s: 5 }),
    scanStart: async b => { ensure(); st.scan = { state: 'running', mode: b.mode || 'quick', t0: Date.now(), paused: 0, f: 0 }; return { job: 'demo-scan' } },
    scanControl: async a => { const s = st.scan; if (!s) throw new Error('No scan is running.');
      if (a === 'pause' && s.state === 'running') { s.state = 'paused'; s.pausedAt = Date.now() / 1000 } else if (a === 'resume' && s.state === 'paused') { s.paused += Date.now() / 1000 - s.pausedAt; s.state = 'running' } else if (a === 'cancel') s.state = 'cancelled';
      return scanStatus() },
    scanStatus: async () => scanStatus(),
    summary: async () => summary(),
    files: async p => { ensure(); const r = qList(st.T, p); delete r._idx; if (!r.total && p.date) r.nearest = nearest(p); return r },
    fileIds: async p => { ensure(); const r = qList(st.T, Object.assign({}, p, { per: 500, page: 1 })); return { ids: r._idx.map(i => st.T.id[i]), sizes: r._idx.map(i => st.T.size[i]), size: r.size } },
    preview: async id => { ensure(); const i = st.T.pos.get(+id); if (i == null) throw new Error('That file is no longer in the index.'); const f = qRow(st.T, i);
      return { file: f, kind: f.cat === 'Images' ? 'image' : 'none', src: f.cat === 'Images' ? sprite(id) : '', demo: true, macro: DEMO_MACRO.has(f.ext),
        open_block: DEMO_BLOCKED.has(f.ext) || !f.ext ? 'For your safety, AuraSort never opens programs, scripts, shortcuts or disk images. Use Open location instead.' : '', created_supported: true } },
    openFile: async id => { ensure(); const i = st.T.pos.get(+id); if (i != null && DEMO_BLOCKED.has(st.T.ext[i])) throw new Error('For your safety, AuraSort never opens programs or scripts.'); return { ok: true, demo: true } },
    calendar: async p => ({ year: +p.year, days: dateGroups(Object.assign({}, p, { date: 'year', from: String(p.year) }), true) }),
    timeline: async p => ({ months: dateGroups(Object.assign({}, p, { date: '' }), false) }),
    rows: async ids => { ensure(); return ids.map(id => st.T.pos.get(id)).filter(i => i != null).map(i => qRow(st.T, i)) },
    extensions: async () => { ensure(); const T = st.T, m = {}; T.ext.forEach((e, i) => { const k = e + '|' + T.cat[i]; (m[k] = m[k] || { ext: e, cat: T.cat[i], n: 0, size: 0 }).n++; m[k].size += T.size[i] }); return { rows: Object.values(m).sort((a, b) => b.size - a.size), disk_total: 512e9 } },
    folders: async p => { ensure(); const T = st.T, out = T.dirs.map((d, di) => ({ id: d.id, path: d.path, kind: d.kind, project: d.project, project_path: d.project >= 0 ? PROJECTS[d.project] : '', included: d.included, n: 0, size: 0, by: {} }));
      T.id.forEach((_, i) => { const o = out[T.dir[i]]; o.n++; o.size += T.size[i]; o.by[T.cat[i]] = (o.by[T.cat[i]] || 0) + 1 });
      const q = (p.q || '').toLowerCase(); return out.filter(d => d.n && (!q || d.path.toLowerCase().includes(q)) && (!p.type || d.by[p.type]) && (p.kind !== 'warn' || d.kind !== 'ok')).sort((a, b) => b.n - a.n) },
    include: async b => { ensure(); const T = st.T;
      if (b.preset) T.dirs.forEach(d => d.included = b.preset === 'all' ? true : b.preset === 'none' ? false : d.kind === 'ok'); else T.dirs.forEach(d => { if ((b.ids || []).includes(d.id)) d.included = !!b.included });
      st.ver++; return { ok: true } },
    thumb: id => sprite(id),
    reveal: async () => ({ ok: true, demo: true }), revealJob: async () => ({ ok: true, demo: true }),
    disk: async p => /^d:/i.test(p || '') ? { path: 'D:\\', total: 1e12, used: 420e9, free: 580e9, dev: 2 } : { path: 'C:\\', total: 512e9, used: 389e9, free: 123e9, dev: 1 },
    plan: async b => { const idx = planIdx(b), T = st.T, by = {}; for (const i of idx) { const c = by[T.cat[i]] || (by[T.cat[i]] = { n: 0, size: 0, subs: {} }); c.n++; c.size += T.size[i]; c.subs[T.sub[i]] = (c.subs[T.sub[i]] || 0) + 1 }
      const dirs = sumBy(idx, 'dir'); return { by_cat: by, n: idx.length, size: idx.reduce((a, i) => a + T.size[i], 0), ndirs: Object.keys(dirs).length, dirs: Object.entries(dirs).sort((a, b) => b[1].n - a[1].n).slice(0, 200).map(([d, v]) => ({ path: T.dirs[d].path, n: v.n })), cross_bytes: 0, project_files: 0 } },
    execute: async b => { const idx = b.ids ? b.ids.map(id => st.T.pos.get(id)).filter(i => i != null) : planIdx(b), id = 'demo-' + Date.now(), T = st.T;
      st.jobs[id] = { id, t0: Date.now(), dur: Math.max(4500, Math.min(11000, idx.length * 5)), ops: idx.map(i => T.id[i]), total: idx.length, total_bytes: idx.reduce((a, i) => a + T.size[i], 0), k: 0, moved: 0, bytes: 0, by_cat: {}, current: [], moves: [], from: Object.fromEntries(idx.map(i => [i, T.dir[i]])), mode: b.mode, dest: b.dest, flat: b.flat, state: 'running' };
      return { job: id, count: idx.length, blocked: 0 } },
    job: async id => st.jobs[id] && st.jobs[id].kind === 'trash' ? binJob(id) : runJob(id),
    selection: async ids => { ensure(); const T = st.T, g = {}; let n = 0;
      for (const id of ids) { const i = T.pos.get(+id); if (i == null) continue; const d = T.dirs[T.dir[i]], k = [T.cat[i], d.kind, 'C:\\'].join('|'); const x = g[k] || (g[k] = [0, 0]); x[0]++; x[1] += T.size[i]; n++ }
      const groups = Object.entries(g).map(([k, v]) => k.split('|').concat(v));
      return { n, size: groups.reduce((a, x) => a + x[4], 0), groups, missing: ids.length - n, no_bin: 0, optin: st.settings.optin } },
    trash: async b => { ensure(); const T = st.T, idx = (b.ids || []).map(id => T.pos.get(+id)).filter(i => i != null);
      if (idx.length >= 100 && String(b.confirm_count) !== String((b.ids || []).length)) throw new Error(`Type ${(b.ids || []).length} to confirm.`);
      const ok = idx.filter(i => !(['project', 'assets'].includes(T.dirs[T.dir[i]].kind) && !b.allow_project) && !(VIEW_ONLY.has(T.cat[i]) && !(b.allow_viewonly || []).includes(T.cat[i])));
      const id = 'demo-bin-' + Date.now(), by = {}; for (const i of ok) { const c = by[T.cat[i]] || (by[T.cat[i]] = { n: 0, size: 0 }); c.n++; c.size += T.size[i] }
      st.jobs[id] = { kind: 'trash', t0: Date.now(), ids: ok.map(i => T.id[i]), sizes: ok.map(i => T.size[i]), cats: ok.map(i => T.cat[i]), names: ok.map(i => T.name[i]), state: 'running' };
      return { job: id, count: ok.length, blocked: idx.length - ok.length, by_cat: by } },
    mkdir: async (parent, name) => { if (!name || /[<>:"/\\|?*]/.test(name)) throw new Error('That folder name is not allowed.'); return { path: String(parent).replace(/\\$/, '') + '\\' + name } },
    openTrash: async () => ({ ok: true, demo: true }), aiStatus: async () => ({ demo: true }), interrupted: async () => [], deleteData: async () => ({ removed: ['demo data (nothing real is stored)'] }),
    integrityResults: async () => ({ total: 0, page: 1, pages: 1, per: 100, size: 0, rows: [], summary: { checked: 0, problems: 0, by_sev: {}, hint: '' } }),
    integrityStart: async () => { throw new Error('The demo does not read files. Run AuraSort on your computer to check them.') },
    duplicatesResults: async () => ({ total: 0, page: 1, pages: 1, per: 50, groups: [], summary: { groups: 0, wasted: 0, last: null } }),
    duplicatesStart: async () => { throw new Error('The demo does not read files. Run AuraSort on your computer to find duplicates.') },
    cleanup: async p => p.reason ? { total: 0, page: 1, pages: 1, per: 100, size: 0, rows: [] } : { groups: [] }, jobControl: async () => ({ ok: true }),
    historyItem: async id => { const h = st.hist.find(x => x.id === id); if (!h) throw new Error('History entry not found.'); return Object.assign({}, h, { _moves: undefined, ops: (h._ops || []).slice(0, 500), more: 0 }) },
    history: async () => st.hist.map(h => Object.assign({}, h, { _moves: undefined, _ops: undefined })),
    undo: async id => { const h = st.hist.find(x => x.id === id); if (!h) throw new Error('History entry not found.'); if (h.undone) throw new Error('This was already undone.');
      for (const [i, d] of h._moves || []) st.T.dir[i] = d; h.undone = true; h.undoable = false; st.T = qTable(st.T); st.ver++; return { restored: h.count, missing: 0 } },
    snapshots: async () => { const now = Date.now() / 1000; return [30, 24, 17, 10, 4, 0].map((d, i) => ({ time: now - d * DAY_S, drive: 'C:\\', used: 360e9 + i * 5.4e9, total: 512e9, bytype: {} })) }
  };
})();
