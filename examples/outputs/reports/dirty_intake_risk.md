# Sensitive Data Risk Report

*Scope: 1 source(s): dirty_intake.csv.*

## Exposure index

# 80.7 / 100

**0 means nothing sensitive was found. 100 means maximally exposed.**

This is *not* a pass/fail grade. Whether this level of exposure is acceptable depends on what the data is for — a clinical registry is supposed to hold patient names. Use it to compare datasets, or to track one dataset over time.

**How it was calculated**

- **84%** of findings are high or critical severity
- **93%** of the 200 records are re-identifiable (fewer than 5 records share their combination of traits)

*(method: severity_x_uniqueness)*

## At a glance

The size of the job: how much sensitive data was found, and where.

|  | Count |
|---|---|
| Findings | 1293 |
| Locations with findings | 7 |
| Records scanned | 200 |
| Findings needing human review | 695 |

**Reading this table**

- **Finding** — one sensitive value found in one cell. A table of 40 rows with 11 sensitive columns gives 440 findings, not 40
- **Location** — the column a finding sat in
- **Record** — one table row, i.e. one person's worth of data

## Severity of what was found

Severity = how bad this would be if exposed. It starts from the *kind* of data, then rises when several identifiers sit together in one record, or when that record is unique in the dataset. It does **not** depend on how confident the scanner is.

| Severity | Findings | What it means |
|---|---|---|
| critical | 1078 | Names a specific person outright |
| high | 2 | Harmful on its own — a direct, financial, or health identifier |
| medium | 213 | Harmless alone, but narrows down who someone is when combined with other fields |

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
| comments | 100 | 1 | 27 |  |  |
| zip_cd |  |  | 185 |  |  |

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
| person_names | 313 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| phone_number | 208 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| date_of_birth | 206 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| medical_record_number_mrn | 206 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| zip_code | 189 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| ssn | 125 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| dates | 15 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| us_itin | 11 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| bank_account_number | 5 | critical | 0.93 | — | CCPA, GDPR, HIPAA |
| timestamps | 5 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| street_address | 4 | critical | 0.96 | — | CCPA, GDPR, HIPAA |
| city | 3 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| medical_condition | 1 | high | 0.91 | — | CCPA, GDPR, HIPAA |
| state | 1 | medium | 0.55 | — | CCPA, GDPR |
| unique_identifier | 1 | critical | 0.95 | — | CCPA, GDPR, HIPAA |

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
| dirty_intake.csv row 13 | 6 | 0.91 | 7.2 | 8 | critical | yes |
| dirty_intake.csv row 137 | 6 | 0.90 | 7.2 | 8 | critical | yes |
| dirty_intake.csv row 79 | 6 | 0.90 | 7.2 | 8 | critical | yes |
| dirty_intake.csv row 9 | 6 | 0.90 | 7.2 | 8 | critical | yes |
| dirty_intake.csv row 37 | 6 | 0.89 | 6.3 | 7 | critical | yes |
| dirty_intake.csv row 4 | 6 | 0.89 | 6.3 | 7 | critical | yes |
| dirty_intake.csv row 20 | 6 | 0.85 | 6.8 | 8 | critical | yes |
| dirty_intake.csv row 122 | 6 | 0.82 | 7.4 | 9 | critical | yes |
| dirty_intake.csv row 187 | 5 | 0.95 | 4.7 | 5 | critical | no |
| dirty_intake.csv row 43 | 5 | 0.95 | 4.7 | 5 | critical | no |

## HIPAA Safe Harbor checklist

HIPAA lists 18 categories of identifier that must be removed for health data to count as de-identified. This is which of the 18 appear in your data.

| Identifier category present | Findings | Found as |
|---|---|---|
| names | 313 | person_names |
| geographic subdivision | 196 | city, street_address, zip_code |
| dates | 226 | date_of_birth, dates, timestamps |
| telephone | 208 | phone_number |
| ssn | 125 | ssn |
| medical record number | 206 | medical_record_number_mrn |
| account number | 5 | bank_account_number |
| other unique id | 12 | unique_identifier, us_itin |

**Not found (10 of 18):** fax, email, health plan beneficiary number, certificate license number, vehicle identifier, device identifier, url, ip address, biometric identifier, full face photo

> HIPAA is tagged below because this dataset was identified as health data.

> A category being absent means the scanner found none — not that none exist. Some categories can only be detected when they appear as text: photographs and fingerprint scans cannot be, while genetic sequences can.

## Regulatory exposure

Which rulebooks this data falls under, and how much of it each one covers.

**Reading this table**

- **Findings subject to it** — how many of the findings above that regulation treats as regulated data. One finding can count under several regulations at once, so these columns overlap and will not add up to the total
- **Worst severity** — the most severe finding in that regulation's scope

| Regulation | Findings subject to it | Worst severity |
|---|---|---|
| CCPA | 1293 | critical |
| GDPR | 1293 | critical |
| HIPAA | 1292 | critical |

> **These are counts, not scores** — a bigger number is not automatically worse, it just reflects how much data of that kind is present.

> **How the mapping is decided — and how far to trust it.** This is decided by this scanner's own ontology, not by OpenMed, using one deliberately simple rule: any data type not marked *neutral* counts as personal data (GDPR + CCPA); a type classified as health data adds HIPAA; a financial instrument adds PCI.

> **Reliable:** *is this personal data at all* — that follows directly from the data type and is dependable. **Not reliable:** *which jurisdiction applies to you*. The rule tags GDPR and CCPA on every personal-data finding regardless of whether your subjects are EU or California residents, or whether your business meets CCPA's thresholds. Read the counts as **"this much data would be in scope if that law applies to you"**, not as a finding that it does. **Not legal advice** — a lawyer confirms which regimes bind you.

## Re-identification risk of individuals

Could someone work out *who* a record belongs to, even after the obvious identifiers (name, email) are taken away — just by combining ordinary-looking fields like city, zip code and visit date? This measures the data **as scanned, before any scrubbing**.

### 93% of records can be singled out — **CRITICAL**

- **176 of 189 records** sit below the k=5 bar used to call data de-identified.
- **176** are completely one of a kind (nobody else matches them at all).
- **Smallest crowd size (k) = 1.**
- Compared on these traits: **comments, dob, zip_cd**
- Values that would be exposed: **comments**

**What k means.** k is the size of the crowd a person hides in: how many records share their exact combination of the traits above. k=1 means that person matches nobody else and can be picked out; k=5 or more is the usual bar for calling data de-identified. Higher k = safer.

> These numbers are only as good as the traits listed above. Comparing on one weak field makes data look safer than it really is.

## De-identification strength (what the scrub left behind)

The policy was applied, then the scrubbed data was compared back against the original. The first numbers say how *safe* the result is (lower is better); the last says how much of the data's structure survived (higher is better).

- **Residue left behind: 0% — clean.** No raw sensitive value survived; every direct identifier was removed as planned.
- **Still re-identifiable: 0% — strong.** After scrubbing, no record can be singled out by the traits left behind.
- **Data properties retained: 1%** across the 1293 values the policy rewrote. This is a **structural** measure, not a judgement about your analysis: it counts how many useful properties survived in the scrubbed values, nothing more. Whether that is enough depends entirely on what you plan to do with the data.
  - Retained by kind of data: sensitive attribute 6%, financial data 6%, direct identifier 1%, quasi identifier 1%

  *The three properties checked on each rewritten value: can it still be read (weight 0.2); can two different originals still be told apart, which is what joining and counting need (0.5); does it keep its original shape and format (0.3). Masking to `[EMAIL]` destroys all three, so a fully masked field retains 0%. A realistic fake value keeps the last two. Only these weights are a judgement call — the three checks are measured on the real output.*

  *Scope: measured only on the values the policy rewrote. Untouched columns and surrounding text are unaffected and are not in this number.*

> Safety and usefulness pull against each other. Today the policy you picked fixes both numbers; choosing a gentler action per field is what a future optimizer will search for.

## Exposure before vs after de-identification

The whole point of applying a policy. Every finding was re-scored against what the scrub actually left behind — a blanked value carries no risk, a coarsened one carries only what its remaining precision is worth, a fake-but-realistic value carries a little because records can still be linked.

### 80.7 → 0.0 out of 100 — nearly all exposure removed

| Severity | Findings before | Findings after |
|---|---|---|
| critical | 1078 | 0 |
| high | 2 | 0 |
| medium | 213 | 0 |
| info | 0 | 1293 |

> This is exposure remaining in the **scrubbed** copy. The original data is unchanged and still carries the number on the left.

## Human approval flagged entities

**695 findings, 695 distinct.** These are severe findings the scanner is **not confident** about, queued for a person to confirm or reject. Severity and confidence are separate: a name is just as sensitive whether we are 50% or 99% sure it is a name — so these are never downgraded, only flagged.

**Reading this table**

- **Location** — the exact cell — column and row number — to open
- **Text found** — the actual value that needs a human decision
- **Why flagged** — `low_confidence` = the detector was unsure. `rescue` = surrounding words rescued a weak match — usually right, but worth a look
- **Times** — how many times this exact value appeared in this location

| Severity | Location | Data type | Text found | Why flagged | Times |
|---|---|---|---|---|---|
| critical | mrn (row 1) | medical_record_number_mrn | `0012346` | rescue | 1 |
| critical | mrn (row 3) | medical_record_number_mrn | `A-12348` | rescue | 1 |
| critical | mrn (row 4) | medical_record_number_mrn | `12349` | rescue | 1 |
| critical | mrn (row 6) | medical_record_number_mrn | `0012351` | rescue | 1 |
| critical | mrn (row 8) | medical_record_number_mrn | `A-12353` | rescue | 1 |
| critical | mrn (row 9) | medical_record_number_mrn | `12354` | rescue | 1 |
| critical | mrn (row 11) | medical_record_number_mrn | `0012356` | rescue | 1 |
| critical | mrn (row 13) | medical_record_number_mrn | `A-12358` | rescue | 1 |
| critical | mrn (row 14) | medical_record_number_mrn | `12359` | rescue | 1 |
| critical | mrn (row 16) | medical_record_number_mrn | `0012361` | rescue | 1 |
| critical | mrn (row 18) | medical_record_number_mrn | `A-12363` | rescue | 1 |
| critical | mrn (row 19) | medical_record_number_mrn | `12364` | rescue | 1 |
| critical | mrn (row 23) | medical_record_number_mrn | `A-12368` | rescue | 1 |
| critical | mrn (row 24) | medical_record_number_mrn | `12369` | rescue | 1 |
| critical | mrn (row 26) | medical_record_number_mrn | `0012371` | rescue | 1 |
| critical | mrn (row 28) | medical_record_number_mrn | `A-12373` | rescue | 1 |
| critical | mrn (row 29) | medical_record_number_mrn | `12374` | rescue | 1 |
| critical | mrn (row 31) | medical_record_number_mrn | `0012376` | rescue | 1 |
| critical | mrn (row 33) | medical_record_number_mrn | `A-12378` | rescue | 1 |
| critical | mrn (row 34) | medical_record_number_mrn | `12379` | rescue | 1 |
| critical | mrn (row 36) | medical_record_number_mrn | `0012381` | rescue | 1 |
| critical | mrn (row 38) | medical_record_number_mrn | `A-12383` | rescue | 1 |
| critical | mrn (row 39) | medical_record_number_mrn | `12384` | rescue | 1 |
| critical | mrn (row 44) | medical_record_number_mrn | `12389` | rescue | 1 |
| critical | mrn (row 46) | medical_record_number_mrn | `0012391` | rescue | 1 |

*…and 670 more distinct items.*

## Worked example: how one score was reached

Nothing in this report is a black box. Below is the **highest-scoring finding in this dataset**, opened up step by step, so you can see exactly how a score is built: it starts from the kind of data, then rises for identifiers stacked in the same record and for that record being unique. Every finding carries a trace like this — this is one example, not a special case.

`0012346` — **medical_record_number_mrn**, scored **0.96** (critical).

**Reading this table**

- **Stage** — which rule fired — `sensitivity` sets the starting score, `cooccurrence` and `reid` raise it, `compliance` only tags regulations
- **What happened** — the rule in plain words
- **Value** — how much that rule moved the score. `—` means it tagged or flagged something without changing the number

| Stage | What happened | Value |
|---|---|---|
| sensitivity | data_class direct_identifier -> severity 0.90 | 0.90 |
| confidence | confidence 0.93 - routes review only, not part of severity | — |
| compliance | category PHI -> HIPAA, GDPR, CCPA | — |
| escalation | high severity with rescue - needs a human | — |
| cooccurrence | 4 strong identifier types stacked in one record: closes 45% of the gap to 1.0 | 0.45 |
| reid | record is unique on comments, dob, zip_cd (k=1): closes 20% of the gap to 1.0 | 0.20 |

## Policy plan (what was done to each finding)

The action taken on every finding, decided by the chosen rulebook. The action comes from the **kind of data** — its OpenMed label, or failing that its data class — **not** from its severity score, and not from any optimization: nothing here searches for a gentler action that would keep more value. That search is a planned feature; today the profile you pick decides everything.

OpenMed profile **`hipaa_safe_harbor`** — executed (values rewritten).

- Exact label lookups (`action_for`): **1282**
- Class fallback (`policy_label_actions` via seiba `data_class`): **11**
- Neutral / missing → keep: **0**

**Action histogram**

| Action | Findings |
|---|---|
| mask | 1293 |

**Sample action records**

**Reading this table**

- **Entity** — the kind of data being acted on
- **OpenMed label** — what that maps to in OpenMed's vocabulary — this is what the rulebook looks up
- **Policy class** — the fallback bucket used when there is no exact label match
- **Action** — `mask` blanks the value out, `replace` swaps in a realistic fake, `hash` turns it into a stable token, `generalize` coarsens it (a date to its year, a zip to its region) so it stays usable, `keep` leaves it alone
- **Replacement** — the value actually written in its place

| Entity | OpenMed label | Policy class | Action | Source | Execute fallback | Replacement |
|---|---|---|---|---|---|---|
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |

*Showing 20 of 1293. All 1293 action records — with the full rule trace behind every finding — are in `dirty_intake_risk.json`.*
