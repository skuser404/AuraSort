/* AuraSort - applies the saved theme before the first paint (no flash). Loaded synchronously in <head>. */
(function () {
  var pref = 'system';
  try { pref = localStorage.getItem('aurasort.theme') || 'system'; } catch (e) { /* storage blocked: use the system theme */ }
  var light = pref === 'light' || (pref === 'system' && window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches);
  document.documentElement.setAttribute('data-theme', light ? 'light' : 'dark');
  document.documentElement.setAttribute('data-theme-pref', pref);
})();
