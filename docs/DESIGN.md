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

Light, calm, HSW-Eval-reference dashboard: a light-gray canvas under white cards,
one considered indigo, verdicts that read at arm's length. No dark-mode terminal
cosplay, no dashboard neon.

## Color

All colors OKLCH. The page canvas is a near-white gray (`oklch(0.977 0.003 280)`)
and cards/sidebar are pure white; the brand mood lives in the indigo primary and
the status colors.

```css
:root {
  --bg:            oklch(0.977 0.003 280);       /* page canvas (cards stay white) */
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

App shell: collapsible sidebar (primary destinations + Setup group) beside a sticky
top bar (breadcrumbs in mono, "New experiment" primary button) over a content region
capped at 1400px with 24px gutters. Breadcrumbs carry location within the shallow
object hierarchy (runs → run → task run). Tables are the primary surface: sticky
header rows, row hover, generous first column, right-aligned numerics.

Runs follows the HSW Eval reference layout: page header with freshness controls
("Last updated" + working auto-refresh switch), a KPI stat strip (all figures
computed from disk), a filter row (search + status/runtime selects), the ledger
table (dot status chips, progress bars with percent labels, pass-rate column,
relative "Updated", per-row ⋯ menu, pagination footer), and at ≥1280px a sticky
21rem inspector rail of stacked cards for the selected row (auto-selected to the
newest run). While the rail is open the ledger drops columns the rail already
carries; closing it (Esc or ✕) restores the full ledger. Below 1280px rows
navigate directly and the rail disappears — no overlay drawer.

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
- **Status dot chip** (`RunStatusChip`): colored dot + word, no pill background —
  the reference chip. The word carries meaning; color is never alone.
- **KPI stat card**: tinted round icon chip + muted label, ink-colored number,
  muted sub-line. Numbers wear text tokens, never status colors.
- **Inspector rail** (`features/run-inspector/RunRail.tsx`): stacked cards for the
  selected run — summary (title, dot chip, 2×2 metrics grid), Configuration facts,
  Tasks activity list (colored outcome icons), Quick actions (icon + chevron rows).
  Shows only facts read from the run's artifacts; null facts are omitted, never
  padded. Shares the `["run", id]` query key so opening the detail page lands warm.

## Motion

150ms (hover/expand) to 200ms (drawer/route) with `cubic-bezier(0.16, 1, 0.3, 1)`.
Motion only for state: expanding evidence, tab underline, running-pulse dot, skeleton
shimmer, toast entry. No page-load choreography. All of it collapses to instant under
`prefers-reduced-motion: reduce`.

## Where facts live / 事实源速查表

Every fact below has **one** home. To change it you open exactly the file in the
right column — the derived copies (GUI agent tables, launcher/CLI choices,
default docker-image map, generated TS types) follow automatically. If you find
yourself editing a second place to keep something "in sync", that is a bug in the
architecture, not a step to remember. The `recipes.md` steps map one-to-one onto
these rows.

| 要改 X (the fact) | 去这个文件 (the single source) | 谁自动跟随 (derived, do not touch) |
|---|---|---|
| **Runtime metadata** — label, protocol, bin, credential env keys, docker env whitelist, judge-sensitive env | Built-in: `RuntimeInfo` in `src/starbench/adapters/<id>.py`; register in `adapters/registry.py`. Custom: `runtimes/<id>.json` | `gui/agents.py`, `gui/library.py` (`AGENT_BINS`/`AGENT_ENV_KEYS`), `gui/experiments.py` (`JUDGE_ENV_SENSITIVE`), `gui/launcher.py` (`AGENT_CHOICES`), `runner/cli.py` — all derive from `list_builtin()` |
| **Injection channel** — how a provider's endpoint/key wires into a runtime | The `injection=InjectionChannel(...)` on that runtime's `RuntimeInfo` (`adapters/<id>.py`). A *new channel kind* is added in `gui/injection.py` | frontend `NewRun.tsx` (no longer holds `providerSettings()`) |
| **Docker image (default per runtime)** | `RuntimeInfo.docker_image` in `adapters/<id>.py` | `adapters/registry.py` `DEFAULT_DOCKER_IMAGES`, `gui/experiments.py` `DOCKER_CAPABLE_AGENTS` |
| **Docker image (the build itself)** | `docker/<id>.Dockerfile` + its `Makefile` `docker-images*` line | — |
| **Output parser** — how stdout becomes `final.md` + comparable events | `src/starbench/execution/parsers.py`; the owning adapter's finalize step points at the helper | every runtime that shares that output format |
| **API shape** — an `/api` request/response field | `src/starbench/gui/contracts.py`, then `make gen-types` | `gui-frontend/src/lib/api-types.ts` (generated, committed), `lib/api.ts` |
| **Provider preset** — endpoint + credential env name + model catalog | `BUILTIN_PROVIDERS` in `src/starbench/gui/providers.py` | `key_present` / catalog snapshot (computed at read time) |
| **Evaluator (judge) prompt** | `build_single_judge_prompt` / `build_parallel_judge_prompt` in `src/starbench/runner/prompts.py` | every runtime's judge (the prompt text is runtime-independent) |
| **Task package format** — task.json / rubrics / references | Loader: `src/starbench/runner/task_loader.py`. Authoring contract: [`docs/task_package.md`](task_package.md) | GUI import/preflight in `gui/library.py` |
| **Run artifact layout** — a task root's `workspace/` / `logs/` / `judges/` paths | `materialize_task` in `src/starbench/runner/executor.py` (the only writer) | `gui/data.py` readers, `runner/judge.py` (mirrors names when staging the judge workspace) |
