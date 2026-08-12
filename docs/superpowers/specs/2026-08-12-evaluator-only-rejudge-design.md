# Evaluator-Only Rejudge Design

## Purpose

Add a first-class `starbench-evaluate` command that judges outputs from an
existing StarBench run against a task package's current rubrics without
starting an executor or modifying the source run.

The command creates a new rejudge run. A rejudge is a new measurement of an
existing executor sample, not a new executor sample and not a mutation of the
historical run that produced the outputs.

## Scope

This change includes:

- a standalone `starbench-evaluate` CLI;
- evaluator-only orchestration for one or more completed task runs;
- single, parallel, and both judge modes through the existing adapters;
- immutable source-output verification;
- rejudge configuration, per-task summaries, and a root summary;
- deterministic fake-CLI tests and operator documentation.

This change does not include:

- a GUI flow;
- resuming or repairing incomplete executor runs;
- replacing or versioning judges inside the source run;
- a force-overwrite option;
- executor flags, executor skill selection, instruction injection, or rigor
  injection;
- treating evaluator failure as an executor failure.

## Command Interface

The new console script is registered as `starbench-evaluate` and accepts:

```text
starbench-evaluate
  --source-run-root PATH
  --tasks-dir PATH
  [--task ID_OR_DIR ...]
  [--runs-dir PATH]
  [--run-id SAFE_ID]
  [--judge-mode single|parallel|both]
  [--max-evaluator-parallel N]
  [--seed INT]
  [--evaluator-agent AGENT]
  [--evaluator-model MODEL]
  [--evaluator-auth-mode env|global|copy-auth]
  [--evaluator-bin COMMAND]
  [--evaluator-option NAME=VALUE ...]
  [runtime shared-bin flags]
  [--runtimes-dir PATH]
  [--evaluator-timeout-seconds N]
  [--no-progress]
```

`--source-run-root` identifies a completed `starbench-run` root containing
`run_config.json` and task-run subdirectories. `--tasks-dir` selects the task
package library whose current rubrics are authoritative for the rejudge.
Repeated `--task` filters the source task IDs to rejudge and uses the existing
task discovery convention. All source samples whose manifest `task_id` matches
a selected task are included, including repeated runs such as `task__002`.

`--runs-dir` follows the standard precedence: explicit flag,
`$STARBENCH_HOME/runs`, then `~/.starbench/runs`. If `--run-id` is omitted, the
CLI derives a safe timestamped ID from the source run ID. The target root must
not already exist. There is deliberately no `--force` option.

The CLI exposes only evaluator-side runtime settings. It must never accept an
executor model, executor backend, executor auth mode, executor skill,
instruction, or rigor flag.

Defaults match `starbench-run` where they have the same meaning:

- evaluator agent: `codex`;
- evaluator auth mode: `env`;
- judge mode: `single`;
- maximum evaluator parallelism: `4`;
- evaluator timeout: `900` seconds;
- seed: `123`.

## Architecture

### Entry Point

`src/starbench/runner/evaluate_cli.py` owns argument parsing and startup
validation for the standalone command. It resolves the evaluator adapter and
runtime options through the adapter registry, builds a `JudgeContext`, and
calls the evaluator-only orchestrator.

It must not import the GUI and must not route through `run_benchmark`, because
that orchestration path always owns executor materialization and execution.

### Rejudge Orchestrator

`src/starbench/runner/rejudge.py` owns source-run discovery, preflight
validation, immutable-output evidence, evaluator scheduling, and rejudge
summaries. It reuses:

- `task_loader.load_task` / `discover_tasks` for authoritative task packages;
- the adapter registry and `JudgeContext` for runtime behavior;
- `judge.run_single_judge` and `judge.run_parallel_judges` for evaluator
  workspaces, prompts, schemas, process execution, and aggregation;
- existing environment scoping so executor-only injected credentials cannot
  reach the judge;
- existing progress event conventions where applicable.

No runtime-specific command construction belongs in `rejudge.py`.

### Judge Workspace Source

The existing `prepare_evaluator_workspace` function currently assumes its
`task_root`, `workspace`, and `judges` paths belong to one run. Rejudge keeps
the source task root and workspace read-only while directing all judge output
to the new rejudge task root. The path dictionary therefore has deliberately
split ownership:

- `task_root`: source task-run directory, read-only evidence;
- `workspace`: source executor workspace, read-only deliverables;
- `judges`: new rejudge task's judge output directory;
- `agent_home`: new rejudge task's evaluator auth/config directory.

`prepare_evaluator_workspace` copies source evidence and deliverables into the
new judge workspace before starting the evaluator. The evaluator receives a
read-only sandbox exactly as it does in a normal run.

## Preflight and Source Selection

All preflight checks occur before the target run root is created. The command
fails if:

- the source run root is missing or is not a directory;
- `run_config.json` is missing or invalid JSON;
- no selected task package exists;
- a selected task ID has no matching source task run;
- a source task-run manifest is missing or its `task_id` does not match the
  selected task package;
- the source executor status is missing or not `success`;
- the source executor timed out;
- `workspace/outputs/` is absent or contains no deliverable files;
- any source path needed for evaluation escapes the source run root or is a
  symlink where the existing task/run path rules prohibit one;
- the destination run ID is unsafe;
- the destination run root already exists;
- evaluator runtime configuration is invalid.

Preflight returns an ordered list of source samples. Ordering follows the
source `run_config.json` `task_order` when available; any compatible legacy
sample absent from that list follows in lexical order. This preserves repeated
run ordering without deriving semantics from `__002` suffixes.

The first implementation requires completed modern source artifacts rather
than guessing missing provenance from legacy directory shapes.

## Immutability Evidence

Before any evaluator starts, the orchestrator records SHA-256 for every regular
file under each selected source `workspace/outputs/`. Hash keys use normalized
paths relative to `workspace/outputs/`.

After all evaluators finish, the orchestrator hashes the source outputs again.
If any file was added, removed, or changed, the affected rejudge task becomes
`inconclusive_judge`, the root summary records an integrity error, and the CLI
exits non-zero. The command never attempts to restore or alter the source.

The hash snapshot is stored in both the root rejudge configuration and the
corresponding task summary. This proves which exact deliverables were judged
without duplicating them as authoritative executor artifacts.

## Artifact Layout

The new run root is independent from the source run:

```text
runs/<rejudge-id>/
  rejudge_config.json
  rejudge_summary.json
  rubrics/
    <task-id>.json
  <run-task-id>/
    rejudge_manifest.json
    task_summary.json
    agent_home/
    judges/
      single_*.json
      single_workspace/
      parallel/
      parallel_*_workspace/
```

`rejudge_config.json` records:

- schema version and `mode: "evaluator_only_rejudge"`;
- source run root and source run ID;
- selected task IDs and ordered source run-task IDs;
- task-package paths and rubric SHA-256 values;
- source-output SHA-256 maps;
- evaluator runtime, model, auth mode, options, timeout, judge mode,
  parallelism, and seed;
- runtime provenance;
- `executor_rerun: false`.

Each `rejudge_manifest.json` binds one source sample to one task package and
its rubric hash. Each `task_summary.json` contains source executor timing as
historical context, source hashes, judge results, and an explicit
`executor_rerun: false`. It does not copy the source executor status into a
field that could be mistaken for an executor invocation owned by the rejudge.

`rejudge_summary.json` contains the ordered task summaries or compact
references to them plus aggregate completion counts. It is written only after
all scheduled evaluators settle.

These evaluator-only artifacts are initially command-owned operational
artifacts. They must not masquerade as an existing `starbench-run` artifact
contract. If the console later consumes them, their schemas must first be
added to the public contract tree and versioned according to
`docs/ARCHITECTURE.md`.

## Evaluation Semantics

The task package supplied to `starbench-evaluate` is authoritative for rubric
IDs, questions, `expected`, and `fail_fast`. The source task package is not
modified and its historical rubrics are not reused unless the operator points
to them explicitly.

Rubric failures produce a valid measurement with `outcome: "agent_fail"` and
do not make the CLI fail. Judge process failure, timeout, missing structured
answers, or source-integrity failure produces `inconclusive_judge` for the
affected sample. Independent samples continue to completion.

The process exit code is:

- `0` when preflight succeeds, every requested judge invocation reaches a
  conclusive aggregate, and source integrity remains intact, regardless of
  agent pass/fail verdicts;
- non-zero for preflight errors, any inconclusive judge result, integrity
  errors, or failure to write the complete rejudge summary.

Single and parallel judge modes retain their existing aggregation behavior.
`both` executes both modes and records each independently.

## Concurrency

`--max-evaluator-parallel` is one shared semaphore across every selected
sample and, in parallel mode, every rubric invocation. It limits evaluator
processes rather than task coroutines. No executor batch size exists in this
command.

The seed only controls deterministic parallel-rubric launch ordering. It does
not imply deterministic model output.

## Authentication and Runtime Rules

The evaluator adapter remains the single source of truth for CLI invocation,
auth homes, provider options, schema transport, and model handling.

Role-scoped environment handling uses the existing judge environment. Values
from `STARBENCH_EXECUTOR_ENV_*` are never exposed to the evaluator. Existing
runtime restrictions continue to apply, including Pi's env-only auth rule.

No API token or copied auth content is written to rejudge configuration or
summary artifacts.

## Failure Cleanup

Preflight failure leaves no destination directory.

Once the destination root is created, runtime failures are preserved as
evidence rather than deleting the run. The root summary records whether the
rejudge completed conclusively. A rerun requires a new run ID; operators never
reuse or overwrite an incomplete rejudge root.

## Testing Strategy

Tests use deterministic fake evaluator CLIs and real filesystem artifacts.
They cover:

1. The CLI launches only evaluator commands and never calls an executor.
2. New rubric questions and IDs reach the evaluator prompt.
3. Repeated source samples retain source `task_order`.
4. Task filtering includes all repeats for a selected task ID.
5. Single, parallel, and both modes write the expected judge artifacts.
6. One shared semaphore enforces `--max-evaluator-parallel` across samples and
   rubric invocations.
7. Source output hashes and mtimes remain unchanged after successful rejudge.
8. Source file mutation during judging yields an integrity error and non-zero
   exit.
9. Existing destination, task mismatch, unsuccessful executor, timed-out
   executor, and missing outputs fail before any evaluator starts.
10. Judge failure, timeout, malformed JSON, and missing rubric results become
    `inconclusive_judge` while independent samples continue.
11. Rubric failure produces `agent_fail` with exit code zero when all judge
    invocations are otherwise conclusive.
12. Runtime option and auth validation matches the adapter registry.
13. Rejudge configuration and summaries contain provenance and hashes but no
    credential values.

The full Python test suite, schema synchronization check, generated-type check,
and `git diff --check` must pass before completion.

## Documentation

`docs/runner_reference.md` gains a dedicated evaluator-only section with CLI
examples, exit-code semantics, and the distinction between source runs and
rejudge runs. `README.md` receives a short discoverability example if its
current command overview has an appropriate entry point.

Because this change adds evaluator-only measurement semantics, the eventual
commit message and handoff must explicitly state that it creates new rubric
measurements over immutable historical executor samples and does not alter the
samples themselves.
