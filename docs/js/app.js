/* AuraSort - router, event wiring and start-up. */
'use strict';
const VIEWFN = { dashboard: viewDashboard, storage: viewStorage, extensions: viewExtensions, folders: viewFolders, media: viewMedia, search: viewSearch, timeline: viewTimeline,
  duplicates: viewDuplicates, cleanup: viewCleanup, corrupted: viewCorrupted, large: viewLarge, move: viewMove, insights: viewInsights, history: viewHistory, settings: viewSettings, help: viewHelp, scan: viewScan };
const TITLES = { dashboard: 'Dashboard', storage: 'Storage Analysis', extensions: 'All extensions', folders: 'Review folders', search: 'Search', timeline: 'Timeline', duplicates: 'Duplicates', cleanup: 'Cleanup', corrupted: 'Corrupted files',
  large: 'Large Files', move: 'Sort & move', insights: 'Insights', history: 'History', settings: 'Settings', help: 'Help', scan: 'Scan' };

function render(anim = true) { // Why: one render path for every view, with a soft fade/slide transition
  if (NEEDS_INDEX.has(S.view) && !S.hasIndex) S.view = 'scan';
  S.refresh = null; closePop(false);
  renderNav(); renderFilters();
  const v = $('#view'); VIEWFN[S.view](v); applyCss(v); renderSelBar();
  document.title = `${S.view === 'media' ? S.F.type || 'All files' : TITLES[S.view]} · ${APP.name}`;
  if (anim && motion()) { v.classList.remove('vt'); void v.offsetWidth; v.classList.add('vt') }
}
function go(view, mode = 'push') { // Why: navigation = state change + render + pushState
  closePreview();
  S.view = view; S.page = 1; S.fmtAll = false; render(); syncURL(mode); syncSearchBox();
  window.scrollTo({ top: 0, behavior: motion() ? 'smooth' : 'auto' }); $('#drawer').hidden = true;
}
function syncSearchBox() { const g = $('#gq'); if (g && document.activeElement !== g) g.value = S.view === 'search' ? S.F.q : '' }
async function refreshIndex() { // Why: after scans/moves the dashboard numbers and the search index version come from the server
  try { S.summary = await API.summary(); S.hasIndex = !!(S.summary && S.summary.scan); S.offline = false; apiWarn(null) }
  catch (e) { S.offline = true; apiWarn(e) }   // never silent: the old numbers stay, with a banner that says they could not be refreshed
  S.extData = null; renderNav();
}

/* ---------------- shared list actions ---------------- */
ACT.nav = t => { // Why: opening a page from the sidebar starts unfiltered (filters are per visit, links restore them)
  const v = t.dataset.v;
  if (['media', 'large', 'folders', 'search'].includes(v)) S.F = blankF({ q: v === 'search' ? S.F.q : '' });   // even when re-clicking the current page
  go(v);
};
ACT['nav-type'] = t => { S.F = Object.assign({}, S.F, { q: '', type: t.dataset.k, formats: new Set(), folder: '', dir: 0, dirPath: '' }); go('media') };
ACT.folderf = t => { // Why: "Show files" lists exactly that folder (its short name goes into the URL, never the full path)
  S.F = blankF({ folder: t.dataset.f, dir: +t.dataset.dir || 0, dirPath: t.dataset.p || '' }); go('media');
};
ACT.pg = t => { S.page = Math.max(1, +t.dataset.p); S.refresh && S.refresh(); window.scrollTo({ top: 0, behavior: motion() ? 'smooth' : 'auto' }) };
ACT.fmt = t => { const x = t.dataset.x; S.F.formats.has(x) ? S.F.formats.delete(x) : S.F.formats.add(x); S.page = 1; S.refresh && S.refresh(); syncURL('replace') };
ACT['fmt-clear'] = () => { S.F.formats = new Set(); S.page = 1; S.refresh && S.refresh(); syncURL('replace') };
ACT.fmtall = () => { S.fmtAll = !S.fmtAll; S.refresh ? S.refresh() : render(false) };
ACT.rmf = t => { const k = t.dataset.k;
  if (k === 'q') { S.F.q = ''; $('#gq').value = '' } else if (k === 'type') S.F.type = ''; else if (k === 'folder') Object.assign(S.F, { folder: '', dir: 0, dirPath: '' });
  else if (k === 'date') Object.assign(S.F, { date: '', from: '', to: '' }); else if (k.startsWith('format:')) S.F.formats.delete(k.slice(7));
  S.page = 1; render(false); syncURL('replace') };
ACT.clearf = () => { S.F = blankF({ q: S.view === 'search' ? '' : S.F.q, type: S.view === 'media' ? S.F.type : '', sort: S.F.sort, datefield: S.F.datefield }); if (S.view === 'search') $('#gq').value = ''; S.page = 1; render(false); syncURL('replace') };
ACT.reveal = t => API.reveal(+t.dataset.id).then(r => pathFallback(r) || (r && r.demo && toast('Demo: this would show the file in Explorer.'))).catch(e => toastError(e));
ACT.theme = t => { setTheme(t.dataset.t); if (S.view === 'settings') render(false) };
ACT.bell = () => toggleDrawer();
ACT['notes-clear'] = () => { S.notes = []; try { localStorage.removeItem(NOTES_KEY) } catch (e) { /* ignore */ } toggleDrawer(); toggleDrawer() };
ACT.copylink = async () => { syncURL('replace'); toast(await copyText(location.href) ? 'Link copied' : 'Could not copy. Copy the address bar instead.', 'ok') };
CH.sort = t => { S.F.sort = t.value; S.page = 1; S.refresh && S.refresh(); syncURL('replace') };
CH.folder = t => { S.F.folder = t.value.slice(0, 120); S.F.dir = 0; S.F.dirPath = ''; clearTimeout(CH.ft); CH.ft = setTimeout(() => { S.page = 1; S.refresh && S.refresh(); renderFilters(); syncURL('replace') }, FILTER_DEBOUNCE_MS) };

/* ---------------- events ---------------- */
const LIVE = new Set(['folder', 'dest', 'extq']);
const TIPS = '[data-tip], [data-tipt]';
document.addEventListener('click', e => { const t = e.target.closest('[data-a]'); if (t && !t.disabled && ACT[t.dataset.a]) { $('#tip').hidden = true; ACT[t.dataset.a](t, e) }
  if (!e.target.closest('#drawer, #bell')) $('#drawer').hidden = true;
  if (!e.target.closest('#pop, [data-a=datepop]') && document.contains(e.target)) closePop(false) });
document.addEventListener('change', e => { const t = e.target.closest('[data-c]'); if (t && CH[t.dataset.c] && !LIVE.has(t.dataset.c)) CH[t.dataset.c](t, e) });
document.addEventListener('input', e => { const t = e.target.closest('[data-c]'); if (t && LIVE.has(t.dataset.c) && CH[t.dataset.c]) CH[t.dataset.c](t, e) });
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'k') { e.preventDefault(); closePreview(); const g = $('#gq'); g.focus(); g.select(); return }
  if (Picker.key(e)) { e.preventDefault(); return }
  if (e.key === 'Escape' && !$('#modal').hidden) { closeModal(); return }
  if (e.key === 'Escape' && closePop()) return;
  if (previewKey(e)) { e.preventDefault(); return }
  const el = document.activeElement, typing = !!el && (/^(SELECT|TEXTAREA)$/.test(el.tagName) || (el.tagName === 'INPUT' && !/^(checkbox|radio|button|range|color)$/i.test(el.type)));
  if (e.key === '/' && !typing && $('#stage').hidden && $('#modal').hidden) { e.preventDefault(); $('#gq').focus(); return }
  if (e.key === 'Escape') { // Why: Esc closes the topmost thing; on a list with nothing open it clears the selection
    if (!$('#drawer').hidden) $('#drawer').hidden = true;
    else if (document.activeElement === $('#gq')) $('#gq').blur();
    else if (S.sel.size && LIST_VIEWS.has(S.view) && !typing) Sel.clear();
  }
  if (e.key === 'Enter' && e.target.matches && e.target.matches('[data-c="jump"]')) { const n = parseInt(e.target.value, 10); if (n > 0) { S.page = n; S.refresh && S.refresh() } }
});
$('#gq').addEventListener('input', e => onSearchInput(e.target.value));
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') closeModal() });
$('#pv').addEventListener('click', e => { if (e.target.id === 'pv') closePreview() });
document.addEventListener('pointerover', e => { const t = e.target.closest(TIPS); if (t) showTip(t, e.clientX, e.clientY) });
document.addEventListener('pointermove', e => { const t = e.target.closest(TIPS); if (t) showTip(t, e.clientX, e.clientY); else $('#tip').hidden = true });
document.addEventListener('focusin', e => { const t = e.target.closest && e.target.closest(TIPS); if (t) showTip(t); else $('#tip').hidden = true });
addEventListener('scroll', () => { $('#tip').hidden = true; closePop(false) }, { passive: true });
addEventListener('resize', () => closePop(false));
addEventListener('popstate', () => { // Why: Back/Forward restore the previous view and filters
  if (!$('#stage').hidden) return;
  const p = parseParams(location.search); closeModal(); closePreview();
  if (!S.hasIndex && p.has && p.view !== 'scan' && p.view !== 'history' && p.view !== 'settings' && p.view !== 'help') { S.pending = p; S.view = 'scan' } else applyParams(p);
  render(); syncSearchBox();
});

/* ---------------- start-up ---------------- */
(async function init() {
  const p = parseParams(location.search);
  try { history.replaceState({ app: 1 }, '', location.pathname + buildQuery(p) + location.hash) } catch (e) { /* sandboxed */ }   // strip unknown params first
  if (/Mac|iPhone|iPad/.test(navigator.platform || '')) $('#kbd').textContent = '⌘K';
  try { S.layout = localStorage.getItem(LAYOUT_KEY) || 'list' } catch (e) { S.layout = 'list' }
  renderThemeSwitch(); loadNotes(); renderFooter();
  await termsGate();   // nothing else starts until the current Terms are accepted
  await Pin.gate();    // ...and until a PIN exists and the app is unlocked (the server enforces both)
  try { [S.info, S.settings, S.drives] = await Promise.all([API.info(), API.settings(), API.drives()]) }
  catch (e) { S.offline = true; S.info = { quick: [], user: '' }; S.settings = {}; S.drives = []; toastError(e) }
  renderUser(); renderFooter();
  if (S.info && S.info.admin && S.info.os !== 'windows') toast('Running as root. AuraSort does not need it; start it as your normal user.', 'err');
  await refreshIndex();
  let st = null; try { st = await API.scanStatus() } catch (e) { st = null }
  if (st && ['running', 'paused'].includes(st.state)) { S.scan = st; S.view = 'scan'; if (p.has) S.pending = p; render(); pollScan(); return }
  if (S.hasIndex) applyParams(p.has ? p : { formats: [] });
  else if (p.has && !['scan', 'history', 'settings', 'help'].includes(p.view)) { S.pending = p; S.view = 'scan' }
  else S.view = p.view || 'dashboard';
  if (!DEMO && S.info && S.info.auto_scan && !S.hasIndex && !p.has) {   // first start: scan the usual folders, no clicks needed
    S.view = 'scan'; render(false); const st = scanSetup(); st.mode = 'quick'; startScan(); return;
  }
  render(false); syncSearchBox();
  if (S.hasIndex) syncURL('replace');
  if (DEMO && S.pending) { S.setup = null; scanSetup(); startScan() }   // demo: a shared link opens straight into its state
})();
