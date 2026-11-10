/* AuraSort - theme switch: Dark / Light / System, remembered in localStorage, applied with a 200 ms transition. */
'use strict';
const THEMES = [['light', 'sun', 'Light theme'], ['dark', 'moon', 'Dark theme'], ['system', 'monitor', 'Use the system theme']];
const SYSTEM_LIGHT = matchMedia('(prefers-color-scheme: light)');

function themePref() { // Why: storage may be blocked (private mode); fall back to the system theme
  try { return localStorage.getItem(THEME_KEY) || 'system' } catch (e) { return 'system' }
}
function applyTheme(pref, animate = true) { // Why: one place sets data-theme (charts/canvas read it via currentTheme)
  const light = pref === 'light' || (pref === 'system' && SYSTEM_LIGHT.matches);
  const root = document.documentElement;
  if (animate && motion()) { root.classList.add('theme-anim'); setTimeout(() => root.classList.remove('theme-anim'), 260) }
  root.dataset.theme = light ? 'light' : 'dark';
  root.dataset.themePref = pref;
  renderThemeSwitch();
}
function setTheme(pref) { // Why: remember the choice for next time
  try { localStorage.setItem(THEME_KEY, pref) } catch (e) { /* not remembered, still applied */ }
  applyTheme(pref);
}
function currentTheme() { return document.documentElement.dataset.theme || 'dark' }
function renderThemeSwitch() {
  const box = document.getElementById('theme-switch'); if (!box) return;
  const pref = themePref();
  box.innerHTML = THEMES.map(([k, icon, label]) => `<button class="${pref === k ? 'on' : ''}" data-a="theme" data-t="${k}" title="${label}" aria-label="${label}" aria-pressed="${pref === k}">${ic(icon)}</button>`).join('');
}
SYSTEM_LIGHT.addEventListener('change', () => { if (themePref() === 'system') applyTheme('system') });
