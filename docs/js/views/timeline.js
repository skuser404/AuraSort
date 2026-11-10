/* AuraSort - Timeline: a calendar heatmap (files per day of a year) and month-by-month bars.
   Selecting a day or a month lists exactly those files in Media Explorer (date=on / date=ym in the URL). */
'use strict';
const mediaTabs = cur => `<div class="seg" role="tablist" data-css="margin-bottom:18px">${[['media', 'Files', 'files'], ['timeline', 'Timeline', 'calendar']]
  .map(([v, l, i]) => `<button class="${cur === v ? 'on' : ''}" data-a="mtab" data-v="${v}" role="tab" aria-selected="${cur === v}">${ic(i)} ${l}</button>`).join('')}</div>`;
const FIELD_VERB = { modified: 'changed', created: 'created', accessed: 'last opened' };

function tlYear() { // Why: the year comes from the URL (date=year&from=YYYY), then from a day/month filter, then the newest year with files
  const F = S.F;
  if (F.date === 'year' && YEAR_RX.test(F.from)) return +F.from;
  if (/^\d{4}-/.test(F.from || '')) return +F.from.slice(0, 4);
  return S.tlYear || new Date().getFullYear();
}
function viewTimeline(v) {
  const F = S.F, field = F.datefield || 'modified';
  v.innerHTML = `<div class="page-head"><div><p class="eyebrow">Media Explorer</p><h1>Timeline</h1><p>How many files were ${FIELD_VERB[field]} on each day, in this computer's time zone. Select a day or a month to list those files.</p></div></div>
    ${mediaTabs('timeline')}
    <div class="toolbar"><select data-c="tltype" aria-label="Type"><option value="">All types</option>${CATS.map(c => `<option value="${esc(c.key)}" ${F.type === c.key ? 'selected' : ''}>${esc(c.key)}</option>`).join('')}</select>
      ${fieldSeg('tlfield')}<span class="sb-sp"></span>
      <div class="row nowrap"><button class="icon-btn" data-a="tlstep" data-d="-1" aria-label="Previous year">${ic('chevl')}</button><select data-c="tlyear" id="tlyears" aria-label="Year"><option>${tlYear()}</option></select><button class="icon-btn" data-a="tlstep" data-d="1" aria-label="Next year">${ic('chevr')}</button></div></div>
    <section class="card"><div class="card-h"><h2 id="cal-title">${tlYear()}</h2><small id="cal-sum" class="num"></small></div>
      <div class="cal-wrap" id="cal"><div class="skel" data-css="height:150px"></div></div>
      <div class="cal-legend"><span>Fewer</span>${[0, 1, 2, 3, 4].map(l => `<i class="cl l${l}"></i>`).join('')}<span>More files</span></div></section>
    <section class="card" data-css="margin-top:20px"><div class="card-h"><h2>Month by month</h2><small id="tl-sum" class="num"></small></div><div class="tl-wrap" id="tl"><div class="skel" data-css="height:190px"></div></div></section>`;
  S.refresh = loadTimeline; loadTimeline();
}
async function loadTimeline() {
  const token = (loadTimeline.n = (loadTimeline.n || 0) + 1), p = { type: S.F.type, datefield: S.F.datefield };
  let tl, cal;
  try {
    tl = await API.timeline(p);
    if (S.F.date !== 'year' && !/^\d{4}-/.test(S.F.from || '') && tl.months.length) { // default: the newest year that has files
      const now = new Date().getFullYear(), years = new Set(tl.months.map(m => +m[0].slice(0, 4)));
      if (!years.has(S.tlYear || now)) S.tlYear = Math.max(...years);
    }
    cal = await API.calendar(Object.assign({ year: tlYear() }, p));
  } catch (e) { if ($('#cal')) $('#cal').innerHTML = empty('alert', 'Could not load the timeline', esc(friendly(e)), '<button class="btn" data-a="retry">Try again</button>'); return }
  if (token !== loadTimeline.n || !$('#cal')) return;
  drawYears(tl.months); drawCalendar(cal); drawMonths(tl.months);
}
function drawYears(months) {
  const y = tlYear(), years = [...new Set(months.map(m => +m[0].slice(0, 4)).concat([y]))].sort((a, b) => b - a);
  const counts = new Map(); for (const [m, n] of months) counts.set(+m.slice(0, 4), (counts.get(+m.slice(0, 4)) || 0) + n);
  $('#tlyears').innerHTML = years.map(x => `<option value="${x}" ${x === y ? 'selected' : ''}>${x}${counts.get(x) ? ` · ${fmt(counts.get(x))} files` : ''}</option>`).join('');
  $('#cal-title').textContent = String(y);
}
function level(n, max) { return n ? Math.max(1, Math.min(4, Math.ceil(4 * Math.log(n + 1) / Math.log(max + 1)))) : 0 }
function drawCalendar(cal) { // Why: GitHub-style year grid, weeks as columns (Monday first), one cell per day
  const y = cal.year, days = new Map(cal.days.map(([d, n, s]) => [d, [n, s]])), max = Math.max(1, ...[...days.values()].map(v => v[0]));
  const lead = (new Date(y, 0, 1).getDay() + 6) % 7, out = [], monthCols = [];
  let k = 0, total = 0, bytes = 0, best = null;
  for (const d = new Date(y, 0, 1); d.getFullYear() === y; d.setDate(d.getDate() + 1), k++) {
    const key = ymd(d), v = days.get(key), n = v ? v[0] : 0, col = Math.floor((lead + k) / 7) + 2, row = ((lead + k) % 7) + 2;
    if (d.getDate() === 1) monthCols.push([d.getMonth(), col]);
    if (n) { total += n; bytes += v[1]; if (!best || n > best[1]) best = [key, n] }
    out.push(`<button class="cl l${level(n, max)}" data-css="grid-column:${col};grid-row:${row}" ${n ? `data-a="calday" data-d="${key}"` : 'disabled'} data-tipt="${esc(dayLabel(key))}|${n ? `${fmt(n)} ${n === 1 ? 'file' : 'files'} · ${sz(v[1])}` : 'No files'}" aria-label="${esc(dayLabel(key))}: ${fmt(n)} files"></button>`);
  }
  const weeks = Math.floor((lead + k - 1) / 7) + 1;
  const labels = monthCols.map(([m, col]) => `<span class="cal-m" data-css="grid-column:${col} / span 3;grid-row:1">${MONTHS[m]}</span>`).join('')
    + [['Mon', 2], ['Wed', 4], ['Fri', 6]].map(([l, r]) => `<span class="cal-w" data-css="grid-column:1;grid-row:${r}">${l}</span>`).join('');
  $('#cal').innerHTML = `<div class="cal" data-css="grid-template-columns:30px repeat(${weeks}, minmax(11px, 1fr))">${labels}${out.join('')}</div>`;
  $('#cal-sum').textContent = total ? `${fmt(total)} files · ${sz(bytes)} in ${y} · busiest day ${dayLabel(best[0])} (${fmt(best[1])})` : `No files ${FIELD_VERB[S.F.datefield || 'modified']} in ${y}`;
}
function drawMonths(months) { // Why: up to 10 years of months, oldest to newest; the selected year is highlighted
  const box = $('#tl'); if (!box) return;
  if (!months.length) { box.innerHTML = '<p class="mut">No dates recorded for these files.</p>'; $('#tl-sum').textContent = ''; return }
  const map = new Map(months.map(([m, n, s]) => [m, [n, s]])), last = months[months.length - 1][0], now = ymd(new Date()).slice(0, 7);
  const end = last > now ? last : now, [ey, em] = end.split('-').map(Number), keys = [];
  for (let i = TIMELINE_MONTHS - 1; i >= 0; i--) { const d = new Date(ey, em - 1 - i, 1); keys.push(`${d.getFullYear()}-${pad2(d.getMonth() + 1)}`) }
  const first = keys.findIndex(x => x >= months[0][0]), shown = keys.slice(Math.max(0, first)), max = Math.max(1, ...shown.map(x => (map.get(x) || [0])[0]));
  const older = months.filter(m => m[0] < shown[0]).reduce((a, m) => a + m[1], 0), y = tlYear();
  box.innerHTML = `<div class="tl">${shown.map((x, i) => { const v = map.get(x), n = v ? v[0] : 0;
    return `<div class="tl-col"><div class="tl-track"><button class="tl-bar ${n ? '' : 'zero'} ${+x.slice(0, 4) === y ? 'cur' : ''}" data-css="--h:${n ? Math.max(3, 100 * n / max).toFixed(1) : 2}%;animation-delay:${Math.min(i, 60) * 8}ms" ${n ? `data-a="calmonth" data-m="${x}"` : 'disabled'}
      data-tipt="${esc(monthLabel(x))}|${n ? `${fmt(n)} ${n === 1 ? 'file' : 'files'} · ${sz(v[1])}` : 'No files'}" aria-label="${esc(monthLabel(x))}: ${fmt(n)} files"></button></div><span class="tl-y">${x.endsWith('-01') || i === 0 ? x.slice(0, 4) : ''}</span></div>` }).join('')}</div>`;
  const best = months.reduce((a, m) => m[1] > a[1] ? m : a, months[0]);
  $('#tl-sum').textContent = `busiest month ${monthLabel(best[0])} (${fmt(best[1])} files)${older ? ` · ${fmt(older)} older files not shown` : ''}`;
}
ACT.mtab = t => go(t.dataset.v);
ACT.calday = t => { Object.assign(S.F, { date: 'on', from: t.dataset.d, to: '' }); go('media') };
ACT.calmonth = t => { Object.assign(S.F, { date: 'ym', from: t.dataset.m, to: '' }); go('media') };
ACT.tlfield = t => { S.F.datefield = t.dataset.k === 'modified' ? '' : t.dataset.k; render(false); syncURL('replace') };
ACT.tlstep = t => { const y = clamp(tlYear() + Number(t.dataset.d), YEAR_MIN, YEAR_MAX); Object.assign(S.F, { date: 'year', from: String(y), to: '' }); $('#cal-title').textContent = String(y); loadTimeline(); syncURL('replace') };
CH.tlyear = t => { Object.assign(S.F, { date: 'year', from: String(t.value), to: '' }); loadTimeline(); syncURL('replace') };
CH.tltype = t => { S.F.type = t.value; loadTimeline(); syncURL('replace') };
