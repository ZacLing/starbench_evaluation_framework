# Design

> Visual system for the StarBench Console (`starbench-gui`). Maintained by impeccable.
> Register: product. Color strategy: Restrained (white surface, indigo primary, verdict
> colors do the semantic work).
>
> Stack: React + Vite + Tailwind v4 + shadcn/ui (`gui-frontend/`). The tokens below
> are implemented as CSS variables in `gui-frontend/src/index.css` and consumed
> through the shadcn theme (`--primary`, `--muted`, ...) plus custom verdict colors
> (`--pass*`, `--fail*`, `--warn*`, `--live*`). Layout: sidebar app shell (Dashboard /
> Task library / Runs / New run), summary cards before tables, tables for detail.
> New run is a four-step wizard (tasks → executor → judge → review) with model-family
> cards, plain-language credential options, inline readiness checks, and an explicit,
> never-defaulted judge.

## Theme

Light, instrument-panel calm. The mood phrase: "the front panel of a measuring
instrument in a well-lit lab": pure white surface, one considered indigo, verdicts
that read at arm's length. No dark-mode terminal cosplay, no dashboard neon.

## Color

All colors OKLCH. Body background is pure white; the brand mood lives in the indigo
primary and the verdict chips, never in a tinted page background.

```css
:root {
  --bg:            oklch(1 0 0);                 /* page */
  --surface:       oklch(0.977 0.003 280);       /* panels, table headers */
  --surface-2:     oklch(0.958 0.005 280);       /* toolbar wells, code blocks */
  --border:        oklch(0.906 0.007 280);
  --border-strong: oklch(0.845 0.010 280);

  --ink:           oklch(0.235 0.018 285);       /* body text, >= 12:1 on bg */
  --muted:         oklch(0.490 0.022 285);       /* secondary text, >= 4.8:1 */
  --faint:         oklch(0.633 0.018 285);       /* disabled/tertiary, large or non-text */

  --primary:       oklch(0.500 0.160 280);       /* actions, links, selection, focus */
  --primary-strong:oklch(0.435 0.160 280);       /* hover */
  --primary-soft:  oklch(0.955 0.025 280);       /* selected-row tint */
  --on-primary:    oklch(1 0 0);

  --accent:        oklch(0.700 0.115 200);       /* running/info pulse, non-text uses */
  --accent-ink:    oklch(0.400 0.090 210);       /* info text on --accent-soft */
  --accent-soft:   oklch(0.950 0.035 200);

  --pass:          oklch(0.545 0.135 152);       /* non-text marks */
  --pass-ink:      oklch(0.400 0.110 152);       /* chip text, >= 4.5:1 on pass-soft */
  --pass-soft:     oklch(0.955 0.045 152);
  --fail:          oklch(0.545 0.185 27);
  --fail-ink:      oklch(0.420 0.155 27);
  --fail-soft:     oklch(0.950 0.032 27);
  --warn:          oklch(0.600 0.125 80);        /* timeout / interrupted */
  --warn-ink:      oklch(0.425 0.095 80);
  --warn-soft:     oklch(0.955 0.055 90);
}
```

Rules:

- Verdicts are always glyph + word + color (`✓ pass`, `✕ fail`, `◷ timeout`), never
  color alone.
- Chips use soft background + same-hue dark ink (pale fill, dark text). Solid fills
  (`--primary`) always carry `--on-primary` white text.
- `--accent` marks liveness (running runs, polling) and informational badges only.
  It never competes with verdict colors.
- Focus ring: 2px `--primary` outline with 2px offset, everywhere.

## Typography

Two families, both local stacks (no webfonts; the console must work offline):

- **UI / prose**: `-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif`
- **Data**: `ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace`
  for run ids, task ids, models, commands, timings, counts, hashes, JSON.

Fixed rem scale (product register, ratio ~1.2):

| Token        | Size      | Use |
|--------------|-----------|-----|
| `--t-caption`| 0.75rem   | meta labels, table headers (uppercase, +0.06em tracking) |
| `--t-data`   | 0.8125rem | table cells, mono data, chips |
| `--t-ui`     | 0.875rem  | controls, nav, secondary UI text |
| `--t-body`   | 1rem      | prose panes (evidence, final message, prompts) |
| `--t-section`| 1.125rem  | panel titles |
| `--t-title`  | 1.375rem  | page title (semibold) |

Weights: 400 body, 500 labels/controls, 600 titles and emphasis. `tabular-nums` on all
numeric table columns and timers. Prose panes capped at 72ch.

## Spacing, Shape, Elevation

- 4px scale: `--s1: 4px` `--s2: 8px` `--s3: 12px` `--s4: 16px` `--s5: 24px`
  `--s6: 32px` `--s7: 48px`. Tight inside groups (8-12), generous between sections (24-48).
- Radii: 6px controls and chips-with-square-content, 10px panels, 999px status chips.
- Borders do structure; shadows only for overlays (drawer, menus):
  `--shadow-overlay: 0 10px 30px oklch(0.2 0.02 285 / 0.18)`.
- Z scale: `--z-menu: 100; --z-sticky: 200; --z-backdrop: 300; --z-drawer: 310;
  --z-toast: 400; --z-tooltip: 500`.

## Layout

App shell: sticky top bar (wordmark, runs-dir path in mono, "New run" primary button)
over a full-width content region (max-width 1480px, 24px gutters). No side nav; the
object hierarchy is shallow (runs → run → task run) and breadcrumbs in the top bar
carry location. Tables are the primary surface: sticky header rows, row hover,
generous first column, right-aligned numerics.

## Components

- **Verdict chip**: pill, soft bg, glyph + word (+ `n/m` count where relevant).
- **Status chip**: run/executor state (`complete`, `running` with pulse dot,
  `interrupted`, `failed`, `timeout`).
- **KV grid**: dt/dd pairs for config panels; dt in `--t-caption` muted, dd in mono.
- **Expander row**: table rows expand in place for rubric evidence; chevron rotates,
  content slides 150ms.
- **Tabs**: underline style, 2px primary indicator for task-run detail panes.
- **Skeleton**: shimmering blocks while fetching; never spinners inside content.
- **Empty states**: teach the CLI (`starbench-run ...` snippet) or point to New run.
- **Command preview**: the launch form always renders the exact `starbench-run` argv
  it will execute, copyable; the GUI never hides the CLI truth.

## Motion

150ms (hover/expand) to 200ms (drawer/route) with `cubic-bezier(0.16, 1, 0.3, 1)`.
Motion only for state: expanding evidence, tab underline, running-pulse dot, skeleton
shimmer, toast entry. No page-load choreography. All of it collapses to instant under
`prefers-reduced-motion: reduce`.
