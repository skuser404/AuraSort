/* AuraSort - date filter: a popover with quick ranges, one day, a range, a month or a year,
   on the Modified, Created or Last-opened date (local time zone). */
'use strict';
const DATE_QUICK = [['', 'Any time'], ['today', 'Today'], ['yesterday', 'Yesterday'], ['7d', 'Last 7 days'], ['30d', 'Last 30 days'], ['month', 'This month']];
const DATE_FIELD_LABELS = [['modified', 'Modified'], ['created', 'Created'], ['accessed', 'Last opened']];
const Pop = { anchor: null };

function dateBtn() { // Why: the toolbar button shows the active date filter in plain words
  const F = S.F;
  return `<button class="btn ghost dbtn ${F.date ? 'on' : ''}" data-a="datepop" aria-haspopup="dialog" aria-expanded="false">${ic('calendar')}<span>${F.date ? esc(dateLabel()) : 'Any date'}</span>${ic('chevd')}</button>`;
}
function createdOk() { return !S.info || S.info.created_supported !== false }
function fieldSeg(act) { // Why: the same Modified / Created / Last opened switch in the popover and on the Timeline
  const cur = S.F.datefield || 'modified';
  return `<div class="seg sm" role="group" aria-label="Which date">${DATE_FIELD_LABELS.map(([k, l]) => `<button class="${cur === k ? 'on' : ''}" data-a="${act}" data-k="${k}" aria-pressed="${cur === k}"
    ${k === 'created' && !createdOk() ? `disabled title="${esc(S.info.created_note || 'Not available on this system')}"` : ''}>${l}</button>`).join('')}</div>`;
}
function datePopHtml() {
  const F = S.F, val = m => F.date === m ? esc(F.from) : '';
  return `<div class="pop-h"><b>Filter by date</b>${fieldSeg('dfield')}</div>
    <div class="chips">${DATE_QUICK.map(([k, l]) => `<button class="chip ${(F.date || '') === k ? 'on' : ''}" data-a="dquick" data-k="${k}">${l}</button>`).join('')}</div>
    <div class="pop-grid">
      <label for="d-on">On day</label><input type="date" id="d-on" value="${val('on')}" min="${YEAR_MIN}-01-01" max="${YEAR_MAX}-12-31"><button class="btn sm" data-a="dapply" data-m="on">Apply</button>
      <label for="d-a">Between</label><span class="row nowrap"><input type="date" id="d-a" value="${val('between')}" aria-label="From day"><span class="mut">–</span><input type="date" id="d-b" value="${F.date === 'between' ? esc(F.to) : ''}" aria-label="To day"></span><button class="btn sm" data-a="dapply" data-m="between">Apply</button>
      <label for="d-ym">Month</label><input type="month" id="d-ym" value="${val('ym')}"><button class="btn sm" data-a="dapply" data-m="ym">Apply</button>
      <label for="d-y">Year</label><input type="number" id="d-y" min="${YEAR_MIN}" max="${YEAR_MAX}" placeholder="${new Date().getFullYear()}" value="${val('year')}"><button class="btn sm" data-a="dapply" data-m="year">Apply</button>
    </div>
    <div class="pop-foot"><span class="mut">Dates use this computer's time zone.</span><button class="link" data-a="nav" data-v="timeline">${ic('calendar')} Open the calendar</button></div>`;
}

/* ---------------- popover plumbing ---------------- */
function openPop(anchor, html) {
  const p = $('#pop'); p.innerHTML = html; p.hidden = false; Pop.anchor = anchor; anchor.setAttribute('aria-expanded', 'true');
  const r = anchor.getBoundingClientRect(), w = p.offsetWidth, h = p.offsetHeight;
  p.style.left = clamp(r.left, 8, innerWidth - w - 8) + 'px';
  p.style.top = (r.bottom + 8 + h > innerHeight && r.top - h - 8 > 0 ? r.top - h - 8 : r.bottom + 8) + 'px';
  setTimeout(() => { const f = p.querySelector('.chip.on, input, button'); f && f.focus() }, 20);
}
function closePop(refocus = true) {
  const p = $('#pop'); if (p.hidden) return false;
  p.hidden = true; p.innerHTML = '';
  if (Pop.anchor && document.contains(Pop.anchor)) { Pop.anchor.setAttribute('aria-expanded', 'false'); if (refocus) Pop.anchor.focus() }
  Pop.anchor = null; return true;
}

/* ---------------- actions ---------------- */
function setDate(date, from = '', to = '') { // Why: every date change re-lists from page 1 and updates the URL
  Object.assign(S.F, { date, from: date ? from : '', to: date ? to : '' });
  closePop(false); S.page = 1; render(false); syncURL('replace');
}
ACT.datepop = t => { if (Pop.anchor === t && !$('#pop').hidden) { closePop(); return } openPop(t, datePopHtml()) };
ACT.dquick = t => setDate(t.dataset.k);
ACT.dapply = t => {
  const m = t.dataset.m, v = id => (($('#' + id) || {}).value || '').trim();
  if (m === 'on' && DAY_RX.test(v('d-on'))) return setDate('on', v('d-on'));
  if (m === 'between' && DAY_RX.test(v('d-a'))) return setDate('between', v('d-a'), DAY_RX.test(v('d-b')) ? v('d-b') : v('d-a'));
  if (m === 'ym' && MONTH_RX.test(v('d-ym'))) return setDate('ym', v('d-ym'));
  if (m === 'year' && dateArgsOk('year', v('d-y'))) return setDate('year', v('d-y'));
  toast(m === 'year' ? `Type a year between ${YEAR_MIN} and ${YEAR_MAX}.` : 'Pick a date first.', 'err');
};
ACT.dfield = t => { // Why: switching Modified/Created/Last opened re-runs an active date filter; otherwise it is remembered for next time
  S.F.datefield = t.dataset.k === 'modified' ? '' : t.dataset.k;
  if (S.F.date) { closePop(false); S.page = 1; render(false); syncURL('replace'); return }
  $$('#pop [data-a=dfield]').forEach(b => { b.classList.toggle('on', b === t); b.setAttribute('aria-pressed', b === t) });
};
ACT.nearday = t => setDate('on', t.dataset.d);
function nearestHtml(n) { // Why: an empty day suggests the closest days that do have files
  if (!n || (!n.before && !n.after)) return '';
  return (n.before ? `<button class="btn ghost" data-a="nearday" data-d="${esc(n.before)}">${ic('chevl')} ${esc(dayLabel(n.before))}</button>` : '')
    + (n.after ? `<button class="btn ghost" data-a="nearday" data-d="${esc(n.after)}">${esc(dayLabel(n.after))} ${ic('chevr')}</button>` : '');
}
