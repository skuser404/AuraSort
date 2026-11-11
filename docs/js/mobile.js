/* AuraSort - phones and small windows (under 900 px): the sidebar becomes a slide-in drawer (menu button, overlay,
   Esc, focus kept inside), a bottom tab bar with the five main places, a search button that opens the search field,
   and one banner that makes every failed API call visible (status code and message) instead of silent zeros. */
'use strict';
const TABS = [['dashboard', 'Dashboard', 'dash'], ['scan', 'Scan', 'scan'], ['media', 'Media', 'explore'], ['move', 'Sort', 'moveto'], ['more', 'More', 'list']];
const SMALL = () => matchMedia('(max-width: 899px)').matches;

function renderTabs() { // Why: one tap to the five places people use most on a phone; "More" opens the full menu
  const t = $('#tabs'); if (!t) return;
  const cur = S.view === 'search' || S.view === 'timeline' ? 'media' : S.view;
  t.innerHTML = TABS.map(([v, l, i]) => {
    const on = v === cur || (v === 'more' && !TABS.some(x => x[0] === cur));
    const off = v !== 'more' && v !== 'dashboard' && v !== 'scan' && NEEDS_INDEX.has(v) && !S.hasIndex;
    return `<button class="tab ${on ? 'on' : ''}" ${v === 'more' ? 'data-a="nav-open"' : `data-a="nav" data-v="${v}"`} ${on ? 'aria-current="page"' : ''} ${off ? 'disabled' : ''}>${ic(i)}<span>${l}</span></button>`;
  }).join('');
}

const Drawer = {
  open() {
    if (!SMALL()) return;
    document.body.classList.add('nav-open'); $('#nav-scrim').hidden = false;
    $('#nav-toggle').setAttribute('aria-expanded', 'true');
    setTimeout(() => { const f = $('#nav .nav-i.on') || $('#nav button'); f && f.focus() }, 30);
  },
  close(refocus = true) {
    if (!document.body.classList.contains('nav-open')) return;
    document.body.classList.remove('nav-open'); $('#nav-scrim').hidden = true;
    $('#nav-toggle').setAttribute('aria-expanded', 'false');
    if (refocus) $('#nav-toggle').focus();
  }
};
ACT['nav-open'] = () => Drawer.open();
ACT['nav-close'] = () => Drawer.close();
ACT['search-open'] = t => { // Why: on a phone the search field only takes room when you want it
  const open = !$('#top').classList.contains('search-open');
  $('#top').classList.toggle('search-open', open); t.setAttribute('aria-expanded', String(open));
  if (open) setTimeout(() => $('#gq').focus(), 30);
};
document.addEventListener('click', e => { if (e.target.closest && e.target.closest('#nav [data-a=nav], #tabs [data-a=nav]')) Drawer.close(false) }, true);   // close on route change
document.addEventListener('keydown', e => {
  if (!document.body.classList.contains('nav-open')) return;
  if (e.key === 'Escape') { e.preventDefault(); Drawer.close() }
  if (e.key === 'Tab') { // Why: focus stays inside the open menu
    const f = $$('#nav button:not(:disabled)'); if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus() }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus() }
  }
});
addEventListener('resize', () => { if (!SMALL()) Drawer.close(false) });

/* ---------------- failed API calls are always visible ---------------- */
function apiWarn(e, what) { // Why: a failed refresh used to leave old (or zero) numbers on screen without a word
  const b = $('#apiwarn'); if (!b || DEMO) return;
  if (!e) { b.hidden = true; b.innerHTML = ''; return }
  if (e.code === 'locked' || e.code === 'pin_not_set' || e.code === 'pin_cancelled') return;   // the unlock screen handles these
  b.innerHTML = `${ic('alert')}<span><b>${esc(what || 'Could not load the latest numbers')}.</b> ${esc(friendly(e))}${e.status ? ` <span class="mut">(HTTP ${e.status})</span>` : ''}</span>
    <button class="btn sm" data-a="apiwarn-reload">${ic('refresh')} Reload</button><button class="icon-btn" data-a="apiwarn-close" aria-label="Close">${ic('x')}</button>`;
  b.hidden = false;
}
ACT['apiwarn-reload'] = () => location.reload();
ACT['apiwarn-close'] = () => apiWarn(null);
