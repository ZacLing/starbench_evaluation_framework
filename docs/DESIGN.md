# Design

> Visual system for the StarBench Console (`starbench-gui`). Maintained by impeccable.
> Register: product. Color strategy: Restrained (white surface, indigo primary, verdict
> colors do the semantic work).
>
> Stack: React + Vite + Tailwind v4 + shadcn/ui (`gui-frontend/`). The tokens below
> are implemented as CSS variables in `gui-frontend/src/index.css` and consumed
> through the shadcn theme (`--primary`, `--muted`, ...) plus custom verdict colors
> (`--pass*`, `--fail*`, `--warn*`, `--live*`). Layout: sidebar app shell (Overview /
> Run matrix / Task library / Runs / Compare, plus a Setup group), summary cards
> before tables, tables for detail. New experiment is a five-step wizard (mode →
> tasks → agents → shared config → review & launch) with provider + model selects,
> inline credential status, and inline readiness checks that block launch.

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
  --background:    oklch(0.977 0.003 280);       /* page canvas (cards stay white) */
  --card:          oklch(1 0 0);                 /* cards, popovers, sidebar */
  --muted:         oklch(0.958 0.005 280);       /* panels, table headers, code blocks */
  --secondary:     oklch(0.958 0.005 280);       /* toolbar wells, secondary buttons */
  --border:        oklch(0.906 0.007 280);
  --input:         oklch(0.845 0.01 280);        /* the strong border (field edges) */

  --foreground:         oklch(0.235 0.018 285);  /* body text, >= 12:1 on background */
  --muted-foreground:   oklch(0.49 0.022 285);   /* secondary text, >= 4.8:1 */

  --primary:            oklch(0.5 0.16 280);     /* actions, links, selection */
  --primary-foreground: oklch(1 0 0);            /* text on solid primary fills */
  --accent:             oklch(0.955 0.025 280);  /* selected-row / hover tint */
  --accent-foreground:  oklch(0.435 0.16 280);   /* ink on that tint, hover */
  --ring:               oklch(0.5 0.16 280);     /* focus */
  --destructive:        oklch(0.545 0.185 27);
  --destructive-foreground: oklch(1 0 0);

  --live:          oklch(0.7 0.115 200);         /* running/info pulse, non-text uses */
  --live-ink:      oklch(0.4 0.09 210);          /* info text on --live-soft */
  --live-soft:     oklch(0.95 0.035 200);

  --pass:          oklch(0.545 0.135 152);       /* non-text marks */
  --pass-ink:      oklch(0.4 0.11 152);          /* chip text, >= 4.5:1 on pass-soft */
  --pass-soft:     oklch(0.955 0.045 152);
  --fail:          oklch(0.545 0.185 27);
  --fail-ink:      oklch(0.42 0.155 27);
  --fail-soft:     oklch(0.95 0.032 27);
  --warn:          oklch(0.6 0.125 80);          /* timeout / interrupted */
  --warn-ink:      oklch(0.425 0.095 80);
  --warn-soft:     oklch(0.955 0.055 90);
}
```

Rules:

- Verdicts are always glyph + word + color (`✓ Pass`, `✕ Fail`, `◷ Timeout`,
  `◌ Inconclusive`), never color alone.
- Chips use soft background + same-hue dark ink (pale fill, dark text). Solid fills
  (`--primary`) always carry `--primary-foreground` white text.
- `--live` marks liveness (running runs, polling) and informational badges only.
  It never competes with verdict colors.
- Focus ring: `--ring` (same value as `--primary`) on every interactive element.
  App code uses `focus-visible:ring-2`, adding `ring-offset-2` where the control
  sits on a tinted surface; untouched shadcn primitives use `ring-[3px] ring-ring/50`.

## Typography

Two families, both local stacks (no webfonts; the console must work offline):

- **UI / prose**: `-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif`
- **Data**: `ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace`
  for run ids, task ids, models, commands, timings, counts, hashes, JSON.

Fixed rem scale (product register). There are no `--t-*` size variables; the scale
is spelled with Tailwind utilities, so the class below *is* the token:

| Class                | Size      | Use |
|----------------------|-----------|-----|
| `text-[0.6875rem]`   | 0.6875rem | uppercase group labels (+0.06–0.08em tracking) |
| `text-xs`            | 0.75rem   | meta labels, table headers |
| `text-[0.8125rem]`   | 0.8125rem | status chips, dense data rows |
| `text-sm`            | 0.875rem  | controls, nav, secondary UI text, panel titles (semibold) |
| `.prose-starbench`   | 0.9375rem | prose panes (evidence, final message, prompts) |
| `text-lg`            | 1.125rem  | section headings within a page |
| `text-xl` / `text-2xl` | 1.25 / 1.5rem | page title (semibold; `2xl` on Overview, Runs, Run matrix) |

Weights: 400 body, 500 labels/controls, 600 titles and emphasis. `tabular-nums` on all
numeric table columns and timers. Prose panes capped at 76ch.

## Spacing, Shape, Elevation

- 4px scale, spelled with Tailwind's own spacing utilities (`gap-1` 4px … `gap-6`
  24px … `gap-12` 48px); there are no `--s*` variables. Tight inside groups (8-12),
  generous between sections (24-48).
- Radii come from one variable, `--radius: 0.5rem`: `rounded-md` 6px for controls
  and chips-with-square-content, `rounded-xl` 12px for cards and panels,
  `rounded-full` for badges and status dots.
- Borders do structure; shadows only for overlays — Tailwind's `shadow-lg` on the
  sheet, `shadow-xs`/`shadow-sm` on inputs and menus. There is no `--shadow-*` variable.
- Z scale is Tailwind's: `z-10`/`z-20` for sticky headers and matrix header cells,
  `z-50` for menus, selects, tooltips, dialogs, and sheets.

## Layout

App shell: collapsible sidebar (primary destinations + Setup group) beside a sticky
top bar (breadcrumbs in mono, "New experiment" primary button) over a content region
capped at 1400px with 16px gutters, 24px from 768px up. Breadcrumbs carry location
within the shallow object hierarchy (runs → run → task run). Tables are the primary
surface: sticky header rows, row hover, generous first column, right-aligned numerics.

The console's navigation principle: the Overview reads progress, the Run matrix
finds differences, the run/task detail pages explain causes. The matrix
(`/coverage`, nav label "Run matrix") is Task × Agent × Model with two-level
headers and a metric switcher — one lens at a time (HSW coverage, Rubric %,
Pass rate, Stability (σ), Duration, Run status), so color never carries two
meanings at once. Clicking a cell opens a "Run group" rail (aggregates + recent
task runs); clicking a column header opens "Combination details". The Overview
(`/`) is a KPI strip (Task pass rate, Completed runs, Running now, Needs
attention, then a compact second tier: Coverage, Run volume, Total runtime, P95
duration), "Progress over time" and "Runs by status" charts, a Performance
heatmap over Agent × Model, tasks by rubric mean (Top 5 / Bottom 5), and at
≥1536px a side rail of "Running now" and "Needs attention" — all computed from
`runs/` plus the task library.

Runs follows the HSW Eval reference layout: page header with freshness controls
("Last updated" + working auto-refresh switch), a KPI stat strip (all figures
computed from disk), a filter row (search + status/runtime selects), the ledger
table (dot status chips, progress bars with percent labels, pass-rate column,
relative "Updated", per-row ⋯ menu, pagination footer), and at ≥1280px a sticky
21rem inspector rail of stacked cards for the selected row (auto-selected to the
newest run). While the rail is open the ledger drops columns the rail already
carries (Tasks, Evaluator, Updated); closing it (✕, or Esc while the selected row
has focus) restores the full ledger. Below 1280px rows navigate directly and the
rail disappears — no overlay drawer.

## Components

- **Verdict chip**: pill, soft bg, glyph + word (+ `n/m` count where relevant).
- **Status chip**: run state (`complete`, `running` with pulse dot, `interrupted`,
  plus a gray fallback that echoes any other status). Executor state (`success`,
  `timeout`, `failed`, pending) is a separate badge.
- **KV grid**: dt/dd pairs for config panels; dt in `text-xs` muted, dd in mono.
- **Expander row**: table rows expand in place for rubric evidence; the chevron
  rotates 90°, and the evidence row mounts rather than sliding.
- **Tabs**: filled-pill style (the shadcn `default` variant) for task-run detail
  panes; the `line` underline variant exists in `ui/tabs.tsx` but is unused.
- **Skeleton**: `animate-pulse` blocks while fetching. Spinners are reserved for
  the New experiment wizard's in-flight checks (preflight, plan build, import).
- **Empty states**: teach the CLI (`starbench-run ...` snippet) or point to New run.
- **Command preview**: the review step renders the argv it will execute behind a
  collapsed `command` disclosure, substituting the literal `starbench-run` for the
  plan's `argv[0..2]`; not yet copyable.
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

Tailwind's default 150ms ease for hover and chevron rotation, `duration-300` for
progress-bar fills, `duration-200`/`duration-500` inside the shadcn sidebar, dialog,
and sheet primitives; no custom easing variable is declared. Motion only for state:
expanding evidence, running-pulse dot, skeleton pulse, progress fill. No page-load
choreography. All of it collapses to instant under `prefers-reduced-motion: reduce`
(`index.css`).

## Where facts live / 事实源速查表

Every fact below has **one** home. To change it you open exactly the file in the
right column — the derived copies (GUI agent tables, launcher/CLI choices,
default docker-image map, generated TS types) follow automatically. If you find
yourself editing a second place to keep something "in sync", that is a bug in the
architecture, not a step to remember. The `recipes.md` steps map one-to-one onto
these rows.

| 要改 X (the fact) | 去这个文件 (the single source) | 谁自动跟随 (derived, do not touch) |
|---|---|---|
| **Runtime metadata** — label, protocol, bin, credential env keys, docker env whitelist, judge-sensitive env | Built-in: `RuntimeInfo` in `src/starbench/adapters/<id>.py`; register in `adapters/registry.py`. Custom: `runtimes/<id>.json` | `gui/agents.py`, `gui/library.py` (`AGENT_BINS`/`AGENT_ENV_KEYS`), `gui/services/planning_inputs.py` (`JUDGE_ENV_SENSITIVE`, re-exported by `gui/experiments.py`), `gui/launcher.py` (`AGENT_CHOICES`), `runner/cli.py` — all derive from `list_builtin()` |
| **Injection channel** — how a provider's endpoint/key wires into a runtime | The `injection=InjectionChannel(...)` on that runtime's `RuntimeInfo` (`adapters/<id>.py`). A *new channel kind* is added in `gui/injection.py` | frontend `NewRun.tsx` (no longer holds `providerSettings()`) |
| **Docker image (default per runtime)** | `RuntimeInfo.docker_image` in `adapters/<id>.py` | `adapters/registry.py` `DEFAULT_DOCKER_IMAGES`, `gui/services/planning_inputs.py` `DOCKER_CAPABLE_AGENTS` |
| **Docker image (the build itself)** | `docker/<id>.Dockerfile` + its `Makefile` `docker-images*` line | — |
| **Output parser** — how stdout becomes `final.md` + comparable events | `src/starbench/execution/parsers.py`; the owning adapter's finalize step points at the helper | every runtime that shares that output format |
| **API shape** — an `/api` request/response field | `src/starbench/gui/contracts.py`, then `make gen-types` | `gui-frontend/src/lib/api-types.ts` (generated, committed), `lib/api.ts` |
| **Provider preset** — endpoint + credential env name + model catalog | `BUILTIN_PROVIDERS` in `src/starbench/gui/providers.py` | `key_present` / catalog snapshot (computed at read time) |
| **Evaluator (judge) prompt** | `build_single_judge_prompt` / `build_parallel_judge_prompt` in `src/starbench/runner/prompts.py` | every runtime's judge (the prompt text is runtime-independent) |
| **Task package format** — task.json / rubrics / references | Loader: `src/starbench/runner/task_loader.py`. Authoring contract: [`docs/task_package.md`](task_package.md) | GUI import/preflight in `gui/library.py` |
| **Run artifact layout** — a task root's `workspace/` / `logs/` / `judges/` paths | `materialize_task` in `src/starbench/runner/executor.py` (the only writer) | `gui/data.py` readers, `runner/judge.py` (mirrors names when staging the judge workspace) |
