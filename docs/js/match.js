/* AuraSort - fuzzy file-name matching (no DOM: used by the search worker, the demo and highlighting).
   Name only; case-insensitive; extension ignored unless typed; substring > compact subsequence > one typo. */
'use strict';
function charMask(s) { // Why: one AND against this mask rejects most non-matching names instantly
  let m = 0;
  for (let i = 0; i < s.length; i++) { const c = s.charCodeAt(i); if (c >= 97 && c <= 122) m |= 1 << (c - 97); else if (c >= 48 && c <= 57) m |= 1 << (26 + (c - 48) % 5) }
  return m;
}
const popc = x => { x -= (x >>> 1) & 0x55555555; x = (x & 0x33333333) + ((x >>> 2) & 0x33333333); return (((x + (x >>> 4)) & 0x0F0F0F0F) * 0x01010101) >>> 24 };
const isBound = (s, i) => { if (i <= 0) return true; const a = s.charCodeAt(i - 1), b = s.charCodeAt(i); const al = c => c >= 97 && c <= 122, dg = c => c >= 48 && c <= 57; return !(al(a) || dg(a)) || dg(a) !== dg(b) };
let MR0 = new Int32Array(160), MR1 = new Int32Array(160), MR2 = new Int32Array(160);
function osa(a, s, p, n) { // Why: optimal-string-alignment distance (a swap counts as one edit), capped at 2
  const m = a.length;
  for (let j = 0; j <= n; j++) MR1[j] = j;
  for (let i = 1; i <= m; i++) {
    MR0[0] = i; let rowMin = i; const ai = a.charCodeAt(i - 1), ap = i > 1 ? a.charCodeAt(i - 2) : -1;
    for (let j = 1; j <= n; j++) {
      const sj = s.charCodeAt(p + j - 1);
      let v = MR1[j - 1] + (ai === sj ? 0 : 1); const del = MR1[j] + 1, ins = MR0[j - 1] + 1;
      if (del < v) v = del; if (ins < v) v = ins;
      if (j > 1 && ap === sj && ai === s.charCodeAt(p + j - 2) && MR2[j - 2] + 1 < v) v = MR2[j - 2] + 1;
      MR0[j] = v; if (v < rowMin) rowMin = v;
    }
    if (rowMin > 1) return 2;
    const t = MR2; MR2 = MR1; MR1 = MR0; MR0 = t;
  }
  return MR1[n];
}
function matchTok(s, T, hl, typo = true) { // Why: score one query token against one lowercase name (0 = no match)
  const t = T.t; let i = s.indexOf(t);
  if (i >= 0) {
    let j = i; while (j >= 0 && !isBound(s, j)) j = s.indexOf(t, j + 1);
    if (j >= 0) i = j;
    if (hl) hl.push([i, i + t.length]);
    return 100 + (i === 0 ? 40 : isBound(s, i) ? 25 : 0) - Math.min(i, 30) * .4 + 20 * t.length / s.length;
  }
  if (t.length >= 2) {
    let bSpan = 1e9, bP = -1;
    for (let p = s.indexOf(t[0]), tries = 0; p >= 0 && tries < 4; p = s.indexOf(t[0], p + 1), tries++) {
      let k = 1, last = p;
      for (let q = p + 1; q < s.length && k < t.length; q++) if (s.charCodeAt(q) === t.charCodeAt(k)) { k++; last = q }
      if (k === t.length && last - p + 1 < bSpan) { bSpan = last - p + 1; bP = p }
    }
    if (bP >= 0 && bSpan <= t.length * 2 + 1) {
      if (hl) { hl.push([bP, bP + 1]); for (let q = bP + 1, k = 1; q < s.length && k < t.length; q++) if (s.charCodeAt(q) === t.charCodeAt(k)) { hl.push([q, q + 1]); k++ } }
      return 60 - (bSpan - t.length) * 4 + (isBound(s, bP) ? 10 : 0);
    }
  }
  if (typo && t.length >= 4) {
    const need = t.length - 4;
    if (need > 0) { let h = 0; for (const b of T.bg) if (s.indexOf(b) >= 0) h++; if (h < need) return 0 }
    const m = t.length, c1 = t.charCodeAt(1), c2 = t.charCodeAt(2);
    for (let p = s.indexOf(t[0]); p >= 0; p = s.indexOf(t[0], p + 1)) {
      const s1 = s.charCodeAt(p + 1), s2 = s.charCodeAt(p + 2);
      if (s1 !== c1 && s2 !== c1 && s1 !== c2 && s2 !== c2) continue;
      for (let k = 0; k < 3; k++) { const L = k === 0 ? m : k === 1 ? m - 1 : m + 1; if (p + L <= s.length && osa(t, s, p, L) <= 1) { if (hl) hl.push([p, p + L]); return 22 } }
    }
  }
  return 0;
}
function tokens(q) { // Why: up to 6 tokens, each with its letter mask and bigrams precomputed once per query
  return String(q).normalize('NFC').toLowerCase().split(/\s+/).filter(Boolean).slice(0, 6)
    .map(t => ({ t, dot: t.includes('.'), m: charMask(t), bg: Array.from({ length: Math.max(0, t.length - 1) }, (_, i) => t.substr(i, 2)) }));
}
function scoreName(ln, lb, mask, toks, typo) { // Why: all tokens must match; extension ignored unless the token has a dot
  let total = 0;
  for (const T of toks) {
    if (!T.dot && popc(T.m & ~mask) > (typo ? 1 : 0)) return 0;
    const s = matchTok(T.dot ? ln : lb, T, null, typo); if (!s) return 0; total += s;
  }
  return total - lb.length * .05;
}
function hlHtml(name, q) { // Why: highlighted match for result rows (escaped character by character)
  const toks = tokens(q), ln = String(name).normalize('NFC').toLowerCase();
  if (!toks.length || ln.length !== name.length) return esc(name);
  const dot = ln.lastIndexOf('.'), lb = dot > 0 ? ln.slice(0, dot) : ln, mark = new Uint8Array(name.length);
  for (const T of toks) { const hl = []; matchTok(T.dot ? ln : lb, T, hl); for (const [a, b] of hl) for (let i = a; i < b; i++) mark[i] = 1 }
  let out = '', open = false;
  for (let i = 0; i < name.length; i++) { if (mark[i] && !open) { out += '<mark>'; open = true } else if (!mark[i] && open) { out += '</mark>'; open = false } out += esc(name[i]) }
  return out + (open ? '</mark>' : '');
}
