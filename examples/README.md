# Examples

End-to-end runs of the SDK on realistic, deliberately messy healthcare data: scan it,
assess the risk, and write de-identified copies.

> These examples are **not** the evaluation harness. They demonstrate a workflow and write
> to `outputs/`. For detection metrics scored against annotated gold, see [`eval/`](../eval).

## Run them

From the repository root:

```bash
python -m examples.walkthrough.single      # one document + one table
python -m examples.walkthrough.batch       # every file, plus a risk report
python -m examples.walkthrough.scrub       # de-identified copies
```

Each takes `--max-rows N` to cap rows per table, which is the quickest way to keep a first
run short. The sample outputs checked in here were produced with `--max-rows 20`.

## The data

`data/notes/` — six clinical documents, each carrying a specific trap:

| File | What makes it hard |
|---|---|
| `adv_01_neurology_consult.txt` | Wilson, Crohn, Bell, Parkinson — four surnames used as diagnoses |
| `adv_02_care_team_roster.txt` | clinicians and NPIs only, **zero patients** — a negative control |
| `adv_03_fax_referral_letter.txt` | fax-to-text OCR damage (`8l0` for `810`), a ward named after a person |
| `adv_04_intake_questionnaire.txt` | family history naming relatives, plus an emergency contact |
| `adv_05_elderly_discharge_summary.txt` | a 94-year-old and a full ZIP — both Safe Harbor edge cases |
| `adv_06_lab_billing_reconciliation.txt` | CPT and ICD-10 codes beside accession and invoice numbers |

`data/tables/`:

- **`dirty_intake.csv`** — 200 rows of the mess real exports contain: four MRN formats in
  one column, three date formats, ZIP codes that lost their leading zero to a spreadsheet,
  masked and sentinel SSNs, and free-text `comments` carrying other people's names and
  phone numbers.
- **`patients_clean.csv`** and **`patients_opaque.csv`** — the same 111 records twice, once
  with readable headers (`ssn`, `date_of_birth`, `zip_code`) and once with opaque ones
  (`f_14`, `dt_2`, `pcode`). Comparing the two shows how much detection leans on column
  names versus the shape of the values.

## What you get

```
outputs/
  single/     per-file findings JSON — every detection with confidence and provenance
  reports/    corpus_risk.md — exposure index, severity, heatmap, HIPAA checklist
  scrubbed/   de-identified copies, same filenames as the inputs
```

Sample outputs are committed so you can read them without running anything. Two large batch
artifacts are not: `reports/corpus_risk.json` (~5MB) and `batch/corpus_findings.json` (~2MB)
are regenerated when you run `batch`.

A scrubbed row looks like this:

```csv
rec_id,pat_nm,mrn,ssn_num,dob,phone,zip_cd,comments,status,amount
R-0001,[PERSON],[ID_NUM],[SSN],[DATE_OF_BIRTH],[PHONE],[ZIPCODE],[TIME],active,124.50
```

`rec_id`, `status` and `amount` pass through untouched — the scrub removes identity, not
the whole record.

## Options

| Flag | Applies to | Notes |
|---|---|---|
| `--max-rows N` | all | Cap rows per table |
| `--out DIR` | all | Output root, default `examples/outputs/` |
| `--stem NAME` | `batch` | Output filename prefix; different runs overwrite otherwise |
| `--optimize` | `batch` | Run the action optimizer (off by default) |
| `--ner-backend` | all | `openmed` (default) or `spacy` |
| `--llm-backend` | all | `openai`, `transformers`, `ollama`, `llama_cpp`, `vllm` — no LLM stage runs unless set |

## A note on the console output

Every run logs `Failed to create pipeline for OpenMed/...: AutoConfig.from_pretrained() got
multiple values for keyword argument 'local_files_only'`, followed by `Loading weights`.
That error is raised and handled inside openmed, which then loads the model directly — NER
still runs. It is noisy, not fatal.
