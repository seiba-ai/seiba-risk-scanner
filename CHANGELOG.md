# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

<!-- TODO(release): move the entries below under a dated [0.1.0] heading when the tag is cut -->

## [0.1.0] — unreleased

First public release. Seiba finds sensitive data, scores how exposed it makes people,
de-identifies it under a policy, and measures what that cost.

### Added

**Detection**
- `SeibaScanner` with `classify_text()`, `classify_texts()`, `classify_structured_text()`
  and deterministic-only variants.
- Layered pipeline: deterministic regex + validators → medical gazetteer → contextual
  scoring → multi-hypothesis fusion → NER.
- 84 entities across three ontology YAMLs (PII / PHI / financial), with detection rules,
  validators, contextual phrases and policy actions all declared in config rather than code.
- Two NER backends — `openmed` (default) and `spacy` — plus `make_hf_ner_runner()` and
  `make_custom_ner_runner()` for bringing your own model.
- Medical gazetteer: ~105k curated surface forms over MONDO / RxNorm / CHV, with canonical
  term and source code carried through on every match.
- Structured-aware scanning: column keys are used as evidence, NER is batched over unique
  cell values, and validated-ID cells skip the model entirely.
- Optional post-fusion LLM refinement stage (`openai`, `transformers`, `ollama`,
  `llama_cpp`, `vllm`), off by default.

**Assessment**
- Severity engine anchored on `data_class`, deliberately decoupled from detector
  confidence — confidence routes findings to human review instead of discounting severity.
- Precision-aware scoring: coarse values (a bare year, a 3-digit zip) score below exact ones.
- Corpus pass: co-occurring identifier types and singleton records escalate to `critical`;
  a lone finding tops out at `high`.
- k-anonymity and re-identification risk via `openmed.risk`.
- Exposure index (0–100), HIPAA Safe Harbor 18-category checklist, regulatory mapping
  (GDPR / CCPA / HIPAA / PCI), per-entity and per-record rollups, location heatmap,
  human review queue.
- Every finding carries a `rule_trace` naming each rule that moved its score.

**Policy and de-identification**
- OpenMed policy profiles, `hipaa_safe_harbor` by default.
- Actions: `keep`, `mask`, `redact`, `hash`, `replace`, `format_preserve`, and the
  Seiba-owned `generalize`.
- Generalization ladders for dates, ages, zip codes and coordinates, defaulting to the
  Safe Harbor thresholds — coarsen rather than destroy.
- Per-entity `default_action` in the ontology YAML, validated at load time; per-run
  `action_overrides`.

**Optimizer** (off by default)
- Single `optimize=` argument taking `Privacy.MAXIMUM | BALANCED | REQUIRED` or a tuned
  `OptimizerConfig`.
- Direct identifiers decided in closed form; only quasi-identifiers are searched, using
  lattice monotonicity to skip dominated combinations.

**Measurement and reporting**
- Residual risk (`reid_rate`, `leakage_rate`) measured from an original ↔ scrubbed pair.
- Retained analytic value scored from three checkable properties of each rewritten value.
- Exposure before vs after de-identification.
- Markdown + JSON reports written together, plain-language throughout, with a glossary
  per table.
- `report_from_paths()` as the one-call SDK entry point for files or folders.

**Evaluation**
- `eval/` harness with span-level gold: 18 unstructured documents (1,140 spans) and
  3 structured fixtures (1,320 cells).
- Per-entity and headline precision / recall / F1 under both `type_overlap` and `strict`
  matchers, plus NER latency.
- Every run writes predictions and full false-positive, false-negative and rescue lists.
- Regression gates (`tests/test_eval_regression.py`,
  `tests/test_structured_eval_regression.py`) against checked-in baselines.

### Measured performance

Against the bundled synthetic gold set, OpenMed backend:

| Set | Metric | Value |
|---|---|---|
| Unstructured (18 docs, 1,140 spans) | micro F1 | 0.826 (P 0.762 / R 0.901) |
| Unstructured | macro F1 | 0.821 |
| Unstructured | strict micro F1 | 0.787 |
| Structured (1,320 cells) | micro F1 | 1.000 |

Severity classification is **not** benchmarked — the harness grades detection only.

### Known limitations

- Precision is the weak axis; the tool over-flags rather than under-flags.
- Non-Anglo surname recall is lower than Anglo surname recall, and is unquantified.
- English only.
- The evaluation corpus is synthetic and small (18 documents) — treat the numbers as a
  floor for well-formed English text, not a guarantee for your corpus.
- `provider_npi` scores poorly (F1 0.125) against this corpus because most of its NPIs are
  made-up digits that fail the NPI checksum. This is a fixture defect, not a detection
  failure; expect materially better NPI performance on real data.
- `ACTION_SEVERITY_RETENTION` (how much severity survives each action) is a hand-picked
  estimate, not measured, and is not user-configurable.
- Residual severity recomputes only the exposure index and severity histogram; the HIPAA
  checklist, compliance summary and review queue still reflect pre-scrub state.
- No generalization ladder exists for city / state / county.
- No packaged CLI.

See the [Readme](Readme.md#limitations) for the full list.

### Notes

- `openmed[hf]` is a required dependency: it powers the default NER backend, policy
  profiles, k-anonymity and residual risk. All inference is local.
- Raw vocabulary source dumps (RxNorm / UMLS, MONDO, CHV) are **not** redistributed —
  only the curated runtime gazetteer artifact ships. See [NOTICE](NOTICE).

[Unreleased]: https://github.com/seiba-ai/seiba-risk-scanner/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/seiba-ai/seiba-risk-scanner/releases/tag/v0.1.0
