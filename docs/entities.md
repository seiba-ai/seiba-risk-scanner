# Entity taxonomy

Every kind of sensitive data Seiba can detect, what it treats each one as, and how it finds it.

**84 entities** across three ontology files under
`src/seiba_risk_scanner/classification_engine/ontologies/`. Those YAML files are the
configuration surface — to change coverage or behaviour, edit them rather than the Python.

Generated from the bundled ontologies at version 0.1.0. To read the current values directly:

```python
from seiba_risk_scanner import load_entity_configs

for entity_id, config in sorted(load_entity_configs().items()):
    print(entity_id, config.data_class, config.de_identifier, config.default_action)
```

---

## How to read the columns

- **Entity** — the entity name. Its stable ID is `{ontology_stem}::{entity_name}`, e.g.
  `pii_entity_ontology::ssn`. IDs are what you match on in code; they do not change.
- **Data class** — the single anchor for severity, and the direct/quasi split that
  re-identification analysis needs. See [Data classes](#data-classes).
- **Sev.** — base severity from that data class, 0–1, before any corpus escalation. A lone
  finding tops out at `high`; `critical` is only reachable when identifiers stack in one record
  or the record is unique. Detector confidence never changes this number.
- **OpenMed label** — the canonical label used for exact policy lookup. `—` means there is no
  honest OpenMed equivalent, so policy falls back through the data class.
- **Detection** — how the entity is found. *context + NER* means it has no regex at all and
  relies on surrounding words and the model; *validator* means a checksum or format rule that
  separates a real identifier from a lookalike number.
- **HIPAA category** — which of the 18 Safe Harbor identifier categories it reports under.
  `—` means it is not a Safe Harbor identifier: `state` is permitted (only subdivisions
  *smaller* than a state count), and clinical values such as diagnoses and lab results are the
  health data itself, not identifiers.
- **Notes** — `reported as X` marks an `is_a` rollup (see below); the phrase count indicates how
  much the entity leans on surrounding context.

---

## Data classes

`data_class` is deliberately the only severity input. It carries both harm and identifying
power, so one axis does the whole job.

| Data class | Sev. | Count | Meaning |
|---|---|---|---|
| `direct_identifier` | 0.90 | 38 | Names a specific person outright |
| `genetic_data` | 0.90 | 2 | Identifies *and* is itself a protected value |
| `biometric_identifier` | 0.90 | 4 | Fingerprints, retinal scans, voiceprints |
| `financial_data` | 0.85 | 8 | Cards, accounts, wallets |
| `sensitive_attribute` | 0.80 | 10 | The protected values k-anonymity guards |
| `device_identifier` | 0.60 | 0 | Device serials, MAC, IMEI |
| `quasi_identifier` | 0.55 | 18 | Harmless alone; combines to single someone out |
| `neutral` | 0.30 | 4 | Not personal data — no regulation applies |

Only `direct_identifier`, `genetic_data`, `biometric_identifier` and `financial_data` count as
*strong* identifiers for co-occurrence escalation: stacking three names does not pin down a
person, but name + SSN + date of birth does.

---

## Rollups (`is_a`)

Four entities are detected by their own patterns and phrases but **reported as the broader entity
they are a kind of**:

| Detected as | Reported as | Why |
|---|---|---|
| `physician_names` | `person_names` | Which *kind* of person someone is is a guess; that they are a person is not |
| `employer_organization` | `organization` | Same reasoning for organizations |
| `hospital_names` | `organization` | |
| `hospital_abbreviations` | `organization` | |

A wrong guess about the subtype can never drop the span out of the class we are certain about.
The finer detection is preserved on `detected_subtype`, so severity, policy and audit can still
use it — a physician is de-identified as a clinician, not merely as a person.

---

## Actions

Every entity ships with `default_action: DEFAULT`, meaning the chosen policy profile decides.
Override per entity in the YAML, or per run via `action_overrides`.

| Action | Effect |
|---|---|
| `keep` | Leave the value untouched |
| `mask` / `redact` | Blank it out — `[ENTITY]` |
| `hash` | Stable token; hides the value but keeps records joinable |
| `replace` | Realistic fake value |
| `format_preserve` | Fake value keeping the original shape |
| `generalize[:level]` | Coarsen instead of destroy |

`generalize` applies only where a defensible ladder exists — dates (`month|year|decade`), ages
(`5|10|20_year_band`), zip codes (`3_digit|1_digit`) and coordinates (`1_decimal|integer`).
Defaults follow HIPAA Safe Harbor, which prescribes coarsening rather than deletion for exactly
these fields. Anything else has no meaningful middle ground, so it is kept or destroyed.

---

## Coverage at a glance

- **30 of 84** entities have no regex at all and are found by context and NER alone — mostly
  names, organizations and clinical concepts, where a pattern would be meaningless.
- **24** carry a format or checksum validator. A validated hit is treated as proof: NER is not
  allowed to relabel it.
- **65** map to an OpenMed label for exact policy lookup; the remaining 19 fall back through
  their data class.

---

## The entities

### PII — `pii_entity_ontology`

Identity, contact details, geography, government IDs, and dates. **44 entities.**

| Entity | Data class | Sev. | OpenMed label | Detection | HIPAA category | Notes |
|---|---|---|---|---|---|---|
| `account_reference_number` | direct_identifier | 0.90 | `ACCOUNT_NUMBER` | 1 pattern(s) | account number | 6 context phrases |
| `australian_passport_number` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) | other unique id | 5 context phrases |
| `canadian_passport_number` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) | other unique id | 5 context phrases |
| `canadian_social_insurance_number_sin` | direct_identifier | 0.90 | `—` | 1 pattern(s) + validator | other unique id | 3 context phrases |
| `device_serial_number` | direct_identifier | 0.90 | `ID_NUM` | context + NER | device identifier | — |
| `drivers_license_number` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) | certificate license number | 12 context phrases |
| `email_address` | direct_identifier | 0.90 | `EMAIL` | 5 pattern(s) | email | 5 context phrases |
| `fax_number` | direct_identifier | 0.90 | `PHONE` | 1 pattern(s) + validator | fax | 3 context phrases |
| `german_passport_number` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) | other unique id | 5 context phrases |
| `imei_number` | direct_identifier | 0.90 | `IMEI` | 1 pattern(s) + validator | device identifier | — |
| `indian_aadhaar_number` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) + validator | other unique id | 3 context phrases |
| `indian_passport_number` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) | other unique id | 5 context phrases |
| `ip_address` | direct_identifier | 0.90 | `IP_ADDRESS` | 1 pattern(s) + validator | ip address | — |
| `mac_address` | direct_identifier | 0.90 | `MAC_ADDRESS` | 1 pattern(s) | device identifier | — |
| `passport_number` | direct_identifier | 0.90 | `ID_NUM` | context + NER | other unique id | 6 context phrases |
| `person_names` | direct_identifier | 0.90 | `PERSON` | context + NER | names | 16 context phrases |
| `phone_number` | direct_identifier | 0.90 | `PHONE` | 1 pattern(s) + validator | telephone | 10 context phrases |
| `po_box` | direct_identifier | 0.90 | `—` | context + NER | geographic subdivision | 3 context phrases |
| `ssn` | direct_identifier | 0.90 | `SSN` | 1 pattern(s) + validator | ssn | 5 context phrases |
| `street_address` | direct_identifier | 0.90 | `STREET_ADDRESS` | 2 pattern(s) | geographic subdivision | 29 context phrases |
| `uk_national_insurance_number_nino` | direct_identifier | 0.90 | `—` | context + NER | other unique id | 3 context phrases |
| `uk_nhs_number` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) + validator | other unique id | 4 context phrases |
| `uk_passport_number` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) | other unique id | 6 context phrases |
| `unique_identifier` | direct_identifier | 0.90 | `ACCOUNT_NUMBER` | 2 pattern(s) | other unique id | 19 context phrases |
| `us_ein` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) | other unique id | 8 context phrases |
| `us_itin` | direct_identifier | 0.90 | `—` | 1 pattern(s) + validator | other unique id | 3 context phrases |
| `us_passport_number` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) | other unique id | 6 context phrases |
| `vehicle_identification_number_vin` | direct_identifier | 0.90 | `VIN` | 1 pattern(s) + validator | vehicle identifier | — |
| `web_url` | direct_identifier | 0.90 | `URL` | 1 pattern(s) + validator | url | — |
| `relative_date_expressions` | neutral | 0.30 | `—` | 6 pattern(s) | dates | 9 context phrases |
| `uuid_guid` | neutral | 0.30 | `ID_NUM` | 2 pattern(s) | other unique id | — |
| `age` | quasi_identifier | 0.55 | `AGE` | 4 pattern(s) | dates | 5 context phrases |
| `city` | quasi_identifier | 0.55 | `LOCATION` | context + NER | geographic subdivision | 8 context phrases |
| `county` | quasi_identifier | 0.55 | `LOCATION` | 1 pattern(s) | geographic subdivision | 1 context phrases |
| `dates` | quasi_identifier | 0.55 | `DATE` | 8 pattern(s) + validator | dates | 19 context phrases |
| `employer_organization` | quasi_identifier | 0.55 | `ORGANIZATION` | context + NER | — | reported as `organization`; 8 context phrases |
| `latitude_coordinates` | quasi_identifier | 0.55 | `GPS_COORDINATES` | 2 pattern(s) + validator | geographic subdivision | 7 context phrases |
| `longitude_coordinates` | quasi_identifier | 0.55 | `GPS_COORDINATES` | 2 pattern(s) + validator | geographic subdivision | 8 context phrases |
| `nationality` | quasi_identifier | 0.55 | `—` | context + NER | — | 5 context phrases |
| `organization` | quasi_identifier | 0.55 | `ORGANIZATION` | context + NER | — | 18 context phrases |
| `state` | quasi_identifier | 0.55 | `LOCATION` | context + NER | — | 5 context phrases |
| `timestamps` | quasi_identifier | 0.55 | `TIME` | 4 pattern(s) + validator | dates | 9 context phrases |
| `zip_code` | quasi_identifier | 0.55 | `ZIPCODE` | 1 pattern(s) + validator | geographic subdivision | 59 context phrases |
| `religious_affiliation` | sensitive_attribute | 0.80 | `—` | context + NER | — | 10 context phrases |

### PHI — `phi_entity_ontology`

Clinical and administrative health data, medical codes, and biometrics. **31 entities.**

| Entity | Data class | Sev. | OpenMed label | Detection | HIPAA category | Notes |
|---|---|---|---|---|---|---|
| `facial_photographs` | biometric_identifier | 0.90 | `—` | context + NER | full face photo | — |
| `fingerprints` | biometric_identifier | 0.90 | `—` | context + NER | biometric identifier | — |
| `retinal_scans` | biometric_identifier | 0.90 | `—` | context + NER | biometric identifier | — |
| `voiceprints` | biometric_identifier | 0.90 | `—` | context + NER | biometric identifier | — |
| `authorization_precertification_code` | direct_identifier | 0.90 | `ID_NUM` | context + NER | other unique id | — |
| `certificate_license_number` | direct_identifier | 0.90 | `ID_NUM` | context + NER | certificate license number | 12 context phrases |
| `claim_control_number` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) | other unique id | 7 context phrases |
| `date_of_birth` | direct_identifier | 0.90 | `DATE_OF_BIRTH` | context + NER | dates | 7 context phrases |
| `date_of_death` | direct_identifier | 0.90 | `DATE` | context + NER | dates | 11 context phrases |
| `health_plan_beneficiary_number` | direct_identifier | 0.90 | `ID_NUM` | 2 pattern(s) | health plan beneficiary number | 29 context phrases |
| `medical_record_number_mrn` | direct_identifier | 0.90 | `ID_NUM` | 3 pattern(s) | medical record number | 23 context phrases |
| `provider_npi` | direct_identifier | 0.90 | `ID_NUM` | 1 pattern(s) + validator | other unique id | 6 context phrases |
| `provider_tax_id_ein` | direct_identifier | 0.90 | `ID_NUM` | context + NER | other unique id | — |
| `dna_sequences` | genetic_data | 0.90 | `—` | context + NER | biometric identifier | — |
| `genomic_variants` | genetic_data | 0.90 | `—` | 5 pattern(s) | biometric identifier | 19 context phrases |
| `measurement_units` | neutral | 0.30 | `—` | context + NER | — | — |
| `relative_date_expressions` | neutral | 0.30 | `—` | 5 pattern(s) | dates | 23 context phrases |
| `dates` | quasi_identifier | 0.55 | `DATE` | 5 pattern(s) + validator | dates | 19 context phrases |
| `hospital_abbreviations` | quasi_identifier | 0.55 | `ORGANIZATION` | context + NER | — | reported as `organization` |
| `hospital_names` | quasi_identifier | 0.55 | `ORGANIZATION` | context + NER | — | reported as `organization` |
| `physician_names` | quasi_identifier | 0.55 | `PERSON` | context + NER | names | reported as `person_names`; 19 context phrases |
| `timestamps` | quasi_identifier | 0.55 | `TIME` | 2 pattern(s) + validator | dates | — |
| `cpt_procedure_codes` | sensitive_attribute | 0.80 | `PROCEDURE` | 1 pattern(s) | — | 5 context phrases |
| `hcpcs_codes` | sensitive_attribute | 0.80 | `PROCEDURE` | context + NER | — | — |
| `icd10_diagnosis_codes` | sensitive_attribute | 0.80 | `CONDITION` | 1 pattern(s) | — | 8 context phrases |
| `lab_results` | sensitive_attribute | 0.80 | `LAB_TEST` | context + NER | — | — |
| `medical_condition` | sensitive_attribute | 0.80 | `CONDITION` | context + NER | — | 9 context phrases |
| `medication_dosage` | sensitive_attribute | 0.80 | `—` | 3 pattern(s) | — | 15 context phrases |
| `medication_name` | sensitive_attribute | 0.80 | `MEDICATION` | context + NER | — | 8 context phrases |
| `ndc_codes` | sensitive_attribute | 0.80 | `MEDICATION` | context + NER | — | — |
| `vital_signs` | sensitive_attribute | 0.80 | `—` | 5 pattern(s) | — | 16 context phrases |

### Financial — `fin_entity_ontology`

Payment cards, bank accounts, routing details, and crypto wallets. **9 entities.**

| Entity | Data class | Sev. | OpenMed label | Detection | HIPAA category | Notes |
|---|---|---|---|---|---|---|
| `bank_account_number` | financial_data | 0.85 | `ACCOUNT_NUMBER` | 1 pattern(s) | account number | 25 context phrases |
| `card_expiry_date` | financial_data | 0.85 | `—` | 1 pattern(s) | dates | 11 context phrases |
| `credit_card_number` | financial_data | 0.85 | `CREDIT_CARD` | 3 pattern(s) + validator | account number | 11 context phrases |
| `crypto_wallet_address` | financial_data | 0.85 | `BITCOIN_ADDRESS` | 2 pattern(s) | account number | 7 context phrases |
| `cvv_code` | financial_data | 0.85 | `CVV` | 1 pattern(s) | account number | 5 context phrases |
| `iban` | financial_data | 0.85 | `IBAN` | 1 pattern(s) + validator | account number | — |
| `payment_transaction_id` | financial_data | 0.85 | `—` | 1 pattern(s) | account number | 9 context phrases |
| `swift_bic` | financial_data | 0.85 | `BIC` | 1 pattern(s) | account number | 6 context phrases |
| `routing_number_aba` | quasi_identifier | 0.55 | `ACCOUNT_NUMBER` | 1 pattern(s) + validator | account number | 9 context phrases |

---

## Adding an entity

No Python required. Add a block to the relevant ontology YAML:

```yaml
  uk_driving_licence_number:
    description: "UK driving licence number"
    regex_patterns:
      accepted_patterns:
        - |-
          \b[A-Z9]{5}\d{6}[A-Z9]{2}\d[A-Z]{2}\b
      prohibited_patterns: []
      confidence_weight: 0.75
    validators:
      enum: null
      confidence_weight: null
    contextual_phrases:
      values: [driving licence, licence number, dvla]
      confidence_weight: null
    prohibited_prefix: { values: [], confidence_weight: null }
    prohibited_suffix: { values: [], confidence_weight: null }
    classification:
      category: PII
      data_class: direct_identifier
    de_identifier: ID_NUM
    default_action: DEFAULT
```

Then add gold annotations under `eval/ground_truth/` and re-run `python3 -m eval.runner` so the
change is measured rather than assumed. A bad `default_action` fails loudly at load time, naming
the entity.

Two things worth knowing before you tune anything:

- **Contextual scoring can only re-score a span that already exists — it can never create one.**
  An entity with no patterns needs NER to produce the span first.
- **A low `ner_confidence_weight` is a demotion that invites relabeling, not a suppressor.** To
  reject a junk span, stop it existing — via `prohibited_patterns` or by not mapping the label.
