# Seiba Sensitive Data Scanner

**Scan sensitive data, understand how it is exposed, choose a safer transformation, and measure what remains useful.**

Seiba is a Python SDK for finding PII, PHI, and financial data in text and tabular datasets. It turns findings into an explainable readiness report: what was found, where it appears, how exposed the dataset is, what action is recommended, and what privacy and utility remain after a scrub.

> **Important:** Seiba identifies candidate sensitive values. It is not legal advice, a certified de-identification solution, or a guarantee of HIPAA, GDPR, CCPA, PCI, or other regulatory compliance. Validate results for your data and use case.

## What you can do

- Scan documents and tables for **84 PII, PHI, and financial entity types**.
- Find sensitive values in `.txt`, `.md`, `.csv`, and JSON records, or pass strings and pandas DataFrames directly from Python.
- Prioritize a dataset with severity, an exposure index, a review queue, and optional record-level re-identification analysis.
- Generate a policy plan that can mask, redact, hash, replace, preserve format, or generalize values such as dates and ZIP codes.
- Use the optimizer to select the least destructive set of actions that meets a privacy target.
- Write a plain-language Markdown report and a complete JSON report together.

Seiba is built on [OpenMed](https://github.com/maziyarpanahi/openmed) for local NER and de-identification primitives, and extends it with structured-data scanning, ontology-driven assessment, policy planning, and privacy-versus-utility measurement.

## Quickstart

Scan one or more supported files and write a report:

```python
from seiba_risk_scanner.assessment import report_from_paths

report = report_from_paths(
    ["clinical_notes/", "patients.csv"],
    out_dir="reports",
    health_context=True,
)

print(report.exposure_index)
print(report.severity_histogram)
print(len(report.review_queue))
```

This writes `reports/readiness_report.md` for people and `reports/readiness_report.json` for systems. See a checked-in [sample Markdown report](demo_scripts/local_runs/readiness_report_unstructured_20260726_005916.md) and its matching [JSON output](demo_scripts/local_runs/readiness_report_unstructured_20260726_005916.json).

For a direct text scan:

```python
from seiba_risk_scanner import SeibaScanner

scanner = SeibaScanner()
result = scanner.classify_text(
    "Contact Emily Davis at emily@example.com. MRN: BH-MRN-789456."
)

for finding in result.detections:
    print(finding.entity, finding.text, round(finding.confidence, 2))
```

For structured data, column names contribute evidence and each finding retains its row and column location:

```python
rows = [
    {"name": "Emily Davis", "city": "Austin", "mrn": "BH-MRN-789456"},
]
result = scanner.classify_structured_text(rows)
```

## Inputs and outputs

| You provide | Seiba does |
|---|---|
| `.txt` or `.md` files | Scans each file as one document record. |
| `.csv` or JSON records | Scans each cell and keeps row/column provenance. |
| Folders | Recursively finds supported files. |
| Python strings, dictionaries, lists of dictionaries, or pandas DataFrames | Scans in-memory data without creating files. |

It currently does **not** ingest PDFs, Word files, Excel workbooks, images, OCR output, or databases directly.

Each report includes the findings, their locations, severity and reason, data-type and record rollups, a risk heatmap, HIPAA Safe Harbor checklist, regulation-scope summary, human-review queue, policy plan, residual-risk measurement, and retained-utility measurement when a policy is executed.

Read the [inputs and outputs guide](docs/inputs-and-outputs.md) for exact supported shapes and the [sample report](demo_scripts/local_runs/readiness_report_unstructured_20260726_005916.md) for the rendered result.

## Core capabilities

### Detection with evidence

Seiba combines format-aware detection, validation rules, a medical-term dictionary, contextual evidence, and a pluggable NER backend. Every finding records the matched text and location, entity type, final confidence, confidence from each contributing detector, the winning method, contextual evidence, and any relabeling applied during resolution.

### Dataset risk assessment

Seiba turns a list of matches into a dataset-level picture:

- **Severity and exposure:** identifies which kinds of data need attention first.
- **Risky locations and records:** shows which documents, columns, or rows concentrate sensitive data.
- **Review queue:** highlights material findings that need a person to confirm.
- **Re-identification analysis:** when there is a sufficient population, measures whether combinations of traits—such as age, ZIP code, and diagnosis—make records stand out. For example, `k=5` means each record shares those traits with at least four others.
- **Compliance-oriented inventories:** reports the relevant HIPAA Safe Harbor categories and data that may be in scope for GDPR, CCPA, HIPAA, or PCI, subject to your jurisdiction and use case.

### De-identification and utility

Choose a policy profile, override actions for specific entities, and optionally execute the plan. Available actions include `keep`, `mask`, `redact`, `hash`, `replace`, `format_preserve`, and `generalize`.

Generalization preserves useful detail where possible: for example, a date can become a year and a ZIP code can become a broader region. The optional optimizer compares privacy reduction against information retained and chooses the least destructive actions that satisfy `Privacy.MAXIMUM`, `Privacy.BALANCED`, or `Privacy.REQUIRED`.

### Reporting and auditability

Every report is written in Markdown and JSON. Findings include rule traces and detector provenance; planned actions explain why they were selected; executed policies can be measured for residual exposure and retained analytical value.

## Installation

Requires **Python 3.12+**.

Install from source:

```bash
git clone https://github.com/seiba-ai/seiba-risk-scanner.git
cd seiba-risk-scanner
pip install -e .
```

The default local model dependency is installed with the package. Its model files may download on first model-backed use and are then cached locally; scanning inference itself runs locally.

Optional extras:

| Extra | Install | Adds |
|---|---|---|
| `ner-spacy` | `pip install -e ".[ner-spacy]"` | spaCy backend. |
| `ner-hf` | `pip install -e ".[ner-hf]"` | Bring-your-own Hugging Face token-classification models. |
| `llm` | `pip install -e ".[llm]"` | Optional LLM refinement stage. |
| `dev` | `pip install -e ".[dev]"` | Test, lint, and type-check tooling. |

## Evaluate and extend

The repository includes a reproducible evaluation harness, annotated synthetic fixtures, regression baselines, standalone model predictions, and full Seiba pipeline runs. The current default-pipeline result on its 18-document synthetic unstructured corpus is **82.6% micro F1** with 90.1% recall; its structured fixtures score **100% micro F1**. These are small, synthetic test sets—not a claim about performance on every corpus.

Seiba’s value is broader than a detector score: it preserves detection evidence, supports tables as well as prose, and carries findings through risk assessment, policy selection, and post-scrub measurement. The project records model-only and full-pipeline runs so those layers remain inspectable rather than implicit.

See the [evaluation guide](docs/evaluation.md) for the corpus, matcher, limitations, artifacts, and commands. See [architecture](docs/architecture.md) for the pipeline and [configuration](docs/configuration.md) for ontology and policy customization.

## Documentation

- [Documentation index](docs/README.md) — links to every guide.
- [Inputs and outputs](docs/inputs-and-outputs.md) — supported formats, in-memory data shapes, and result objects.
- [Configuration](docs/configuration.md) — ontologies, detector backends, actions, and runtime overrides.
- [Architecture](docs/architecture.md) — how detection, assessment, policy, and measurement connect.
- [Evaluation](docs/evaluation.md) — reproducible metrics, test sets, artifacts, and known limits.
- [Entity taxonomy](docs/entities.md) — all bundled entities and their detection and policy metadata.

## Limitations

- Detection quality varies by entity and corpus. Dates, ages, timestamps, and unfamiliar identifier formats can produce false positives or misses.
- English is the only supported and evaluated language. Name quality across populations is not yet fully evaluated.
- A zero count means no candidate was found; it is not proof that a data category is absent.
- `health_context=True` is needed when identifiers appear in health data; the scanner cannot infer that context reliably from the values alone.
- Re-identification analysis requires a real population (default: at least 10 records); otherwise it is reported as not measured.
- Regulatory tags indicate potential scope, not which laws apply to you.
- No packaged CLI exists in v0.1; this is currently a Python SDK.

Read the [full limitations and security notes](SECURITY.md) before relying on Seiba for a sensitive-data workflow.

## Development

```bash
pip install -e ".[dev]"
pytest -m "not slow"
pytest -m slow
```

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md), and never commit real PII or PHI in fixtures, issues, or pull requests.

## License

Copyright © 2026 Seiba AI. Licensed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for third-party vocabulary attributions.
