/* AuraSort - shared helpers: DOM, escaping, clear sizes/dates/durations, CSP-safe styling, lazy thumbnails. */
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
// Why: HTML-escape everything shown; bidi override characters are replaced so a name like "invoice‮gpj.exe" can't pose as a .jpg
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])).replace(/[‪-‮⁦-⁩]/g, '�');
const fmt = n => Math.round(Number(n) || 0).toLocaleString();
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const base = p => String(p).split(/[\\/]/).filter(Boolean).pop() || String(p);
const parentOf = p => { const s = String(p), i = Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/')); return i > 0 ? s.slice(0, i) : '' };
// Why: every percentage uses one rule: clamped to 0-100, and "n/a" when there is nothing to divide by (never 197%).
const share = (a, b) => (b > 0 && isFinite(a) && isFinite(b)) ? Math.min(100, Math.max(0, a / b * 100)) : null;
const pct = (a, b) => share(a, b) ?? 0;   // bar widths
const pctTxt = p => p == null || !isFinite(p) ? 'n/a' : (p > 0 && p < 1 ? '<1' : Math.round(Math.min(100, Math.max(0, p)))) + '%';
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)');
const motion = () => !REDUCED.matches;
const easeOut = t => 1 - Math.pow(1 - t, 3);
const easeIO = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
const rnd = (a, b) => a + Math.random() * (b - a);

/* ---------------- sizes: one clear format everywhere ---------------- */
const SIZE_UNITS = ['KB', 'MB', 'GB', 'TB', 'PB'];
function sz(b) { // Why: sizes read the same everywhere: 2 decimals under 10, 1 under 100, none above (4.27 MB, 42.7 MB, 427 MB)
  b = Math.max(0, Number(b) || 0);
  if (b < 1024) return `${Math.round(b)} B`;
  let i = -1;
  do { b /= 1024; i++ } while (b >= 1024 && i < SIZE_UNITS.length - 1);
  return `${b >= 100 ? b.toFixed(0) : b >= 10 ? b.toFixed(1) : b.toFixed(2)} ${SIZE_UNITS[i]}`;
}
const bytesTxt = b => `${fmt(b)} bytes`;
const sizeHtml = (b, cls = '') => `<span class="size num ${cls}" title="${bytesTxt(b)}">${sz(b)}</span>`; // exact bytes on hover

/* ---------------- dates & durations (local time zone) ---------------- */
const dt = t => t ? new Date(t * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—';
const dtt = t => t ? new Date(t * 1000).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
function ago(t) { // Why: Recent Activity reads better as "5 min ago"
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < DAY_S) return `${Math.floor(s / 3600)} h ago`;
  if (s < DAY_S * 7) return `${Math.floor(s / DAY_S)} d ago`;
  return dt(t);
}
function dur(s) { // Why: times read like "2 min 14 s" instead of raw seconds
  if (s == null || !isFinite(s)) return '—';
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} s`;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h} h ${m} min` : `${m} min${r ? ` ${r} s` : ''}`;
}
function durRange(a, b) { // Why: estimates are shown as a range ("~2–4 min")
  if (b < 60) return `~${Math.max(1, Math.round(a))}–${Math.max(2, Math.round(b))} s`;
  return `~${Math.max(1, Math.round(a / 60))}–${Math.max(1, Math.ceil(b / 60))} min`;
}
function greeting() { const h = new Date().getHours(); return h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening' }

const pad2 = n => String(n).padStart(2, '0');
const ymd = d => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;   // local calendar day key
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const monthLabel = ym => { const [y, m] = ym.split('-').map(Number); return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' }) };
const dayLabel = key => { const [y, m, d] = key.split('-').map(Number); return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' }) };

/* ---------------- paths ---------------- */
const pathHtml = p => { const s = String(p), i = Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/')); return `<span class="fpath" title="${esc(s)}">${esc(s.slice(0, i + 1))}<b>${esc(s.slice(i + 1))}</b></span>` };
const joinPath = (dir, name) => { const s = String(dir), sep = s.includes('\\') ? '\\' : '/'; return (s.endsWith(sep) ? s : s + sep) + name };
function driveName(p) { // Why: a short label for any mount: "C:", a network share "\\server\share", "My Disk" (macOS), "usb" (/media/usb) or "/"
  const s = String(p || '');
  if (/^[A-Za-z]:/.test(s)) return s.slice(0, 2).toUpperCase();
  const unc = s.match(/^[\\/]{2}([^\\/]+)[\\/]+([^\\/]+)/);
  if (unc) return `\\\\${unc[1]}\\${unc[2]}`;
  if (s.startsWith('/Volumes/')) return s.split('/')[2] || '/';
  if (/^\/storage\/emulated\/\d+\/?$/.test(s)) return 'phone';   // Android: was "0", which read like "0 files"
  if (/^\/storage\/[0-9A-F]{4}-[0-9A-F]{4}\/?$/i.test(s)) return 'SD card';
  const parts = s.split('/').filter(Boolean);
  return parts.length ? parts[parts.length - 1] : '/';
}

/* ---------------- misc ---------------- */
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms) } }
async function copyText(text) { // Why: clipboard API with a fallback for older browsers
  try { await navigator.clipboard.writeText(text); return true } catch (e) { /* fall back */ }
  const t = document.createElement('textarea'); t.value = text; t.setAttribute('readonly', ''); t.className = 'sr'; document.body.append(t); t.select();
  let ok = false; try { ok = document.execCommand('copy') } catch (e) { ok = false } t.remove(); return ok;
}
function qs(params) { // Why: skip empty values so URLs stay short
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '' && !(Array.isArray(v) && !v.length)) u.set(k, Array.isArray(v) ? v.join(',') : v);
  return u.toString();
}

/* ---------------- CSP: no inline styles or handlers ---------------- */
function applyCss(root) { // Why: style attributes in HTML are blocked by the Content-Security-Policy; CSSOM assignments are allowed
  if (!root || !root.querySelectorAll) return;
  if (root.dataset && root.dataset.css != null) { root.style.cssText = root.dataset.css; root.removeAttribute('data-css') }
  for (const el of root.querySelectorAll('[data-css]')) { el.style.cssText = el.dataset.css; el.removeAttribute('data-css') }
}
function markMixed(root) { // Why: "some selected" header checkboxes need the indeterminate property (there is no HTML attribute for it)
  for (const el of root.matches && root.matches('input[data-mixed]') ? [root] : root.querySelectorAll('input[data-mixed]')) { el.indeterminate = true; el.removeAttribute('data-mixed') }
}
new MutationObserver(muts => { for (const m of muts) for (const n of m.addedNodes) if (n.nodeType === 1) { applyCss(n); observeThumbs(n); markMixed(n) } })
  .observe(document.documentElement, { childList: true, subtree: true });
document.addEventListener('error', e => { const t = e.target; if (t && t.tagName === 'IMG' && t.hasAttribute('data-fallback')) t.remove() }, true);

/* ---------------- lazy thumbnails ---------------- */
const thumbIO = 'IntersectionObserver' in window ? new IntersectionObserver(entries => {
  for (const en of entries) if (en.isIntersecting) { const img = en.target; thumbIO.unobserve(img); if (img.dataset.src) { img.src = img.dataset.src; img.removeAttribute('data-src') } }
}, { rootMargin: '300px' }) : null;
function observeThumbs(root) { // Why: thumbnails load only when they scroll into view
  if (!root.querySelectorAll) return;
  const imgs = root.matches && root.matches('img[data-src]') ? [root] : [...root.querySelectorAll('img[data-src]')];
  for (const img of imgs) { if (thumbIO) thumbIO.observe(img); else { img.src = img.dataset.src; img.removeAttribute('data-src') } }
}
