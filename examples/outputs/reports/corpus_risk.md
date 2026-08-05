# Sensitive Data Risk Report

*Scope: 9 source(s): adv_01_neurology_consult.txt, adv_02_care_team_roster.txt, adv_03_fax_referral_letter.txt, adv_04_intake_questionnaire.txt, adv_05_elderly_discharge_summary.txt ….*

## Exposure index

# 46.9 / 100

**0 means nothing sensitive was found. 100 means maximally exposed.**

This is *not* a pass/fail grade. Whether this level of exposure is acceptable depends on what the data is for — a clinical registry is supposed to hold patient names. Use it to compare datasets, or to track one dataset over time.

**How it was calculated**

- **48%** of findings are high or critical severity
- **97%** of the 428 records are re-identifiable (fewer than 5 records share their combination of traits)

*(method: severity_x_uniqueness)*

## At a glance

The size of the job: how much sensitive data was found, and where.

|  | Count |
|---|---|
| Findings | 5889 |
| Locations with findings | 59 |
| Records scanned | 428 |
| Findings needing human review | 1730 |

**Reading this table**

- **Finding** — one sensitive value found in one cell. A table of 40 rows with 11 sensitive columns gives 440 findings, not 40
- **Location** — the column a finding sat in
- **Record** — one table row, i.e. one person's worth of data

## Severity of what was found

Severity = how bad this would be if exposed. It starts from the *kind* of data, then rises when several identifiers sit together in one record, or when that record is unique in the dataset. It does **not** depend on how confident the scanner is.

| Severity | Findings | What it means |
|---|---|---|
| critical | 2777 | Names a specific person outright |
| high | 29 | Harmful on its own — a direct, financial, or health identifier |
| medium | 2860 | Harmless alone, but narrows down who someone is when combined with other fields |
| low | 223 | Barely sensitive |

## Where the risk is

Which columns (or documents) the sensitive data actually sits in — so you know where to act first.

**Reading this table**

- **Location** — one column of the table
- **The number** — how many **findings** of that severity sat there — not how many rows. In a clean table every row has the same columns, so a column scanned across 40 rows shows 40
- **Blank** — none of that severity here

| Location | critical | high | medium | low | info |
|---|---|---|---|---|---|
| pat_nm | 263 |  |  |  |  |
| dob | 204 |  | 1 |  |  |
| mrn | 200 | 1 |  |  |  |
| phone | 175 |  |  |  |  |
| ssn_num | 136 |  |  |  |  |
| addr_x | 111 |  |  |  |  |
| f_14 | 111 |  |  |  |  |
| first_name | 111 |  |  |  |  |
| geo_a | 111 |  |  |  |  |
| geo_b | 111 |  |  |  |  |
| last_name | 111 |  |  |  |  |
| nm_a | 111 |  |  |  |  |
| nm_c | 111 |  |  |  |  |
| ssn | 111 |  |  |  |  |
| street_address | 111 |  |  |  |  |
| comments | 100 | 1 | 27 |  |  |
| f_23 | 92 |  |  |  |  |
| passport_number | 92 |  |  |  |  |
| middle_name | 85 |  |  |  |  |
| nm_b | 85 |  |  |  |  |
| loc_1 | 47 |  | 48 |  |  |
| maiden_name | 40 |  |  |  |  |
| nm_d | 40 |  |  |  |  |
| adv_02_care_team_roster.txt | 27 | 3 | 13 |  |  |
| adv_04_intake_questionnaire.txt | 17 | 6 | 15 |  |  |
| adv_06_lab_billing_reconciliation.txt | 17 | 6 | 15 |  |  |
| adv_01_neurology_consult.txt | 11 | 6 | 10 |  |  |
| adv_03_fax_referral_letter.txt | 13 | 3 | 11 | 1 |  |
| adv_05_elderly_discharge_summary.txt | 11 | 3 | 20 |  |  |
| birthplace | 3 |  | 216 |  |  |
| loc_0 | 3 |  | 216 |  |  |
| c_2 | 2 |  | 1 |  |  |
| suffix | 2 |  | 1 |  |  |
| c_4 | 1 |  |  |  |  |
| race | 1 |  |  |  |  |
| amt_1 |  |  | 111 |  |  |
| amt_2 |  |  | 111 |  |  |
| amt_3 |  |  | 111 |  |  |
| city |  |  | 111 |  |  |
| county |  |  | 111 |  |  |
| coverage |  |  | 111 |  |  |
| date_of_birth |  |  | 111 |  |  |
| date_of_death |  |  | 13 |  |  |
| dt_2 |  |  | 111 |  |  |
| dt_9 |  |  | 13 |  |  |
| expenses |  |  | 111 |  |  |
| f_01 |  |  |  | 111 |  |
| fips |  |  | 84 |  |  |
| income |  |  | 111 |  |  |
| latitude |  |  | 111 |  |  |
| loc_2 |  |  | 111 |  |  |
| loc_3 |  |  | 111 |  |  |
| longitude |  |  | 111 |  |  |
| num_7 |  |  | 84 |  |  |
| patient_id |  |  |  | 111 |  |
| pcode |  |  | 111 |  |  |
| state |  |  | 111 |  |  |
| zip_cd |  |  | 185 |  |  |
| zip_code |  |  | 111 |  |  |

## Data types / entities identified

The inventory: which *types* of sensitive data live in this dataset, and how exposed each type is.

**Reading this table**

- **Data type** — the kind of sensitive data (a name, an email, a zip code)
- **Findings** — how many times it appeared across the whole dataset
- **Worst severity** — the most severe any single one of them reached
- **Typical severity** — their average score, 0 (harmless) to 1 (identifies someone outright). Values of the same type usually score alike, so this number repeats
- **Rolled up from** — a more specific type that was matched but is reported under this broader one (a physician reported as a person). **`—` means nothing was rolled up** — the type was matched directly
- **Regulations** — which rules treat this type as regulated data

| Data type | Findings | Worst severity | Typical severity (0–1) | Rolled up from | Regulations |
|---|---|---|---|---|---|
| zip_code | 1262 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| person_names | 1123 | critical | 0.95 | physician_names (15) | CCPA, GDPR, HIPAA |
| state | 448 | medium | 0.55 | — | CCPA, GDPR |
| city | 392 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| ssn | 348 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| dates | 276 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| street_address | 233 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| county | 230 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| phone_number | 224 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| uuid_guid | 222 | low | 0.30 | — | HIPAA |
| date_of_birth | 211 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| medical_record_number_mrn | 210 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| credit_card_number | 188 | critical | 0.93 | — | CCPA, GDPR, HIPAA, PCI |
| genomic_variants | 184 | critical | 0.96 | — | CCPA, GDPR, HIPAA |
| latitude_coordinates | 111 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| longitude_coordinates | 111 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| imei_number | 31 | critical | 0.96 | — | CCPA, GDPR, HIPAA |
| medical_condition | 25 | high | 0.91 | — | CCPA, GDPR, HIPAA |
| timestamps | 14 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| organization | 12 | medium | 0.55 | hospital_names (5), employer_organization (5) | CCPA, GDPR |
| us_itin | 11 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| bank_account_number | 5 | critical | 0.93 | — | CCPA, GDPR, HIPAA |
| age | 4 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| icd10_diagnosis_codes | 3 | high | 0.91 | — | CCPA, GDPR, HIPAA |
| indian_aadhaar_number | 3 | critical | 0.96 | — | CCPA, GDPR, HIPAA |
| payment_transaction_id | 2 | critical | 0.93 | — | CCPA, GDPR, HIPAA |
| unique_identifier | 2 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| certificate_license_number | 1 | critical | 0.96 | — | CCPA, GDPR, HIPAA |
| claim_control_number | 1 | critical | 0.96 | — | CCPA, GDPR, HIPAA |
| date_of_death | 1 | critical | 0.96 | — | CCPA, GDPR, HIPAA |
| relative_date_expressions | 1 | low | 0.30 | — | HIPAA |

## Riskiest records

The individual people (rows, or documents) most exposed by this dataset. Ranked by how *concentrated* the risk is, not how much text there is — otherwise the longest document would always win on volume alone. Showing the top 10; in a uniform table every row holds the same columns, so many rows tie on an identical score.

**Reading this table**

- **Record** — one table row
- **Composite identifier types** — how many **different kinds** of strong identifier sit together here (name + SSN + email = 3). Ten names still count as one, because ten names pin down a person no better than one does. This is the main ranking: identifiers stacking up is what makes a record dangerous
- **Avg severity** — average severity of this record's findings, 0–1
- **Total risk** — those severity scores added up (11 findings averaging 0.73 = 8.1). It grows with size, so use it to compare records of similar length — it is deliberately **not** what ranks this table
- **Findings** — every sensitive value in the record, weak ones included. Always ≥ composite identifier types, which counts only distinct strong kinds
- **Unique** — **`yes` is bad** — nobody else shares this record's combination of traits, so this person can be picked out of the crowd. `no` is safer: they blend in with at least one other record

| Record | Composite identifier types | Avg severity | Total risk | Findings | Worst severity | Unique |
|---|---|---|---|---|---|---|
| adv_06_lab_billing_reconciliation.txt | 9 | 0.79 | 29.9 | 38 | critical | yes |
| dirty_intake.csv row 13 | 6 | 0.91 | 7.2 | 8 | critical | yes |
| dirty_intake.csv row 137 | 6 | 0.90 | 7.2 | 8 | critical | yes |
| dirty_intake.csv row 79 | 6 | 0.90 | 7.2 | 8 | critical | yes |
| dirty_intake.csv row 9 | 6 | 0.90 | 7.2 | 8 | critical | yes |
| dirty_intake.csv row 37 | 6 | 0.89 | 6.3 | 7 | critical | yes |
| dirty_intake.csv row 4 | 6 | 0.89 | 6.3 | 7 | critical | yes |
| dirty_intake.csv row 20 | 6 | 0.85 | 6.8 | 8 | critical | yes |
| dirty_intake.csv row 122 | 6 | 0.82 | 7.4 | 9 | critical | yes |
| adv_04_intake_questionnaire.txt | 6 | 0.79 | 30.0 | 38 | critical | yes |

## HIPAA Safe Harbor checklist

HIPAA lists 18 categories of identifier that must be removed for health data to count as de-identified. This is which of the 18 appear in your data.

| Identifier category present | Findings | Found as |
|---|---|---|
| names | 1123 | person_names |
| geographic subdivision | 2339 | city, county, latitude_coordinates, longitude_coordinates, street_address, zip_code |
| dates | 507 | age, date_of_birth, date_of_death, dates, relative_date_expressions, timestamps |
| telephone | 224 | phone_number |
| ssn | 348 | ssn |
| medical record number | 210 | medical_record_number_mrn |
| account number | 195 | bank_account_number, credit_card_number, payment_transaction_id |
| certificate license number | 1 | certificate_license_number |
| device identifier | 31 | imei_number |
| biometric identifier | 184 | genomic_variants |
| other unique id | 239 | claim_control_number, indian_aadhaar_number, unique_identifier, us_itin, uuid_guid |

**Not found (7 of 18):** fax, email, health plan beneficiary number, vehicle identifier, url, ip address, full face photo

> HIPAA is tagged below because this dataset was identified as health data.

> A category being absent means the scanner found none — not that none exist. Some categories can only be detected when they appear as text: photographs and fingerprint scans cannot be, while genetic sequences can.

## Regulatory exposure

Which rulebooks this data falls under, and how much of it each one covers.

**Reading this table**

- **Findings subject to it** — how many of the findings above that regulation treats as regulated data. One finding can count under several regulations at once, so these columns overlap and will not add up to the total
- **Worst severity** — the most severe finding in that regulation's scope

| Regulation | Findings subject to it | Worst severity |
|---|---|---|
| CCPA | 5666 | critical |
| GDPR | 5666 | critical |
| HIPAA | 5429 | critical |
| PCI | 188 | critical |

> **These are counts, not scores** — a bigger number is not automatically worse, it just reflects how much data of that kind is present.

> **How the mapping is decided — and how far to trust it.** This is decided by this scanner's own ontology, not by OpenMed, using one deliberately simple rule: any data type not marked *neutral* counts as personal data (GDPR + CCPA); a type classified as health data adds HIPAA; a financial instrument adds PCI.

> **Reliable:** *is this personal data at all* — that follows directly from the data type and is dependable. **Not reliable:** *which jurisdiction applies to you*. The rule tags GDPR and CCPA on every personal-data finding regardless of whether your subjects are EU or California residents, or whether your business meets CCPA's thresholds. Read the counts as **"this much data would be in scope if that law applies to you"**, not as a finding that it does. **Not legal advice** — a lawyer confirms which regimes bind you.

## Re-identification risk of individuals

Could someone work out *who* a record belongs to, even after the obvious identifiers (name, email) are taken away — just by combining ordinary-looking fields like city, zip code and visit date? This measures the data **as scanned, before any scrubbing**.

### 97% of records can be singled out — **CRITICAL**

- **404 of 417 records** sit below the k=5 bar used to call data de-identified.
- **404** are completely one of a kind (nobody else matches them at all).
- **Smallest crowd size (k) = 1.**
- Compared on these traits: **age, amt_1, amt_2, amt_3, birthplace, c_2, city, comments, county, coverage, date_of_birth, date_of_death, dates, dob, dt_2, dt_9, expenses, fips, income, latitude, loc_0, loc_1, loc_2, loc_3, longitude, num_7, organization, pcode, state, suffix, timestamps, zip_cd, zip_code**
- Values that would be exposed: **comments, f_23, icd10_diagnosis_codes, medical_condition, passport_number**

**What k means.** k is the size of the crowd a person hides in: how many records share their exact combination of the traits above. k=1 means that person matches nobody else and can be picked out; k=5 or more is the usual bar for calling data de-identified. Higher k = safer.

> These numbers are only as good as the traits listed above. Comparing on one weak field makes data look safer than it really is.

## De-identification strength (what the scrub left behind)

The policy was applied, then the scrubbed data was compared back against the original. The first numbers say how *safe* the result is (lower is better); the last says how much of the data's structure survived (higher is better).

- **Residue left behind: 0% — clean.** No raw sensitive value survived; every direct identifier was removed as planned.
- **Still re-identifiable: 0% — strong.** After scrubbing, no record can be singled out by the traits left behind.
- **Data properties retained: 25%** across the 5889 values the policy rewrote. This is a **structural** measure, not a judgement about your analysis: it counts how many useful properties survived in the scrubbed values, nothing more. Whether that is enough depends entirely on what you plan to do with the data.
  - Retained by kind of data: financial data 50%, direct identifier 49%, quasi identifier 7%, sensitive attribute 5%, neutral 1%, genetic data 1%

  *The three properties checked on each rewritten value: can it still be read (weight 0.2); can two different originals still be told apart, which is what joining and counting need (0.5); does it keep its original shape and format (0.3). Masking to `[EMAIL]` destroys all three, so a fully masked field retains 0%. A realistic fake value keeps the last two. Only these weights are a judgement call — the three checks are measured on the real output.*

  *Scope: measured only on the values the policy rewrote. Untouched columns and surrounding text are unaffected and are not in this number.*

> Safety and usefulness pull against each other. Today the policy you picked fixes both numbers; choosing a gentler action per field is what a future optimizer will search for.

## Exposure before vs after de-identification

The whole point of applying a policy. Every finding was re-scored against what the scrub actually left behind — a blanked value carries no risk, a coarsened one carries only what its remaining precision is worth, a fake-but-realistic value carries a little because records can still be linked.

### 46.9 → 0.0 out of 100 — nearly all exposure removed

| Severity | Findings before | Findings after |
|---|---|---|
| critical | 2777 | 0 |
| high | 29 | 0 |
| medium | 2860 | 0 |
| low | 223 | 1 |
| info | 0 | 5888 |

> This is exposure remaining in the **scrubbed** copy. The original data is unchanged and still carries the number on the left.

## What the optimizer chose, and why

You asked for actions to be chosen automatically rather than taken from the policy profile. Each entity below was given the least destructive action that still met the privacy target; anything not listed was left as configured.

**Reading this table**

- **Data type** — the kind of data the decision applies to
- **Action chosen** — what will be done to every value of that type
- **Why** — the reason this action was picked over a gentler or harsher one

| Data type | Action chosen | Why |
|---|---|---|
| age | `mask` | combines with other fields to single people out; mask reaches k=32 (target 5) |
| bank_account_number | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| certificate_license_number | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| city | `mask` | combines with other fields to single people out; mask reaches k=32 (target 5) |
| claim_control_number | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| county | `mask` | combines with other fields to single people out; mask reaches k=32 (target 5) |
| credit_card_number | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| date_of_birth | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| date_of_death | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| dates | `mask` | combines with other fields to single people out; mask reaches k=32 (target 5) |
| imei_number | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| indian_aadhaar_number | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| latitude_coordinates | `generalize:integer` | combines with other fields to single people out; generalize:integer reaches k=32 (target 5) |
| longitude_coordinates | `mask` | combines with other fields to single people out; mask reaches k=32 (target 5) |
| medical_record_number_mrn | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| organization | `mask` | combines with other fields to single people out; mask reaches k=32 (target 5) |
| payment_transaction_id | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| person_names | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| phone_number | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| ssn | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| state | `mask` | combines with other fields to single people out; mask reaches k=32 (target 5) |
| street_address | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| timestamps | `mask` | combines with other fields to single people out; mask reaches k=32 (target 5) |
| unique_identifier | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| us_itin | `hash` | identifies a person outright, so the raw value cannot survive; hashed, which hides it but keeps records joinable |
| zip_code | `mask` | combines with other fields to single people out; mask reaches k=32 (target 5) |

Reached a smallest crowd size of **k=32** after testing 51199 combinations. Combinations that could only be more destructive than one already known to work were skipped rather than measured.

## Human approval flagged entities

**1730 findings, 1722 distinct.** These are severe findings the scanner is **not confident** about, queued for a person to confirm or reject. Severity and confidence are separate: a name is just as sensitive whether we are 50% or 99% sure it is a name — so these are never downgraded, only flagged.

**Reading this table**

- **Location** — the exact cell — column and row number — to open
- **Text found** — the actual value that needs a human decision
- **Why flagged** — `low_confidence` = the detector was unsure. `rescue` = surrounding words rescued a weak match — usually right, but worth a look
- **Times** — how many times this exact value appeared in this location

| Severity | Location | Data type | Text found | Why flagged | Times |
|---|---|---|---|---|---|
| critical | adv_02_care_team_roster.txt | person_names | `0700` | rescue | 3 |
| critical | adv_02_care_team_roster.txt | person_names | `MD` | low_confidence | 3 |
| critical | adv_01_neurology_consult.txt | person_names | `Maya Ellison` | low_confidence | 2 |
| critical | adv_03_fax_referral_letter.txt | person_names | `Daniel Ibarra` | low_confidence | 2 |
| critical | adv_06_lab_billing_reconciliation.txt | person_names | `1847392056` | rescue | 2 |
| critical | adv_02_care_team_roster.txt | person_names | `1192837465` | rescue | 2 |
| critical | adv_01_neurology_consult.txt | date_of_birth | `03/14/1978` | rescue | 1 |
| critical | adv_01_neurology_consult.txt | medical_record_number_mrn | `RB-472918` | rescue | 1 |
| critical | adv_01_neurology_consult.txt | person_names | `1467829351` | rescue | 1 |
| critical | adv_03_fax_referral_letter.txt | person_names | `Jefferson Ward` | low_confidence | 1 |
| critical | adv_03_fax_referral_letter.txt | person_names | `Mercy Cummings` | low_confidence | 1 |
| critical | adv_03_fax_referral_letter.txt | date_of_birth | `11/22/1959` | rescue | 1 |
| critical | adv_03_fax_referral_letter.txt | medical_record_number_mrn | `MRN MC-009418` | low_confidence | 1 |
| critical | adv_03_fax_referral_letter.txt | phone_number | `1548392716` | low_confidence | 1 |
| critical | adv_04_intake_questionnaire.txt | person_names | `Tessa Moreno` | low_confidence | 1 |
| critical | adv_04_intake_questionnaire.txt | date_of_birth | `07/09/1986` | rescue | 1 |
| critical | adv_04_intake_questionnaire.txt | unique_identifier | `HL-77294018` | low_confidence | 1 |
| critical | adv_04_intake_questionnaire.txt | person_names | `Patricia Moreno` | low_confidence | 1 |
| critical | adv_04_intake_questionnaire.txt | person_names | `Gabriel Moreno` | low_confidence | 1 |
| critical | adv_04_intake_questionnaire.txt | person_names | `Nina Moreno` | low_confidence | 1 |
| critical | adv_04_intake_questionnaire.txt | person_names | `Rosa Alvarez` | low_confidence | 1 |
| critical | adv_04_intake_questionnaire.txt | person_names | `1629384750` | rescue | 1 |
| critical | adv_05_elderly_discharge_summary.txt | person_names | `Harold Bennett` | low_confidence | 1 |
| critical | adv_05_elderly_discharge_summary.txt | date_of_birth | `01/25/1932` | rescue | 1 |
| critical | adv_05_elderly_discharge_summary.txt | medical_record_number_mrn | `GO-881274` | rescue | 1 |

*…and 1697 more distinct items.*

## Worked example: how one score was reached

Nothing in this report is a black box. Below is the **highest-scoring finding in this dataset**, opened up step by step, so you can see exactly how a score is built: it starts from the kind of data, then rises for identifiers stacked in the same record and for that record being unique. Every finding carries a trace like this — this is one example, not a special case.

`1200 Harbor Avenue, Suite 410` — **street_address**, scored **0.96** (critical).

**Reading this table**

- **Stage** — which rule fired — `sensitivity` sets the starting score, `cooccurrence` and `reid` raise it, `compliance` only tags regulations
- **What happened** — the rule in plain words
- **Value** — how much that rule moved the score. `—` means it tagged or flagged something without changing the number

| Stage | What happened | Value |
|---|---|---|
| sensitivity | data_class direct_identifier -> severity 0.90 | 0.90 |
| confidence | confidence 0.65 - routes review only, not part of severity | — |
| compliance | category PII -> GDPR, CCPA | — |
| compliance | declared health data, so this Safe Harbor identifier is HIPAA-regulated here | — |
| cooccurrence | 5 strong identifier types stacked in one record: closes 45% of the gap to 1.0 | 0.45 |
| reid | record is unique on age, amt_1, amt_2, amt_3, birthplace, c_2, city, comments, county, coverage, date_of_birth, date_of_death, dates, dob, dt_2, dt_9, expenses, fips, income, latitude, loc_0, loc_1, loc_2, loc_3, longitude, num_7, organization, pcode, state, suffix, timestamps, zip_cd, zip_code (k=1): closes 20% of the gap to 1.0 | 0.20 |

## Policy plan (what was done to each finding)

The action taken on every finding, decided by the chosen rulebook. The action comes from the **kind of data** — its OpenMed label, or failing that its data class — **not** from its severity score, and not from any optimization: nothing here searches for a gentler action that would keep more value. That search is a planned feature; today the profile you pick decides everything.

OpenMed profile **`hipaa_safe_harbor`** — executed (values rewritten).

- Exact label lookups (`action_for`): **250**
- Class fallback (`policy_label_actions` via seiba `data_class`): **184**
- Neutral / missing → keep: **1**

**Action histogram**

| Action | Findings |
|---|---|
| hash | 2699 |
| keep | 1 |
| mask | 3189 |

**Sample action records**

**Reading this table**

- **Entity** — the kind of data being acted on
- **OpenMed label** — what that maps to in OpenMed's vocabulary — this is what the rulebook looks up
- **Policy class** — the fallback bucket used when there is no exact label match
- **Action** — `mask` blanks the value out, `replace` swaps in a realistic fake, `hash` turns it into a stable token, `generalize` coarsens it (a date to its year, a zip to its region) so it stays usable, `keep` leaves it alone
- **Replacement** — the value actually written in its place

| Entity | OpenMed label | Policy class | Action | Source | Execute fallback | Replacement |
|---|---|---|---|---|---|---|
| organization | ORGANIZATION | — | mask | seiba_action_override | — | [ORGANIZATION] |
| street_address | STREET_ADDRESS | — | hash | seiba_action_override | — | STREET_ADDRESS_54b46fe3 |
| city | LOCATION | — | mask | seiba_action_override | — | [LOCATION] |
| state | LOCATION | — | mask | seiba_action_override | — | [LOCATION] |
| zip_code | ZIPCODE | — | mask | seiba_action_override | — | [ZIPCODE] |
| phone_number | PHONE | — | hash | seiba_action_override | — | PHONE_ee84ec5b |
| phone_number | PHONE | — | hash | seiba_action_override | — | PHONE_60b6ab0d |
| dates | DATE | — | mask | seiba_action_override | — | [DATE] |
| person_names | PERSON | — | hash | seiba_action_override | — | PERSON_815fd9a3 |
| date_of_birth | DATE_OF_BIRTH | — | hash | seiba_action_override | — | DATE_OF_BIRTH_64be4a7b |
| medical_record_number_mrn | ID_NUM | — | hash | seiba_action_override | — | ID_NUM_84bc14b5 |
| person_names | PERSON | — | hash | seiba_action_override | — | PERSON_c7fb6b99 |
| person_names | PERSON | — | hash | seiba_action_override | — | PERSON_815fd9a3 |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| person_names | PERSON | — | hash | seiba_action_override | — | PERSON_c7fb6b99 |

*Showing 20 of 5889. All 5889 action records — with the full rule trace behind every finding — are in `corpus_risk.json`.*
