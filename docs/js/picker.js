/* AuraSort - folder picker (multi-select for scan/skip lists, single for destinations).
   Checkbox per row, click the name to open, selection persists while navigating, "included via parent", locked protected folders,
   keyboard: arrows move, Space ticks, Enter opens, Backspace goes up, Esc closes. */
'use strict';
const Picker = {
  st: null,
  open(opts) { // opts: { mode: 'scan'|'skip'|'dest', title, selected: [paths], start: path, okLabel, onDone(paths, startNow) }
    this.st = { mode: opts.mode, title: opts.title, onDone: opts.onDone, sel: new Set(opts.selected || []), data: null, focus: 0, okLabel: opts.okLabel || 'Use this folder', naming: false };
    modal('<div class="pk-head"><div class="skel xl"></div></div><div class="pk-list"><div class="skel row"></div><div class="skel row"></div></div>', 'picker');
    this.go(opts.start || '', true);
  },
  async go(path, quiet) { // Why: browse one level; errors (no access, unplugged) become a friendly message, not a crash
    try { this.st.data = await API.browse(path); this.st.focus = 0; this.st.naming = false; this.render() }
    catch (e) { if (!quiet) toast(friendly(e), 'err'); if (!this.st.data) this.go('') }
  },
  sep(p) { return String(p).includes('\\') ? '\\' : '/' },
  under(child, parent) { // Why: "included via parent" (case-insensitive, separator-aware)
    const c = child.toLowerCase(), p = parent.toLowerCase().replace(/[\\/]+$/, '');
    return c !== p && c.startsWith(p + this.sep(parent));
  },
  via(path) { for (const s of this.st.sel) if (this.under(path, s)) return s; return null },
  render() {
    const { data, sel, mode, title } = this.st, dest = mode === 'dest';
    const crumbs = `<div class="crumbs"><button data-a="pk-go" data-p="">This PC</button>` + (data.crumbs || []).map((c, i, a) => `<span class="dim">›</span><button class="${i === a.length - 1 ? 'cur' : ''}" data-a="pk-go" data-p="${esc(c.path)}">${esc(c.name)}</button>`).join('') + '</div>';
    const rows = data.dirs.map((d, i) => {
      const via = !dest && this.via(d.path), checked = sel.has(d.path) || !!via;
      const box = dest ? '' : `<input type="checkbox" data-c="pk-tick" data-p="${esc(d.path)}" ${checked ? 'checked' : ''} ${d.protected || via ? 'disabled' : ''} aria-label="Select ${esc(d.name)}">`;
      const tag = d.protected ? `<span class="badge b-mut" title="${esc(d.reason || 'protected')}">${ic('lock')} protected</span>` : via ? '<span class="badge b-mut">included via parent</span>' : '';
      return `<div class="pk-row ${d.protected ? 'locked' : ''} ${via ? 'via' : ''} ${i === this.st.focus ? 'focus' : ''}" role="option" aria-selected="${checked}" data-i="${i}" title="${esc(d.protected ? d.reason : d.path)}">
        ${box}<button class="pk-open" data-a="pk-go" data-p="${esc(d.path)}" ${d.protected ? 'disabled' : ''}>${ic(d.drive ? 'drive' : 'folder')}<b>${esc(d.name)}</b></button>${tag}</div>`;
    }).join('') || '<p class="mut" data-css="padding:16px">No sub-folders here.</p>';
    const chips = [...sel].map(p => `<span class="chip" title="${esc(p)}">${ic('folder')}<span class="t">${esc(p)}</span><button data-a="pk-unsel" data-p="${esc(p)}" aria-label="Remove ${esc(p)}">${ic('x')}</button></span>`).join('');
    const naming = dest && this.st.naming;
    const btns = dest ? (naming ? `<label class="fld pk-newname">${ic('folderplus')}<input type="text" id="pk-name" maxlength="120" placeholder="New folder name" aria-label="New folder name"></label><button class="btn ghost" data-a="pk-new-cancel">Cancel</button><button class="btn pri" data-a="pk-create">${ic('check')} Create</button>`
      : `<button class="btn ghost" data-a="pk-new" ${data.path ? '' : 'disabled title="Open a folder first"'}>${ic('folderplus')} New folder</button><span class="sb-sp"></span><button class="btn ghost" data-a="pk-cancel">Cancel</button><button class="btn pri" data-a="pk-here" ${data.path ? '' : 'disabled'}>${ic('check')} ${esc(this.st.okLabel)}</button>`)
      : `<button class="btn ghost" data-a="pk-cancel">Cancel</button><button class="btn" data-a="pk-done" ${sel.size ? '' : 'disabled'}>${ic('plus')} ${mode === 'skip' ? 'Add to skip list' : 'Add to scan list'}</button>`
        + (mode === 'scan' ? `<button class="btn pri" data-a="pk-start" ${sel.size ? '' : 'disabled'}>${ic('play')} Add &amp; start scan</button>` : '');
    const box = $('#modal .mbox');
    box.innerHTML = `<div class="pk-head"><h2>${esc(title)}</h2>${crumbs}</div>
      <div class="pk-list" role="listbox" aria-multiselectable="${!dest}" tabindex="0" id="pk-list">${data.parent != null && data.path ? `<div class="pk-row"><button class="pk-open" data-a="pk-go" data-p="${esc(data.parent)}">${ic('up')}<b>Up one level</b></button></div>` : ''}${rows}</div>
      <div class="pk-foot">${dest ? `<span class="mut">Selected: <b>${esc(data.path || 'choose a folder')}</b></span>` : `<div class="row between"><b>${sel.size} folder${sel.size === 1 ? '' : 's'} selected</b><span class="mut">Tick folders, or open one with its name.</span></div><div class="chips">${chips || '<span class="mut">Nothing selected yet.</span>'}</div>`}
      <div class="row" data-css="justify-content:flex-end">${btns}</div></div>`;
    if (naming) $('#pk-name').focus(); else $('#pk-list').focus();
  },
  async create() { // Why: "New folder" creates it inside the open folder (server checks the name and the location), then opens it
    const name = ($('#pk-name') || {}).value || '';
    if (!name.trim()) { toast('Type a name for the new folder.', 'err'); return }
    try { const r = await API.mkdir(this.st.data.path, name.trim()); toast('Folder created', 'ok'); await this.go(r.path) }
    catch (e) { toast(friendly(e), 'err'); $('#pk-name') && $('#pk-name').focus() }
  },
  tick(path, on) { if (on) { for (const s of [...this.st.sel]) if (this.under(s, path)) this.st.sel.delete(s); this.st.sel.add(path) } else this.st.sel.delete(path); this.render() },
  finish(start) { const done = this.st.onDone, paths = this.st.mode === 'dest' ? [this.st.data.path] : [...this.st.sel]; closeModal(); done(paths, start) },
  key(e) { // Why: full keyboard support inside the picker
    if (!this.st || $('#modal').hidden || !$('#pk-list')) return false;
    if (this.st.naming) { if (e.key === 'Enter') { this.create(); return true } if (e.key === 'Escape') { this.st.naming = false; this.render(); return true } return false }
    const rows = this.st.data.dirs, f = this.st.focus;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { this.st.focus = clamp(f + (e.key === 'ArrowDown' ? 1 : -1), 0, Math.max(0, rows.length - 1)); this.render(); $('#pk-list .pk-row.focus')?.scrollIntoView({ block: 'nearest' }); return true }
    if (e.key === ' ' && rows[f] && this.st.mode !== 'dest' && !rows[f].protected && !this.via(rows[f].path)) { this.tick(rows[f].path, !this.st.sel.has(rows[f].path)); return true }
    if (e.key === 'Enter' && rows[f] && !rows[f].protected) { this.go(rows[f].path); return true }
    if (e.key === 'Backspace' && this.st.data.parent != null) { this.go(this.st.data.parent || ''); return true }
    return false;
  }
};
ACT['pk-go'] = t => Picker.go(t.dataset.p);
ACT['pk-unsel'] = t => { Picker.st.sel.delete(t.dataset.p); Picker.render() };
ACT['pk-cancel'] = () => closeModal();
ACT['pk-done'] = () => Picker.finish(false);
ACT['pk-start'] = () => Picker.finish(true);
ACT['pk-here'] = () => Picker.finish(false);
ACT['pk-new'] = () => { Picker.st.naming = true; Picker.render() };
ACT['pk-new-cancel'] = () => { Picker.st.naming = false; Picker.render() };
ACT['pk-create'] = () => Picker.create();
CH['pk-tick'] = t => Picker.tick(t.dataset.p, t.checked);
