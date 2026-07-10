# Authoring Rubrics

Rubrics are yes/no checks. Each check has an expected boolean answer.

```json
{
  "rubrics": [
    {
      "id": "R001",
      "fail_fast": true,
      "expected": true,
      "question": "Does `outputs/result.md` exist?"
    },
    {
      "id": "R002",
      "fail_fast": true,
      "expected": false,
      "question": "Does the submission rely on non-stdlib dependencies?"
    }
  ]
}
```

Evaluator output is considered passing when:

```text
answer == expected
```

The evaluator returns only `rubric_id`, a JSON boolean `answer`, and concrete
`evidence`. The task package remains authoritative for `expected` and
`fail_fast`; StarBench derives `passed` and `overall_pass`. String values such as
`"false"`, numeric booleans, missing results, and evaluator-supplied verdict
fields are invalid Judge output, not task failures.

## Good Rubrics

Good rubrics are concrete and directly inspectable:

- Does `outputs/stellar_measure/stellar_measure/__main__.py` exist?
- Does the sample command output JSON with `total_meters` equal to `122.1`?
- Does the memo mention `Year 1`, `Year 2`, and `Year 3`?
- Does the output cite at least three named input files?

Weak rubrics are vague:

- Is the work thoughtful?
- Did the agent do a good job?
- Is the analysis reasonable?

## Fail-Fast Rubrics

Use `fail_fast: true` for violations that invalidate the task:

- Missing primary deliverable.
- Wrong programming language.
- Forbidden dependency class.
- Non-executable output for a code task.
- Output format not parseable when parseability is central.

Fail-fast rubrics still appear in the score table. They also populate `fail_fast_failures` in aggregate output.

## Executor-Visible Fairness

Rubrics should grade what the executor could reasonably know from `prompt.md` and `workspace/inputs/`. Do not require hidden expert conclusions unless the prompt and materials make the requirement inferable.

Evaluator-only references are useful for designing rubrics, but they should not become impossible hidden-answer checks.
