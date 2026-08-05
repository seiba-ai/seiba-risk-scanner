# Sensitive Data Risk Report

*Scope: 1 source(s): adv_01_neurology_consult.txt.*

## Exposure index

# 63.0 / 100

**0 means nothing sensitive was found. 100 means maximally exposed.**

This is *not* a pass/fail grade. Whether this level of exposure is acceptable depends on what the data is for — a clinical registry is supposed to hold patient names. Use it to compare datasets, or to track one dataset over time.

**How it was calculated**

- **63%** of findings are high or critical severity
- Re-identifiability was **not measured**: 1 record(s) scanned, below the minimum of 10 needed to tell whether anyone actually stands out.

*(method: severity_only)*

## At a glance

The size of the job: how much sensitive data was found, and where.

|  | Count |
|---|---|
| Findings | 27 |
| Locations with findings | 1 |
| Records scanned | 1 |
| Findings needing human review | 5 |

**Reading this table**

- **Finding** — one sensitive value found in one place. One document mentioning the same patient's name 12 times gives 12 findings, not 1
- **Location** — the document a finding came from
- **Record** — one whole document — documents are counted as one record each, since each is treated as one person's worth of data

## Severity of what was found

Severity = how bad this would be if exposed. It starts from the *kind* of data, then rises when several identifiers sit together in one record, or when that record is unique in the dataset. It does **not** depend on how confident the scanner is.

| Severity | Findings | What it means |
|---|---|---|
| critical | 11 | Names a specific person outright |
| high | 6 | Harmful on its own — a direct, financial, or health identifier |
| medium | 10 | Harmless alone, but narrows down who someone is when combined with other fields |

## Where the risk is

Which columns (or documents) the sensitive data actually sits in — so you know where to act first.

**Reading this table**

- **Location** — one document
- **The number** — how many **findings** of that severity sat there — not how many documents. One document can hold hundreds of findings
- **Blank** — none of that severity here

| Location | critical | high | medium | low | info |
|---|---|---|---|---|---|
| adv_01_neurology_consult.txt | 11 | 6 | 10 |  |  |

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
| medical_condition | 6 | high | 0.89 | — | CCPA, GDPR, HIPAA |
| person_names | 5 | critical | 0.95 | physician_names (1) | CCPA, GDPR, HIPAA |
| city | 2 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| dates | 2 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| organization | 2 | medium | 0.55 | hospital_names (2) | CCPA, GDPR |
| phone_number | 2 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| state | 2 | medium | 0.55 | — | CCPA, GDPR |
| street_address | 2 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| zip_code | 2 | medium | 0.55 | — | CCPA, GDPR, HIPAA |
| date_of_birth | 1 | critical | 0.95 | — | CCPA, GDPR, HIPAA |
| medical_record_number_mrn | 1 | critical | 0.95 | — | CCPA, GDPR, HIPAA |

## Riskiest records

The individual people (rows, or documents) most exposed by this dataset. Ranked by how *concentrated* the risk is, not how much text there is — otherwise the longest document would always win on volume alone. Showing the top 10; in a uniform table every row holds the same columns, so many rows tie on an identical score.

**Reading this table**

- **Record** — one document
- **Composite identifier types** — how many **different kinds** of strong identifier sit together here (name + SSN + email = 3). Ten names still count as one, because ten names pin down a person no better than one does. This is the main ranking: identifiers stacking up is what makes a record dangerous
- **Avg severity** — average severity of this record's findings, 0–1
- **Total risk** — those severity scores added up (11 findings averaging 0.73 = 8.1). It grows with size, so use it to compare records of similar length — it is deliberately **not** what ranks this table
- **Findings** — every sensitive value in the record, weak ones included. Always ≥ composite identifier types, which counts only distinct strong kinds
- **Unique** — **`yes` is bad** — nobody else shares this record's combination of traits, so this person can be picked out of the crowd. `no` is safer: they blend in with at least one other record

| Record | Composite identifier types | Avg severity | Total risk | Findings | Worst severity | Unique |
|---|---|---|---|---|---|---|
| adv_01_neurology_consult.txt | 5 | 0.79 | 21.2 | 27 | critical | no |

## HIPAA Safe Harbor checklist

HIPAA lists 18 categories of identifier that must be removed for health data to count as de-identified. This is which of the 18 appear in your data.

| Identifier category present | Findings | Found as |
|---|---|---|
| names | 5 | person_names |
| geographic subdivision | 6 | city, street_address, zip_code |
| dates | 3 | date_of_birth, dates |
| telephone | 2 | phone_number |
| medical record number | 1 | medical_record_number_mrn |

**Not found (13 of 18):** fax, email, ssn, health plan beneficiary number, account number, certificate license number, vehicle identifier, device identifier, url, ip address, biometric identifier, full face photo, other unique id

> HIPAA is tagged below because this dataset was identified as health data.

> A category being absent means the scanner found none — not that none exist. Some categories can only be detected when they appear as text: photographs and fingerprint scans cannot be, while genetic sequences can.

## Regulatory exposure

Which rulebooks this data falls under, and how much of it each one covers.

**Reading this table**

- **Findings subject to it** — how many of the findings above that regulation treats as regulated data. One finding can count under several regulations at once, so these columns overlap and will not add up to the total
- **Worst severity** — the most severe finding in that regulation's scope

| Regulation | Findings subject to it | Worst severity |
|---|---|---|
| CCPA | 27 | critical |
| GDPR | 27 | critical |
| HIPAA | 23 | critical |

> **These are counts, not scores** — a bigger number is not automatically worse, it just reflects how much data of that kind is present.

> **How the mapping is decided — and how far to trust it.** This is decided by this scanner's own ontology, not by OpenMed, using one deliberately simple rule: any data type not marked *neutral* counts as personal data (GDPR + CCPA); a type classified as health data adds HIPAA; a financial instrument adds PCI.

> **Reliable:** *is this personal data at all* — that follows directly from the data type and is dependable. **Not reliable:** *which jurisdiction applies to you*. The rule tags GDPR and CCPA on every personal-data finding regardless of whether your subjects are EU or California residents, or whether your business meets CCPA's thresholds. Read the counts as **"this much data would be in scope if that law applies to you"**, not as a finding that it does. **Not legal advice** — a lawyer confirms which regimes bind you.

## Re-identification risk of individuals

Could someone work out *who* a record belongs to, even after the obvious identifiers (name, email) are taken away — just by combining ordinary-looking fields like city, zip code and visit date? This measures the data **as scanned, before any scrubbing**.

**Not measured.** Re-identifiability is a comparison *between* records — you need a crowd before you can ask whether someone stands out in it. 1 record(s) were scanned, below the minimum of 10, so no honest number can be given.

## De-identification strength (what the scrub left behind)

The policy was applied, then the scrubbed data was compared back against the original. The first numbers say how *safe* the result is (lower is better); the last says how much of the data's structure survived (higher is better).

- **Data properties retained: 31%** across the 27 values the policy rewrote. This is a **structural** measure, not a judgement about your analysis: it counts how many useful properties survived in the scrubbed values, nothing more. Whether that is enough depends entirely on what you plan to do with the data.
  - Retained by kind of data: quasi identifier 45%, direct identifier 30%, sensitive attribute 8%

  *The three properties checked on each rewritten value: can it still be read (weight 0.2); can two different originals still be told apart, which is what joining and counting need (0.5); does it keep its original shape and format (0.3). Masking to `[EMAIL]` destroys all three, so a fully masked field retains 0%. A realistic fake value keeps the last two. Only these weights are a judgement call — the three checks are measured on the real output.*

  *Scope: measured only on the values the policy rewrote. Untouched columns and surrounding text are unaffected and are not in this number.*

> Safety and usefulness pull against each other. Today the policy you picked fixes both numbers; choosing a gentler action per field is what a future optimizer will search for.

## Exposure before vs after de-identification

The whole point of applying a policy. Every finding was re-scored against what the scrub actually left behind — a blanked value carries no risk, a coarsened one carries only what its remaining precision is worth, a fake-but-realistic value carries a little because records can still be linked.

### 63.0 → 0.0 out of 100 — nearly all exposure removed

| Severity | Findings before | Findings after |
|---|---|---|
| critical | 11 | 0 |
| high | 6 | 0 |
| medium | 10 | 0 |
| info | 0 | 27 |

> This is exposure remaining in the **scrubbed** copy. The original data is unchanged and still carries the number on the left.

## Human approval flagged entities

**5 findings, 4 distinct.** These are severe findings the scanner is **not confident** about, queued for a person to confirm or reject. Severity and confidence are separate: a name is just as sensitive whether we are 50% or 99% sure it is a name — so these are never downgraded, only flagged.

**Reading this table**

- **Location** — the file this value was found in
- **Text found** — the actual value that needs a human decision
- **Why flagged** — `low_confidence` = the detector was unsure. `rescue` = surrounding words rescued a weak match — usually right, but worth a look
- **Times** — how many times this exact value appeared in this location

| Severity | Location | Data type | Text found | Why flagged | Times |
|---|---|---|---|---|---|
| critical | adv_01_neurology_consult.txt | person_names | `Maya Ellison` | low_confidence | 2 |
| critical | adv_01_neurology_consult.txt | date_of_birth | `03/14/1978` | rescue | 1 |
| critical | adv_01_neurology_consult.txt | medical_record_number_mrn | `RB-472918` | rescue | 1 |
| critical | adv_01_neurology_consult.txt | person_names | `1467829351` | rescue | 1 |

## Worked example: how one score was reached

Nothing in this report is a black box. Below is the **highest-scoring finding in this dataset**, opened up step by step, so you can see exactly how a score is built: it starts from the kind of data, then rises for identifiers stacked in the same record and for that record being unique. Every finding carries a trace like this — this is one example, not a special case.

`1200 Harbor Avenue, Suite 410` — **street_address**, scored **0.95** (critical).

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

## Policy plan (what was done to each finding)

The action taken on every finding, decided by the chosen rulebook. The action comes from the **kind of data** — its OpenMed label, or failing that its data class — **not** from its severity score, and not from any optimization: nothing here searches for a gentler action that would keep more value. That search is a planned feature; today the profile you pick decides everything.

OpenMed profile **`hipaa_safe_harbor`** — executed (values rewritten).

- Exact label lookups (`action_for`): **27**
- Class fallback (`policy_label_actions` via seiba `data_class`): **0**
- Neutral / missing → keep: **0**

**Action histogram**

| Action | Findings |
|---|---|
| mask | 27 |

**Sample action records**

**Reading this table**

- **Entity** — the kind of data being acted on
- **OpenMed label** — what that maps to in OpenMed's vocabulary — this is what the rulebook looks up
- **Policy class** — the fallback bucket used when there is no exact label match
- **Action** — `mask` blanks the value out, `replace` swaps in a realistic fake, `hash` turns it into a stable token, `generalize` coarsens it (a date to its year, a zip to its region) so it stays usable, `keep` leaves it alone
- **Replacement** — the value actually written in its place

| Entity | OpenMed label | Policy class | Action | Source | Execute fallback | Replacement |
|---|---|---|---|---|---|---|
| organization | ORGANIZATION | — | mask | openmed_action_for | — | [ORGANIZATION] |
| street_address | STREET_ADDRESS | — | mask | openmed_action_for | — | [STREET_ADDRESS] |
| city | LOCATION | — | mask | openmed_action_for | — | [LOCATION] |
| state | LOCATION | — | mask | openmed_action_for | — | [LOCATION] |
| zip_code | ZIPCODE | — | mask | openmed_action_for | — | [ZIPCODE] |
| phone_number | PHONE | — | mask | openmed_action_for | — | [PHONE] |
| phone_number | PHONE | — | mask | openmed_action_for | — | [PHONE] |
| dates | DATE | — | mask | openmed_action_for | — | [DATE] |
| person_names | PERSON | — | mask | openmed_action_for | — | [PERSON] |
| date_of_birth | DATE_OF_BIRTH | — | mask | openmed_action_for | — | [DATE_OF_BIRTH] |
| medical_record_number_mrn | ID_NUM | — | mask | openmed_action_for | — | [ID_NUM] |
| person_names | PERSON | — | mask | openmed_action_for | — | [PERSON] |
| person_names | PERSON | — | mask | openmed_action_for | — | [PERSON] |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| medical_condition | CONDITION | — | mask | openmed_action_for | — | [CONDITION] |
| person_names | PERSON | — | mask | openmed_action_for | — | [PERSON] |

*Showing 20 of 27. All 27 action records — with the full rule trace behind every finding — are in `adv_01_neurology_consult_risk.json`.*
