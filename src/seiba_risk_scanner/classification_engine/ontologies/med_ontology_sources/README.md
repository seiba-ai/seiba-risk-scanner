# Medical terms gazetteer

Runtime uses `cleaned/medical_terms_gazetteer.json` only. Raw dumps stay local (gitignored) — see root [NOTICE](../../../../../NOTICE).

## Rebuild (incl. RxNorm)

1. Get a UMLS/RxNorm license and download **RXNCONSO.RRF**.
2. Place sources next to this README:

```text
med_ontology_sources/
  MONDO.csv
  RXNCONSO.RRF
  CHV_concepts_terms_flatfile_20110204.csv   # optional; lay-term aliases
```

3. From the repo root (package installed editable):

```bash
python -m seiba_risk_scanner.classification_engine.ontologies.gazetteer.build
```

Writes `cleaned/medical_terms_gazetteer.json` (MONDO diseases + RxNorm meds + CHV aliases typed against them).

Do **not** commit raw `.RRF` / source `.csv` dumps. Redistributing RxNorm/UMLS content (including derived lists) requires your own compliance review.
