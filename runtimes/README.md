# Custom Runtimes

Plug any headless agent CLI into StarBench without writing Python: drop a
`<id>.json` file in this directory and select it with
`--executor-agent custom:<id>` / `--evaluator-agent custom:<id>`.
Use `--runtimes-dir` to point at a different directory.

## Schema

| Field | Required | Default | Meaning |
|---|---|---|---|
| `id` | yes | — | Must match the filename (`<id>.json`). |
| `command` | yes | — | Executable or shell-like prefix (split like `--codex-bin`). |
| `args` | no | `[]` | Extra argv for executor runs. |
| `judge_args` | no | = `args` | Extra argv for judge runs (use your CLI's read-only/plan flags here). |
| `model_flag` | no | `null` | Flag used to pass `--executor-model` / `--evaluator-model` (e.g. `-m`). `null` = model not passed. |
| `prompt_via` | no | `"stdin"` | `"stdin"` writes the prompt to stdin; `"arg"` appends `prompt_flag <prompt>` to argv. |
| `prompt_flag` | no | `"-p"` | Only used when `prompt_via` is `"arg"`. `null` or `""` passes the prompt as a positional argument (e.g. `trae-cli run "<task>"`). |
| `parser` | yes | — | One of `headless-json`, `jsonl-events`, `text` (see below). |
| `env` | no | `{}` | Static environment variables set for executor and judge runs. |
| `docker` | no | — | Enables `--executor-backend docker` for this runtime: `{"image": "...", "env_passthrough": ["VAR", ...]}`. |

Warning: `prompt_via: "arg"` puts the full task prompt on the command line.
Large prompts can exceed the OS argument-size limit (ARG_MAX); prefer
`"stdin"` whenever the CLI supports piped input.

## Console fields

The StarBench Console stores a few extra keys in the same file; the runner
ignores them. `label` (display name), `icon` (brand icon hint), `protocol`
(`openai` / `anthropic` / `gemini` / `none` — which AI providers the console
offers for this runtime), and `base_url_env` / `api_key_env` (the environment
variables this CLI reads for a custom endpoint and its key; the console
injects the selected provider through them at launch).

## Parsers

- `headless-json` — stdout is a single JSON object (the gemini/grok shape).
  The final message is taken from `response`/`result`/`text`-style keys, and
  the object is normalized into Codex-style trace events. Judges extract the
  structured JSON verdict from the response text.
- `jsonl-events` — stdout is already a Codex-compatible JSONL event stream
  (`item.completed` items). Events pass through untouched; the final message
  is the last `agent_message` text.
- `text` — raw stdout is the final message. A synthetic `agent_message`
  event is generated so `trace_summary.json` stays coherent; there is no
  command/file-change trace. Weakest evidence for judges — use only when the
  CLI offers no structured output.

## Judges

Custom judges always receive the rubric JSON schema appended to the prompt
and must answer with a single JSON value; StarBench extracts it from the
parsed final text. Point `judge_args` at your CLI's read-only mode so judges
cannot modify the judge workspace.

## Example

`qwen-code.json.example` in this directory is a starting point for Qwen
Code (a gemini-cli fork). Verify every flag against the installed CLI's
`--help` before use — flags drift between versions — then rename the file
to `qwen-code.json`.
