/* AuraSort - product constants, icons, the 14 file categories and navigation. Rename the product here (and in core/config.py). */
'use strict';
const APP = { name: 'AuraSort', tagline: 'Make your files easier.', subline: 'Scan your whole PC, find anything fast, and sort files safely.' };
const PAGE_SIZE = 100;              // every list shows 100 files per page
const SEARCH_DEBOUNCE_MS = 140;
const FILTER_DEBOUNCE_MS = 220;
const POLL_SCAN_MS = 350;
const POLL_JOB_MS = 220;
const ESTIMATE_DEBOUNCE_MS = 700;
const TOAST_MS = 3200;
const TOAST_ERR_MS = 6000;
const TOAST_ACTION_MS = 15000;    // an error toast with buttons stays up longer (it also pauses while hovered)
// Server error codes -> what people read. Codes not listed here show the server's own (already friendly) message.
const ERROR_TEXT = {
  session_expired: 'This page belongs to an older server session. Reload the page to reconnect.',
  rate_limited: 'That was a lot of requests at once. Wait a moment, then try again.',
  internal: 'Something went wrong on our side. Your files were not changed.',
  too_large: 'That selection is too large to send in one go. Select fewer files and try again.',
  forbidden: 'This request was blocked for safety. Open the app from the address the server printed.',
  not_allowed: 'That action is not available.',
  index_busy: 'The file index is being used by another AuraSort window. Close the other window, then try again.',
  disk_full: 'The drive that holds your AuraSort data is full. Free some space, then try again.'
};
const THEME_KEY = 'aurasort.theme';
const NOTES_KEY = 'aurasort.notes';
const NOTES_MAX = 30;
const LAYOUT_KEY = 'aurasort.layout';
const DAY_S = 86400;
const TEXT_PREVIEW_BYTES = 200 * 1024;  // mirrors core/config.py
const TIMELINE_MONTHS = 120;            // the month timeline shows up to 10 years
const ZOOM_STEP = 1.25, ZOOM_MIN = 0.1, ZOOM_MAX = 8;
const YEAR_MIN = 1970, YEAR_MAX = 2100;
const SORTS = [['size', 'Biggest first'], ['smallest', 'Smallest first'], ['date', 'Newest first'], ['oldest', 'Oldest first'], ['name', 'Name A–Z']];

/* ---------------- icons: one hand-drawn sprite (docs/icons.svg), 20px grid, 1.5px stroke, currentColor ---------------- */
const ICON_NAMES = new Set(["image", "video", "audio", "doc", "pdf", "sheet", "archive", "installer", "disc", "code", "log", "font", "db", "file", "files", "dash", "storage", "explore", "large", "insight", "settings", "help", "history", "scan", "folder", "moveto", "folderplus", "drive", "usb", "network", "search", "link", "x", "shield", "check", "checkall", "undo", "external", "arrow", "lock", "info", "alert", "plus", "up", "play", "pause", "stop", "chevl", "chevr", "chevd", "grid", "list", "bell", "sun", "moon", "monitor", "clock", "calendar", "copy", "refresh", "tag", "eye", "zoomin", "zoomout", "fit", "trash"]);
const ic = (k, cls = '') => `<svg class="i ${cls}" aria-hidden="true"><use href="icons.svg#${ICON_NAMES.has(k) ? k : 'file'}"/></svg>`;
const LOGO = '<svg class="mark" viewBox="0 0 40 40" aria-hidden="true"><rect x="3" y="3" width="34" height="34" rx="10" fill="currentColor"/><path d="M13.5 28 20 12l6.5 16M15.9 22.5h8.2" fill="none" stroke="var(--accent-ink)" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

/* ---------------- the 14 categories (mirrors core/classify.py; vo = view-only) ---------------- */
const CATS = [
  { key: 'Images', ic: 'image', c: '#a78bfa' }, { key: 'Videos', ic: 'video', c: '#f472b6' }, { key: 'Audio', ic: 'audio', c: '#22d3ee' },
  { key: 'Documents', ic: 'doc', c: '#60a5fa' }, { key: 'PDFs', ic: 'pdf', c: '#fb7185' }, { key: 'Sheets & Slides', ic: 'sheet', c: '#34d399' },
  { key: 'Archives', ic: 'archive', c: '#fbbf24' }, { key: 'Installers & Apps', ic: 'installer', c: '#fb923c', vo: true },
  { key: 'Disk images', ic: 'disc', c: '#2dd4bf', vo: true }, { key: 'Code & Scripts', ic: 'code', c: '#a3e635', vo: true },
  { key: 'Text & Logs', ic: 'log', c: '#94a3b8', vo: true }, { key: 'Fonts', ic: 'font', c: '#e879f9', vo: true },
  { key: 'Databases', ic: 'db', c: '#38bdf8', vo: true }, { key: 'Other', ic: 'file', c: '#a1a1aa', vo: true }];
const CAT = Object.fromEntries(CATS.map(c => [c.key, c]));
const VIEW_ONLY = new Set(CATS.filter(c => c.vo).map(c => c.key));
const ALL_FILES = { key: '', ic: 'files', c: '#8b5cf6' };

/* ---------------- navigation ---------------- */
const NAV = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dash' },
  { id: 'storage', label: 'Storage Analysis', icon: 'storage', also: ['extensions', 'folders'] },
  { id: 'media', label: 'Media Explorer', icon: 'explore', also: ['search', 'timeline'] },
  { id: 'duplicates', label: 'Duplicates', icon: 'copy' },
  { id: 'large', label: 'Large Files', icon: 'large' },
  { id: 'cleanup', label: 'Cleanup', icon: 'trash' },
  { id: 'corrupted', label: 'Corrupted', icon: 'alert' },
  { id: 'move', label: 'Sort & move', icon: 'moveto' },
  { id: 'insights', label: 'Insights', icon: 'insight' },
  { h: 'Activity' },
  { id: 'history', label: 'History & undo', icon: 'history' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
  { id: 'help', label: 'Help', icon: 'help' }
];
const VIEWS = ['dashboard', 'storage', 'extensions', 'folders', 'media', 'search', 'timeline', 'duplicates', 'large', 'cleanup', 'corrupted', 'move', 'insights', 'history', 'settings', 'help', 'scan'];
const NEEDS_INDEX = new Set(['storage', 'extensions', 'folders', 'media', 'search', 'timeline', 'duplicates', 'large', 'cleanup', 'corrupted', 'move', 'insights']);
const LIST_VIEWS = new Set(['media', 'search', 'large', 'insights', 'corrupted', 'duplicates', 'cleanup']);   // pages whose files can be ticked (sticky selection bar)
