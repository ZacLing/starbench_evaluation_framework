# Product

> Design context for the StarBench Console (local GUI). Maintained by impeccable.

## Register

product

## Users

Benchmark operators: engineers who evaluate coding-agent CLIs with StarBench. They work
on a laptop next to a terminal, usually mid-investigation ("did the run pass?", "which
rubric failed?", "what did the executor actually do?"). Runs take minutes to hours, so
they return to the console repeatedly while something is cooking. They are fluent in
JSON and could read `runs/` by hand; the console exists because they should not have to.

## Product Purpose

A local, read-mostly console over the StarBench `runs/` directory plus a launcher for
new evaluation runs. Success: an operator answers "how did this run go, which rubric
failed, and why" in seconds, and can start a correctly-formed run without remembering
thirty CLI flags. The file system stays the single source of truth; the console never
writes its own database.

## Brand Personality

Precise, calm, legible. A lab instrument, not a marketing dashboard. It should feel
like the trustworthy front panel of a machine that is doing serious measurement work.

## Visual Reference

The console follows the light SaaS-dashboard language of the HSW Eval reference
(operator decision, 2026-07): light-gray canvas under white cards, KPI stat strip,
dot-plus-word status chips, progress bars, and a selected-item inspector panel.
Every figure must still come from `runs/` on disk.

## Anti-references

- Invented dashboard metrics: cost, owners, or trend deltas with no source on disk.
- Gradient decoration; charts that exist for looks rather than a question.
- Grafana-style neon-on-dark observability walls.
- Terminal cosplay: fake scanlines, phosphor green, TUI-in-browser aesthetics.
- Anything that hides the underlying files or invents state not present on disk.

## Design Principles

1. **Verdict first.** Pass/fail/timeout is readable before any prose: glyph + color,
   never color alone. The eye lands on the verdict, then the detail.
2. **Evidence one gesture away.** Every rubric score expands to the judge's evidence;
   every task run links to its trace, final message, and artifacts.
3. **The file system is the truth.** The GUI renders `runs/` as it exists on disk.
   Missing files render as honest absence, not as errors invented by the UI.
4. **Density without noise.** Operators want tables: monospace ids, timings, counts.
   Density is served by alignment and hierarchy, not by shrinking text.
5. **Motion conveys state only.** Progress, loading, and state change may move.
   Nothing else does.

## Accessibility & Inclusion

WCAG 2.1 AA. Verdicts are encoded with glyph + text + color (color-blind safe).
Full keyboard paths for tables, expanders, and the launch form. `prefers-reduced-motion`
respected everywhere. Body text contrast >= 4.5:1, data text >= 4.5:1 including muted
labels.
