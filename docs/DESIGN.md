# AuraSort design

AuraSort should look like a tool: in the spirit of Windows File Explorer and a disk analyser, calm and dense, with
real numbers up front. Nothing on screen is decoration.

## Principles

- **Neutral greys and one accent.** The accent (blue) marks the primary action, the current page and focus. It is not
  used for decoration.
- **Flat surfaces.** Cards are a 1 px border on a slightly lighter surface. Shadows are used only for things that float
  above the page: dialogs, toasts, menus and the tooltip.
- **Subtle radius.** 6 px for controls, 8 px for cards. There are no pills.
- **Hierarchy through type**, not colour or boxes. Layouts are left-aligned. Data that is tabular is shown in a table
  (space by type, sort preview, file lists).
- **Plain copy.** Short labels, real numbers, and errors that say what happened and what to do. No exclamation marks,
  no emoji, no marketing words.
- **Motion only where it explains something:** scan progress, the move animation with real file names, and one short
  shake on a wrong PIN. Transitions are 150-200 ms. Nothing loops for decoration, and `prefers-reduced-motion` turns
  movement off.

## Tokens

Every value lives in `docs/css/theme.css`, the single source of truth. `app.css` and `stage.css` only reference tokens.

| Token | Value |
|---|---|
| Font | Inter (variable, self-hosted in `docs/fonts`, SIL Open Font License), falling back to Segoe UI Variable, Segoe UI, system-ui |
| Type scale | 12, 13, 14 (body), 16, 20, 24 (page title) px; weights 400 / 600 |
| Spacing | 4, 8, 16, 24, 32 px (`--s0` to `--s4`) |
| Radius | 3 px (swatches), 6 px (controls), 8 px (cards) |
| Accent | light `#0b5cb8`, dark `#5aa2ee` (text on it: white / `#0b1220`) |
| Motion | 160 ms, `cubic-bezier(.2, 0, 0, 1)` |

## Colour for data

Category colour marks data only: bar segments, a 10 px swatch next to the type's name, and the files flying in the
move animation. Icons in lists, tabs and tiles are neutral grey, and the label names the type.

The 7 sortable types use the validated categorical palette in a fixed order (it never depends on rank). All 7 view-only
types share one neutral grey, so the storage bar shows them as a single "view-only" segment instead of seven similar
greys.

| Slot | Type | Light | Dark |
|---|---|---|---|
| 1 | Images | `#2a78d6` | `#3987e5` |
| 2 | Videos | `#eb6834` | `#d95926` |
| 3 | Audio | `#1baf7a` | `#199e70` |
| 4 | Documents | `#eda100` | `#c98500` |
| 5 | PDFs | `#e87ba4` | `#d55181` |
| 6 | Sheets & Slides | `#008300` | `#008300` |
| 7 | Archives | `#6250d6` | `#9085e9` |
| view-only | Installers, disk images, code, logs, fonts, databases, other | `#8f8f8a` | `#6b6b67` |

Validation (`validate_palette.js`, adjacent pairs, the order above):

- **Light:** CVD ΔE 9.1 (target 8 or more), normal-vision ΔE 19.6 (floor 15). Three light slots are below 3:1
  contrast, so every segment is labelled (tooltip, table row, aria-label) and the Storage page has the table view.
- **Dark:** CVD ΔE 8.4, normal-vision ΔE 19.3, every slot at 3:1 or more.
- The neutral grey fails the chroma check on purpose: it is the "other" bucket.

## Icons

There is one icon set, `docs/icons.svg`: 20 px grid, 1.5 px stroke, round caps and joins, `currentColor`, no fills.
It is drawn in the same style as Lucide but is AuraSort's own set. Each of its 64 icons is referenced by the code, and they are
consistent with each other, so swapping them for Lucide would change nothing a user can see.

## Removed in 1.1.3

- The PIN screen bear: its eyes followed the cursor, and it covered and uncovered them. The screen now shows a padlock
  and an "Enter PIN" form.
- "Good morning, name" greetings, the "Make your files easier." tagline and the decorative animated scene on the
  dashboard.
- The purple-to-blue gradients on the gauge, ring, trend line and buttons.
- Counting-up numbers: numbers show their value at once.
- Rainbow category colours (14 saturated hues) and tinted icon squares.
- The equal grid of 14 type tiles, replaced by a table.
- Resting shadows on cards, and pill shapes.
