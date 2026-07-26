# Task Package Structure

A Starbench task package is one directory with `task.json`, `prompt.md`, `rubrics.json`, and optional input materials. By default, put user task packages under the StarBench home task library, `$STARBENCH_HOME/tasks` (`~/.starbench/tasks`); `--tasks-dir` overrides it.

For the protocol-level contract, schema, and compatibility policy, see
[Artifact Contracts](artifact_contracts.md).

```text
~/.starbench/tasks/
  my_task/
    task.json
    prompt.md
    rubrics.json
    human_reference.json        # optional
    materials/                  # optional
    data.csv                    # optional
    figure.png                  # optional
```

The bundled `examples/tasks/` directory in a repository checkout is for demos and is never auto-loaded into the library. Seed it with `cp -r examples/tasks/* ~/.starbench/tasks/`, or run those examples directly by passing `--tasks-dir examples/tasks`.

At runtime the executor sees a fresh workspace:

```text
workspace/
  inputs/
    prompt.md
    materials/
    data.csv
    figure.png
  outputs/
```

Executors are instructed to read from `./inputs/` and write deliverables under `./outputs/`.

## `task.json`

```json
{
  "id": "demo_python_cli",
  "name": "Demo Python CLI: Stellar Measure",
  "prompt": "prompt.md",
  "rubrics": "rubrics.json",
  "human_reference": "human_reference.json",
  "timeout_seconds": 1800,
  "allow_web_search": false,
  "materials": ["materials", "data.csv"]
}
```

Fields:

- `id`: stable task id used in run output.
- `name`: human-readable display name.
- `prompt`: executor-facing task prompt path.
- `rubrics`: evaluator-facing rubric path. This is never copied into executor inputs.
- `human_reference`: optional expert step file. Only public `instruction` text may be appended to executor prompts when enabled.
- `timeout_seconds`: executor timeout.
- `allow_web_search`: passes web-search permission to Codex when true.
- `materials`: optional explicit list of files or directories to expose under `workspace/inputs/`.

If `materials` is omitted, Starbench copies all top-level task files and directories except `task.json`, `prompt.md`, `rubrics.json`, `human_reference.json`, hidden files, and the configured `files_dir`.

## Prompt Guidelines

A good prompt should specify:

- The exact output path under `./outputs/`.
- Expected file formats.
- Required calculations, citations, tests, or verification commands.
- Constraints such as dependency policy, word count, or source limits.
- A short final-report expectation.

Avoid putting hidden answers, rubric text, evaluator notes, or API credentials in `prompt.md`.

## Materials

Materials can be any files the executor should inspect: CSV, PDF, image, HTML, JSON, notebooks, or source trees. They are copied into `workspace/inputs/` with their relative paths preserved.

Keep evaluator-only references outside `materials` and out of `prompt.md`.
