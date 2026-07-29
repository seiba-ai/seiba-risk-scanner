# Evaluation

The evaluation harness measures entity detection against checked-in gold annotations. It does not validate legal compliance, de-identification certification, or severity against human judgments.

## Current snapshot

The default Seiba pipeline was evaluated on 18 synthetic English unstructured documents containing 1,140 annotated spans across 46 entity types.

| Matcher | Precision | Recall | F1 |
|---|---:|---:|---:|
| Type overlap (headline) | 0.762 | 0.901 | 0.826 |
| Macro type overlap | 0.805 | 0.889 | 0.821 |
| Exact offsets | 0.727 | 0.859 | 0.787 |

The structured fixtures contain 1,320 cells across three datasets and score 1.000 micro F1. Structured columns provide useful type evidence, so this is a different and easier task than prose detection.

These results are a reproducible development baseline, not a general-performance guarantee. The corpus is synthetic and small; real data can contain different vocabulary, abbreviations, formatting, and population characteristics.

## What the repository records

The repository preserves both standalone OpenMed prediction runs in [`eval/openmed_runs/`](../eval/openmed_runs/) and Seiba pipeline evaluations in [`eval/runs/`](../eval/runs/). Pipeline artifacts include predictions, reports, false positives, false negatives, and contextual rescues. This makes the contribution of Seiba’s added layers inspectable without presenting an unrun head-to-head claim.

Seiba’s extension is evaluated as an end-to-end workflow: it carries detections into structured-data handling, risk assessment, policy planning, and post-scrub measurement. Those capabilities are not summarized by a single detector-comparison percentage.

## Reproduce an evaluation

```bash
python3 -m eval.runner --ner-backend openmed
python3 -m eval.structured_runner
python3 -m eval.compare <run-a> <run-b>
```

The headline matcher requires the correct entity type and any character overlap. Exact-offset results are shown separately because they penalize equivalent but differently bounded spans.

Regression tests reconstruct the baseline configuration and fail on material quality loss. Run the full evaluation gates with:

```bash
pytest -m slow
```

## Known limits

- Severity is explainable and rule-traced, but not yet benchmarked against human severity judgments.
- Precision is weaker than recall for several entities, particularly dates, ages, timestamps, and catch-all identifier formats.
- English is the only evaluated language.
- The reported latency figures are not published here because they need a documented hardware configuration to be comparable.

Inspect per-entity errors and dataset composition in the generated run artifacts before deciding whether Seiba is suitable for your corpus.
