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

## Scan output

A scan returns a `PipelineStageResult` containing `CombinedDetectionRow` findings. A finding contains:

- the stable `entity_id` and readable `entity` name;
- `text`, `start`, and `end` for its location in the scanned value;
- final `confidence` and contributions from deterministic detection, context, NER, and optional LLM stages;
- `winner_kind`, contextual matches, and rescue/relabeling metadata when relevant;
- source `provenance`, including table row/column location or dictionary metadata.

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
