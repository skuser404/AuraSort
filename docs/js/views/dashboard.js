/* AuraSort - Dashboard: greeting, drive gauge, the file-manager scene, the key numbers, space by type,
   biggest folders and files, insights, trend and recent activity. */
'use strict';
function pickDrive() { // Why: the gauge shows the drive the last scan covered (or the first ready drive)
  const ready = S.drives.filter(d => d.ready && d.total);
  const roots = (S.summary && S.summary.scan && S.summary.scan.roots) || [];
  const want = S.selectedDrive || (roots[0] && ready.find(d => roots[0].toLowerCase().startsWith(d.root.toLowerCase()))?.root) || (ready[0] && ready[0].root);
  return ready.find(d => d.root === want) || ready[0] || null;
}
function insightsFor(s) { // Why: rule-based observations from real numbers (no AI involved)
  const out = [], top = Object.entries(s.by_cat).sort((a, b) => b[1].size - a[1].size)[0], d = pickDrive();
  if (top && top[1].size) out.push({ icon: CAT[top[0]].ic, title: `${top[0]} take up ${pctTxt(pct(top[1].size, s.total_size))} of the scanned space`, body: `${fmt(top[1].n)} files, ${sz(top[1].size)}`, act: `data-a="nav-type" data-k="${esc(top[0])}"` });
  if (s.ready) out.push({ icon: 'moveto', title: `${fmt(s.ready)} files (${sz(s.ready_size)}) can be sorted`, body: 'You see exactly where each one goes before anything moves.', act: 'data-a="nav" data-v="move"' });
  if (d && d.used / d.total > .85) out.push({ icon: 'alert', title: `${driveName(d.root)} is ${pctTxt(pct(d.used, d.total))} full`, body: `${sz(d.free)} free on ${driveName(d.root)}. Large files are the quickest place to look.`, act: 'data-a="nav" data-v="large"' });
  const big = s.biggest_files && s.biggest_files[0];
  if (big) out.push({ icon: 'large', title: `Your biggest file is ${sz(big.size)}`, body: big.name, act: 'data-a="nav" data-v="large"' });
  if (s.projects && s.projects.length) out.push({ icon: 'shield', title: `${fmt(s.projects.length)} project folders are protected`, body: `${fmt(s.projects.reduce((a, p) => a + p.n, 0))} files stay where they are unless you choose otherwise.`, act: 'data-a="nav" data-v="folders"' });
  const inst = s.by_cat['Installers & Apps'];
  if (inst && inst.size > 1e8) out.push({ icon: 'installer', title: `${sz(inst.size)} of installers and apps`, body: `${fmt(inst.n)} files. Listed only, unless you opt in.`, act: 'data-a="nav-type" data-k="Installers &amp; Apps"' });
  return out;
}
const insightHtml = list => list.map(x => `<div class="insight"><span class="in-ic">${ic(x.icon)}</span><span><b>${esc(x.title)}</b><small class="mut">${esc(x.body)}</small></span><button class="btn sm ghost" ${x.act}>Review</button></div>`).join('') || '<p class="mut">Nothing to point out right now.</p>';
function mountScene(mode) { const svg = $('#view .scene'); if (svg) Scene.mount(svg, mode, S.summary) }

function welcome(v) { // Why: first run: what the app does and one clear next step
  v.innerHTML = `<section class="card hero"><div><p class="greet">${greeting()}${S.info && S.info.user ? ', ' + esc(S.info.user.split(/[\s.]+/)[0]) : ''}</p><h1>Welcome to ${esc(APP.name)}</h1>
    <p class="lead">${esc(APP.subline)} Everything stays on this computer, and nothing is ever permanently deleted.</p>
    <div class="row" data-css="margin-top:20px"><button class="btn pri lg" data-a="nav" data-v="scan">Scan my PC</button><button class="btn ghost lg" data-a="nav" data-v="help">How it works</button></div></div>
    <div class="hero-scene">${Scene.html('idle')}</div></section>
    <section class="card" data-css="margin-top:20px"><h2>How it works</h2><ol class="steps">
      <li><b>Scan.</b> Quick Scan reads your usual folders in seconds; Deep Scan reads whole drives. Only names, sizes and dates are read.</li>
      <li><b>Find.</b> Every file is listed with its size and folder, 100 per page, with search that forgives typos.</li>
      <li><b>Sort, safely.</b> You preview every move first. Projects and system folders are left alone, and every move can be undone.</li></ol></section>`;
  mountScene('idle');
}

function viewDashboard(v) {
  if (!S.hasIndex) return welcome(v);
  const s = S.summary, d = pickDrive(), up = d ? d.used / d.total : 0, ready = S.drives.filter(x => x.ready && x.total);
  const segs = CATS.map(c => ({ c, x: s.by_cat[c.key] || { n: 0, size: 0 } })), tot = s.total_size || 1;
  const bf = s.biggest_folders || [], mxF = bf[0] ? bf[0].size : 1, bfi = s.biggest_files || [], mxB = bfi[0] ? bfi[0].size : 1;
  const name = S.info && S.info.user ? S.info.user.split(/[\s.]+/)[0] : '', types = Object.values(s.by_cat).filter(x => x.n).length;
  v.innerHTML = `<div class="stack">
  <section class="card hero">
    <div><p class="greet">${greeting()}${name ? ', ' + esc(name) : ''}</p><h1>Dashboard</h1>
      <p class="lead">${s.scan ? `Last ${s.scan.mode === 'deep' ? 'Deep' : 'Quick'} Scan ${ago(s.scan.finished)}` : ''}</p>
      ${d ? `<div class="row" data-css="margin-top:12px">${ready.length > 1 ? `<select data-c="drive" aria-label="Drive">${ready.map(x => `<option value="${esc(x.root)}" ${x.root === d.root ? 'selected' : ''}>${esc(x.name)} (${esc(driveName(x.root))})</option>`).join('')}</select>` : `<span class="badge b-mut">${esc(d.name)} (${esc(driveName(d.root))})</span>`}</div>
      <dl class="drive-legend"><div><dt><i class="lg-used"></i>Used</dt><dd class="num">${sz(d.used)}</dd></div><div><dt><i class="lg-free"></i>Free</dt><dd class="num">${sz(d.free)}</dd></div><div><dt>Total</dt><dd class="num">${sz(d.total)}</dd></div></dl>` : ''}
      <div class="row" data-css="margin-top:18px"><button class="btn pri" data-a="nav" data-v="media">Explore all files</button><button class="btn ghost" data-a="nav" data-v="scan">${ic('refresh')} Scan again</button></div></div>
    <div class="gauge-wrap"><svg class="gauge" viewBox="0 0 220 220" role="img" aria-label="${Math.round(up * 100)}% of the drive is used"><circle class="trk" cx="110" cy="110" r="90"/><circle class="val" cx="110" cy="110" r="90" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100" data-to="${(100 - up * 100).toFixed(2)}"/></svg>
      <div class="gauge-c"><b class="num" data-count="${(up * 100).toFixed(1)}" data-f="pct">0%</b><small>${d ? esc(driveName(d.root)) + ' used' : 'used'}</small></div></div>
    <div class="hero-scene">${Scene.html()}</div>
  </section>
  <section class="card sumstrip">
    <div class="key"><small>Files found</small><b class="num" data-count="${s.total}">0</b><span class="mut">${sz(s.total_size)} across ${fmt(types)} of 14 file types</span></div>
    <dl class="minis">
      <div><dt>Ready to sort</dt><dd><b class="num">${fmt(s.ready)}</b> <span class="mut num">${sz(s.ready_size)}</span></dd></div>
      <div><dt>Left alone</dt><dd><b class="num">${fmt(s.left_alone)}</b> <span class="mut">${fmt(s.project_count)} project, ${fmt(s.asset_dirs)} asset folders</span></dd></div>
      ${d ? `<div><dt>Free on ${esc(driveName(d.root))}</dt><dd><b class="num">${sz(d.free)}</b> <span class="mut">of ${sz(d.total)}</span></dd></div>` : ''}
    </dl>
  </section>
  <section class="card"><div class="card-h"><h2>Space by file type</h2><small>${sz(s.total_size)} in ${fmt(s.total)} files. Select a type to open it.</small></div>
    <div class="segbar">${segs.filter(x => x.x.size).map(x => `<button class="sg" data-css="--c:${x.c.c};flex-grow:${(x.x.size / tot).toFixed(5)}" data-a="nav-type" data-k="${esc(x.c.key)}" data-tip="${esc(x.c.key)}" aria-label="${esc(x.c.key)}: ${sz(x.x.size)}, ${fmt(x.x.n)} files"></button>`).join('')}</div>
    <div class="type-tiles">${segs.map(x => `<button class="ttile ${x.x.n ? '' : 'zero'}" data-css="--c:${x.c.c}" data-a="nav-type" data-k="${esc(x.c.key)}" data-tip="${esc(x.c.key)}"><span class="t-ic">${ic(x.c.ic)}</span><span><b>${esc(x.c.key)}</b><small class="num">${sz(x.x.size)} · ${fmt(x.x.n)} files</small></span><span class="pct num">${pctTxt(pct(x.x.size, tot))}</span></button>`).join('')}</div>
  </section>
  <section class="card"><div class="card-h"><h2>Quick actions</h2><small>Each one opens a list to review first. Nothing happens without your OK.</small></div>
    <div class="qa-row">${[['cleanup', 'Clean junk files', 'Unfinished downloads, temp files, old installers'], ['duplicates', 'Find duplicates', 'Identical copies, newest kept'], ['large', 'Free up space', 'Biggest files first'], ['corrupted', 'Check for damaged files', 'Read-only check']]
      .map(([v, t, d]) => `<button class="qa-item" data-a="nav" data-v="${v}"><b>${t}</b><small class="mut">${d}</small></button>`).join('')}</div></section>
  <div class="grid g-5-7">
    <section class="card"><div class="card-h"><h2>Biggest folders</h2><small>by the files directly inside</small></div>
      ${bf.map(x => `<button class="rank" data-a="folderf" data-f="${esc(base(x.path))}" data-dir="${x.id}" data-p="${esc(x.path)}" title="${esc(x.path)}"><span class="rk-name">${ic('folder')}<span><b>${esc(base(x.path))} ${kindBadge(x)}</b><small>${esc(x.path)}</small></span></span><span class="mini"><i data-css="width:${pct(x.size, mxF).toFixed(1)}%"></i></span>${sizeHtml(x.size)}</button>`).join('') || '<p class="mut">No folders yet.</p>'}</section>
    <section class="card"><div class="card-h"><h2>Biggest files</h2><small>largest single files</small></div>
      ${bfi.map(f => `<div class="rank"><span class="rk-name" data-css="--c:${CAT[f.cat].c}">${fileIcon(f)}<span><button class="fn-open" data-a="preview" data-id="${f.id}"><b title="${esc(f.name)}">${esc(f.name)}</b></button><small>${esc(f.path)}</small></span></span><span class="mini"><i data-css="width:${pct(f.size, mxB).toFixed(1)}%"></i></span>${sizeHtml(f.size)}</div>`).join('') || '<p class="mut">No files yet.</p>'}</section>
  </div>
  <div class="grid g-7-5">
    <section class="card"><div class="card-h"><h2>Insights</h2><button class="btn sm ghost" data-a="nav" data-v="insights">Review suggestions</button></div>${insightHtml(insightsFor(s).slice(0, 4))}</section>
    <section class="card trend"><div class="card-h"><h2>Used space</h2><div class="seg" role="group" aria-label="Range">${[7, 30, 90].map(n => `<button class="${(S.trendDays || 30) === n ? 'on' : ''}" data-a="trend" data-n="${n}">${n} days</button>`).join('')}</div></div><div id="trend"><div class="skel" data-css="height:180px"></div></div></section>
  </div>
  <section class="card"><div class="card-h"><h2>Recent activity</h2><button class="link" data-a="nav" data-v="history">All history</button></div><div id="activity"><div class="skel row"></div><div class="skel row"></div></div></section>
  </div>`;
  countUps(v); mountScene('live'); loadTrend(); loadActivity();
}

async function loadTrend() { // Why: area chart from real post-scan snapshots; an honest message with fewer than 2
  const box = $('#trend'); if (!box) return;
  const d = pickDrive(), days = S.trendDays || 30;
  let pts = []; try { pts = await API.snapshots({ days, drive: d ? d.root : '' }) } catch (e) { pts = [] }
  if (!box.isConnected) return;
  if (pts.length < 2) { box.innerHTML = `<p class="mut" data-css="padding:18px 0">The chart needs two scans. Each scan saves one reading of used space on ${esc(d ? driveName(d.root) : 'the drive')}.</p>`; return }
  const W = 560, H = 180, P = 26, t0 = pts[0].time, t1 = pts[pts.length - 1].time || t0 + 1, lo = Math.min(...pts.map(p => p.used)) * .995, hi = Math.max(...pts.map(p => p.used)) * 1.005 || 1;
  const x = t => P + (W - 2 * P) * (t - t0) / Math.max(1, t1 - t0), y = u => H - P - (H - 2 * P) * (u - lo) / Math.max(1, hi - lo);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.time).toFixed(1)},${y(p.used).toFixed(1)}`).join('');
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Used space over the last ${days} days"><path class="axis" d="M${P},${H - P}H${W - P}"/><path class="area" d="${line}L${x(t1).toFixed(1)},${H - P}L${P},${H - P}Z"/><path class="line" d="${line}"/>
    <text x="${P}" y="${H - 6}">${esc(dt(t0))}</text><text x="${W - P}" y="${H - 6}" text-anchor="end">${esc(dt(t1))}</text><text x="${P}" y="14">${esc(sz(hi))}</text></svg>
    <p class="mut num" data-css="margin:6px 0 0">${sz(pts[0].used)} to ${sz(pts[pts.length - 1].used)} (${pts[pts.length - 1].used >= pts[0].used ? '+' : '−'}${sz(Math.abs(pts[pts.length - 1].used - pts[0].used))})</p>`;
}
async function loadActivity() { // Why: latest moves, scans and checks from History
  const box = $('#activity'); if (!box) return;
  let h = []; try { h = await API.history(6) } catch (e) { h = [] }
  if (!box.isConnected) return;
  const icon = { scan: 'scan', move: 'moveto', copy: 'copy', trash: 'trash', quarantine: 'shield', integrity: 'check', duplicates: 'files' };
  box.innerHTML = h.length ? h.map(x => `<div class="act"><span class="a-ic">${ic(icon[x.kind] || 'history')}</span><span><b>${esc(histLabel(x))}${x.undone ? ' <span class="badge b-ok">undone</span>' : ''}</b><small class="mut">${x.size ? sz(x.size) + ' · ' : ''}${x.dest ? esc(base(x.dest)) + ' · ' : ''}${ago(x.time)}</small></span></div>`).join('')
    : '<p class="mut">Nothing yet. Scans and moves will show up here.</p>';
}
ACT.trend = t => { S.trendDays = +t.dataset.n; $$('.trend .seg button').forEach(b => b.classList.toggle('on', b === t)); loadTrend() };
CH.drive = t => { S.selectedDrive = t.value; render(false) };
