# Design

Flight-deck instrument theme: warm graphite surfaces, one signal-amber accent carrying risk, mono numerals, hairline dividers. Dark is the default (an ops room, low ambient light, long sessions); light mode is a first-class alternate.

## Color

Dark (default, `[data-theme="dark"]`):

| token | value | role |
|---|---|---|
| `--bg` | `#141317` | app background (warm graphite) |
| `--surface` | `#1b1a20` | primary panels |
| `--panel` | `#222128` | raised blocks, table header |
| `--line` | `#2f2e36` | hairline dividers |
| `--ink` | `#edebe6` | primary text |
| `--ink2` | `#b9b6c0` | secondary text |
| `--mut` | `#908d99` | labels, captions (AA on bg) |
| `--amber` | `#f2a33c` | THE accent: risk, flags, primary actions |
| `--amber-deep` | `#c97f1b` | amber pressed/borders |
| `--red` | `#ff6252` | high-risk end of scale only |
| `--green` | `#5fc78f` | confirmed/ok states only |
| `--focus` | `#8ab4ff` | focus rings (never decorative) |

Light (`[data-theme="light"]`): `--bg #f2f1ef`, `--surface #ffffff`, `--panel #f7f6f4`, `--line #dcdad6`, `--ink #1d1c21`, `--ink2 #46444c`, `--mut #6a6771`, `--amber #a86603` (text-safe), `--amber-raw #e8992e` (fills), `--red #bb2d13`, `--green #17714a`.

Strategy: Restrained — amber is the only voice; red and green are semantic endpoints, never decoration.

Chart categorical palette (validated with the dataviz six-check script against each surface; CVD floor band covered by direct labels on every bar row):

| category | dark (`#1b1a20`) | light (`#ffffff`) |
|---|---|---|
| Supply | `#cc7f14` | `#b56f07` |
| Forecasting | `#8f7bee` | `#6b53d8` |
| Logistics | `#1795b1` | `#0b7fa3` |
| Customer | `#279c61` | `#17714a` |
| Other | `#c76fa1` | `#b05a86` |

Heatmap = sequential single-hue amber ramp (graphite-tinted low → saturated amber high) with the measured % printed in every cell; red never enters the ramp.

## Typography

One sans family for UI (`system-ui` stack); `ui-monospace` for every numeral, code, and axis (`tabular-nums`). Scale ratio 1.125 on a fixed rem scale: 12 / 13.5 / 15 (body) / 17 / 19 / 24 / 34 (hero numeral). Hero numerals are mono, weight 500. No display fonts.

## Components

- **Tab bar**: top strip, amber underline on the active tab, mono labels.
- **Stat block**: mono numeral + one-line plain-language sentence under it (no bare hero-metric grids; every number gets its sentence).
- **Charts**: hand-rolled SVG; hairline axes in `--line`; amber for the signal series; band fills at 12% opacity; no gridline forests.
- **Risk heatmap** (the signature): 2x4 cell matrix, graphite -> amber -> red ramp, measured % in each cell (mono), n underneath in `--mut`.
- **Register table**: dual-sticky data window (sticky header + lead column), impact bars in amber (measured) vs outlined amber (forward proxy), confidence chips, per-row reason expand.
- **Chips**: 1px border, no fills except active state (amber fill, dark ink).
- **Q tooltips**: fixed-position glossary layer, `--panel` background, 1px `--line` border.

## Motion

150–250ms, `cubic-bezier(0.22, 1, 0.36, 1)` (ease-out-quint). Motion conveys state only: tab switch crossfade, row expand, chart draw-in once on load. Full `prefers-reduced-motion` fallback to instant transitions.

## Voice

Labels sentence-case. No exclamation marks. Captions state caveats plainly ("dispersion, not a confidence interval").
