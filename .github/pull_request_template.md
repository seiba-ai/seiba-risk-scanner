<!--
Never include real PII or PHI — in code, tests, fixtures, or this description.
Use realistic fake data.
-->

## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## Why

<!-- The problem being solved, not just the mechanism. -->

## Checklist

- [ ] `pytest` passes locally (or `pytest -m "not slow"` plus a note on why the eval gates were skipped)
- [ ] `ruff check --select E9,F .` is clean
- [ ] No real PII/PHI in any added file
- [ ] Public behaviour changes are reflected in `Readme.md` and `CHANGELOG.md`

## If this changes detection, scoring, or policy behaviour

Quality is gated against checked-in baselines, so numbers are required — a change that
moves detection without a measurement is not reviewable.

```
python3 -m eval.runner --ner-backend openmed
```

| | before | after |
|---|---|---|
| micro F1 | | |
| affected entities | | |

- [ ] Baseline re-cut (`--update-baseline`) **and** the reason it moved is explained above

<!--
Re-cutting a baseline to make a gate pass hides the regression it exists to catch. If the
numbers went down, say why that is the right trade rather than silently rebaselining.
-->
