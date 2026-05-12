# Task: Build `stellar_measure`

Create a pure Python standard-library CLI package under:

```text
./outputs/stellar_measure/
```

The package must run with:

```bash
python -m stellar_measure --segments 12.5,34.75,74.85 --label orion-demo --json
```

For that sample command, stdout must be valid JSON with:

```json
{
  "total_meters": 122.1,
  "total_feet": 400.591,
  "segment_count": 3,
  "longest_segment_meters": 74.85,
  "label": "orion-demo"
}
```

Use the conversion `1 meter = 3.28084 feet`, rounded to 3 decimal places for `total_feet`.

Implementation requirements:

- Use only Python standard-library modules.
- Include `stellar_measure/__main__.py` so `python -m stellar_measure` works.
- Define callable functions named `parse_segments` and `summarize_segments`.
- Reject non-numeric segment values with a non-zero exit and an error mentioning `invalid` or `number`.
- Reject negative segment values with a non-zero exit.
- Include a README that contains the exact sample segment string `12.5,34.75,74.85`.
- Include tests with at least four `def test_...` functions.
- Run the sample command once before finishing so the execution trace captures the command and output.

When finished, briefly report the created path and the sample verification result.

