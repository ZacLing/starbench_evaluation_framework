# StarBench Artifact Contracts 草案

> Draft v1. 本文描述 StarBench task packages 与 run artifacts 的公开制品契约。
> 当前版本是非强制草案，用来固定语义、字段边界和后续 schema/test 落点；
> 它不表示所有历史 artifact 都已经携带 `schema_version`。

## 1. Scope

StarBench 的 artifact contract 覆盖两类文件级接口：

- 输入制品：任务作者、平台或 GUI 提供给 `starbench-run` 的 task package。
- 输出制品：`starbench-run` 写入 `runs/<run_id>/` 的结果目录。

不在本契约范围内：

- 具体 runtime CLI 的私有事件格式；
- 本地 GUI 状态；
- API key 或 credential value；
- 临时 scratch 文件；
- 未声明为 public 的调试日志。

## 2. Stability classes

StarBench artifacts 分为四类。

| Class | Meaning | Compatibility expectation |
| --- | --- | --- |
| Public | 平台、GUI、CI、外部脚本可稳定消费 | 需要版本策略；删除/改义为 breaking |
| Private | 可以存在于输入中，但不得公开输出 | 必须有隐私测试守护 |
| Diagnostic | 可帮助 debug，但不保证长期稳定 | reader 应宽松处理 |
| Internal | 实现细节，不应被外部消费者依赖 | 不写入公开 contract |

## 3. Versioning policy

Public artifacts should carry `schema_version` once enforcement begins.

Current draft rule:

- Missing `schema_version` means legacy v0.
- `schema_version: 1` is the first public contract target.
- Adding optional fields is compatible.
- Removing stable fields, renaming stable fields, or changing field meaning is breaking.
- Consumers should ignore unknown fields unless a schema explicitly forbids them.
- Unknown future versions should produce a clear warning or fail-fast depending on the consumer role.

This first draft keeps `schema_version` optional in JSON Schema so current examples
and existing run outputs remain valid while the contract is being introduced.

## 4. Task package contract

A task package is a directory with at least:

- `task.json`
- `prompt.md`
- `rubrics.json`

Optional files include:

- `human_reference.json`
- `rigors.json`
- `executor_skills.json`
- materials listed explicitly in `task.json`
- other non-hidden top-level files/directories copied as materials when `materials` is omitted

### 4.1 `task.json`

Public fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable task id. Use letters, digits, dot, dash, underscore. |
| `name` | no | Human-readable task name. Defaults to `id`. |
| `prompt` | no | Prompt file path. Defaults to `prompt.md`. |
| `rubrics` | no | Rubric file path. Defaults to `rubrics.json`. |
| `human_reference` | no | Expert step file path. Defaults to `human_reference.json` when present. |
| `rigors` | no | Rigor requirement file path. Defaults to `rigors.json` when present. |
| `executor_skills` | no | Task-local executor-skill declaration file. |
| `timeout_seconds` | no | Executor timeout. Defaults to 1800. |
| `allow_web_search` | no | Whether the task permits web search. Defaults false. |
| `materials` | no | Explicit files/directories copied into executor inputs. |
| `input_materials` | legacy | Legacy alias for `materials`. |
| `files_dir` | no | Conventional material directory. Defaults to `files` when present. |

Contract note: boolean fields should be JSON booleans. String truthiness should
not be treated as a public protocol feature even if legacy code accepted it.

Schema: `schemas/starbench/v1/task.schema.json`.

### 4.2 `rubrics.json`

`rubrics.json` contains a `rubrics` array. Each rubric has:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable rubric id within the task. |
| `question` | yes | Evaluator-facing yes/no criterion. |
| `expected` | yes | Expected boolean answer for pass. |
| `fail_fast` | yes | Whether failure invalidates the task. |

Schema: `schemas/starbench/v1/rubrics.schema.json`.

### 4.3 `human_reference.json`

`human_reference.json` contains expert process steps used by instruction sweeps.

Each step has:

| Field | Required | Class | Meaning |
| --- | --- | --- | --- |
| `step_id` | yes | Public | Stable step id. |
| `step_type` | yes | Public | Category of expert step. |
| `instruction` | yes | Public | Executor-facing expert instruction when selected. |
| `reasoning` | yes | Private | Expert private reasoning. Never expose through GUI API, executor prompt, or public artifacts. |

Schema: `schemas/starbench/v1/human_reference.schema.json`.

### 4.4 `rigors.json`

`rigors.json` contains rubric-level requirements that can be restated in the
executor prompt for controlled experiments.

Each rigor has:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable rigor id. |
| `rubric_id` | no | Rubric id this requirement supports. Defaults to `id`. |
| `requirement` | yes | Executor-facing requirement text. |

Schema: `schemas/starbench/v1/rigors.schema.json`.

### 4.5 `executor_skills.json`

`executor_skills.json` declares task-local executor skills.

Each skill has:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable skill id. |
| `path` | no | Directory path, defaults to `skills/<id>`. |
| `activation` | no | Executor-facing activation text. |
| `description` | no | Human-readable description. |
| `leakage_level` | no | Optional leakage classification. |
| `sha256` | no | Optional directory integrity hash. |

Schema: `schemas/starbench/v1/executor_skills.schema.json`.

## 5. Run artifact contract

The stable run layout starts at:

```text
runs/<run_id>/
  summary.json
  progress_events.jsonl
  <task_run_id>/
    manifest.json
    task_summary.json
    logs/
      status.json
      trace_summary.json
      artifact_manifest.json
      events.jsonl
      final.md
    judges/
      ...
    workspace/
      outputs/
```

### 5.1 `summary.json`

`summary.json` is the whole-run public summary.

Stable fields include run configuration (`run_id`, agents, models, backend,
judge mode, seed, selected research knobs) and `batches`.

Runs created after runtime provenance capture landed also carry an optional
`runtime_provenance` object (executor/evaluator environment snapshot for
reproducibility). Its full contract is
`schemas/starbench/v1/runtime_provenance.schema.json`; older runs simply omit
the field.

Schema: `schemas/starbench/v1/run_summary.schema.json`.

### 5.2 `progress_events.jsonl`

`progress_events.jsonl` is an append-only progress stream. Each line is a JSON
object with an `event` string and event-specific fields. It is public for live
readers, but readers should be forward-compatible with unknown event types.

Schema: `schemas/starbench/v1/progress_event.schema.json`.

### 5.3 `manifest.json`

`manifest.json` records what the executor task run saw and which research
variants were selected.

Schema: `schemas/starbench/v1/task_manifest.schema.json`.

### 5.4 `task_summary.json`

`task_summary.json` is the public summary for one task run. It links executor
status and judge results.

Schema: `schemas/starbench/v1/task_summary.schema.json`.

### 5.5 `logs/status.json`

`logs/status.json` is the executor process status and artifact pointers.
Newer runs add an optional `executor_runtime_provenance` object whose shape
matches the `executor` snapshot in
`schemas/starbench/v1/runtime_provenance.schema.json`.

Schema: `schemas/starbench/v1/executor_status.schema.json`.

### 5.6 `logs/trace_summary.json`

`logs/trace_summary.json` is a normalized trace summary across runtimes. It is
useful for GUI and reports, but raw event details remain diagnostic.

Schema: `schemas/starbench/v1/trace_summary.schema.json`.

### 5.7 `logs/artifact_manifest.json`

`logs/artifact_manifest.json` inventories files produced under
`workspace/outputs/`.

Schema: `schemas/starbench/v1/artifact_manifest.schema.json`.

### 5.8 Judge artifacts

Judge aggregate files summarize rubric verdicts. Their current structure is
captured by:

- `schemas/starbench/v1/judge_aggregate.schema.json`

The evaluator response schemas under `src/starbench/runner/schemas/` remain
runtime prompt/response schemas, not public artifact schemas.

## 6. Privacy and credential rules

Hard rules:

- `human_reference.reasoning` is private expert data.
- Private expert reasoning must not enter GUI API responses, executor prompts,
  public run artifacts, or report artifacts.
- API key values are never artifacts.
- Credential environment-variable names may appear in configuration artifacts;
  credential values must not.
- Executor and judge environment scopes must stay isolated.
- Local absolute paths should not be treated as stable public fields unless a
  schema or doc marks them diagnostic.

## 7. Reader guidance

Consumers should:

- prefer `schema_version` when present;
- treat missing `schema_version` as legacy v0;
- ignore unknown fields in public artifacts;
- preserve unknown fields when rewriting user-owned config where practical;
- fail clearly on malformed required fields;
- avoid depending on diagnostic artifacts for stable business logic.

## 8. Implementation status

This document is the first public contract draft. The current schemas are
reference schemas and are not yet enforced by the runner or GUI.

Implemented in this branch:

- Contract tests under `tests/contracts/`.
- Bundled example-task validation against task package schemas.
- Fake-runtime runner output validation against public run artifact schemas.
- Shared runner/GUI validation via `starbench.contracts`.
- `schema_version: 1` emitted on stable public run artifacts.
- Contract review checklist linked from `docs/contributing.md`.

Planned next steps:

- Decide when task package inputs should declare `schema_version`.
