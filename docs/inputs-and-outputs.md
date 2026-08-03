# Inputs and outputs

Seiba supports document text and row-oriented structured data. It returns Pydantic models, which can be converted to ordinary JSON with `.model_dump(mode="json")`.

## File inputs

`report_from_paths()` and `scan_paths()` accept individual file paths and directories. Directories are searched recursively.

| File type | Interpretation |
|---|---|
| `.txt`, `.md` | One text document per file. |
| `.csv` | One row per record; each cell is scanned and retains its row and column. |
| `.json` | A JSON object is one record; an array of JSON objects is many records. Nested values are not flattened into a relational table. |

Unsupported file types are ignored by the path scanner. In particular, PDF, DOCX, XLSX, images, OCR, and database connections are not supported in v0.1.

```python
from seiba_risk_scanner.assessment import report_from_paths

report = report_from_paths(
    ["notes/", "patients.csv", "claims.json"],
    out_dir="reports",
    health_context=True,
)
```

## Python inputs

| API | Accepted input |
|---|---|
| `scanner.classify_text(text)` | One string. |
| `scanner.classify_texts(texts)` | A list of strings; model-backed NER is batched. |
| `scanner.classify_structured_text(data)` | A pandas DataFrame, a dictionary, or a list of dictionaries. |

For structured data, a column or key such as `mrn`, `city`, or `date_of_birth` is evidence about the value beneath it. Findings retain source provenance such as `row` and `column` (or `key` for a dictionary).

Each API also accepts a source name — `source_id` and `source_label`, or `sources` for the
batch form — which `report_from_paths` fills in from the file path. Naming sources is what
lets one scan cover many files and still scrub each one correctly; leave them unset and a
stable id is derived from the content.

## Scan output

A scan returns a `PipelineStageResult` containing `CombinedDetectionRow` findings. A finding contains:

- the stable `entity_id` and readable `entity` name;
- `text`, `start`, and `end` for its location in the scanned value;
- final `confidence` and contributions from deterministic detection, context, NER, and optional LLM stages;
- `winner_kind`, contextual matches, and rescue/relabeling metadata when relevant;
- `origin`, naming which input the span came from (`source_id`, `source_label`) and which
  cell within it (`row`, `column`);
- detector `provenance`, such as gazetteer codes, column consensus, and the raw input kind.

`origin` answers *where the value is*; `provenance` answers *what the detector saw*. Offsets
only mean something against their own source, so scrubbing reads `origin` to route each
replacement back to the right document.

```python
result = scanner.classify_text("Email emily@example.com")
print(result.model_dump(mode="json"))
```

## Assessment output

`ReadinessAssessor.assess()` and `report_from_paths()` return `SensitiveDataReadinessReport`.

| Report section | What it answers |
|---|---|
| `findings` | What sensitive values were found, how severe they are, and why. |
| `exposure_index` and `exposure_breakdown` | How exposed the dataset is and what drove the number. |
| `per_entity`, `per_record`, and `heatmap` | Which data types and locations need attention. |
| `review_queue` | Which material findings merit human confirmation. |
| `hipaa_checklist` and `compliance_summary` | Which identifier categories and regulatory scopes are present. |
| `reidentification` | Whether records are distinguishable by their quasi-identifying traits, when measured. |
| `policy_plan` | What action is proposed for every finding and why. |
| `residual_severity` and `utility` | What remains exposed and useful after a policy is executed. |

Markdown and JSON files are both written when `out_dir` is supplied. See the [sample Markdown report](../demo_scripts/local_runs/readiness_report_unstructured_20260726_005916.md) and [matching JSON](../demo_scripts/local_runs/readiness_report_unstructured_20260726_005916.json).

## Scrubbed output

`scrub_documents` applies an executed plan back to the inputs it came from, keyed by
`origin.source_id`. Strings are scrubbed by span, tables cell by cell, and a source with no
findings is returned unchanged.

```python
from seiba_risk_scanner.policy import scrub_documents

sources = {"notes/intake.txt": intake_text, "patients.csv": rows}
scrubbed = scrub_documents(report.policy_plan, sources)
```

A record whose span no longer matches its source, or that belongs to a different source, is
an error rather than a skipped replacement — a silently skipped record leaves an identifier
in output that reads as de-identified. `scrub_text` and `scrub_rows` handle one source each.
