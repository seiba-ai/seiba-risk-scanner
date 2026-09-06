# Task backlog

Deferred work with the evidence attached, so a future reader does not have to
re-derive why it is on the list. Nothing here is in progress.

---

## Column-key resolution — found 2026-09-05, not fixed

Found while integrating the SDK into seiba-assess, by running the scanner over the
**real Synthea `patients` table** (111 rows, 28 columns) rather than the gold corpus.
Four of fifteen typed columns came out wrong, and the gold corpus catches none of it
because it has no column named `RACE`, `SUFFIX` or `PASSPORT`.

`_decisive_key_entities` resolves a column name to the one entity it decisively
names, and returns `None` on ambiguity so NER stays on. That rule is right in
principle and misfires in two specific ways.

### 1 · `LAST` resolves to `credit_card_number` — the worst of these

```
_decisive_key_entities(["LAST"]) -> fin_entity_ontology::credit_card_number
```

"last" is a contextual phrase on credit cards ("last 4 digits"), so a **surname
column decisively resolves to a payment entity**. It did not surface as a wrong
label on Synthea only because NER outvoted it — the mechanism is pointing the wrong
way regardless, and on a table with weaker name signal it would win.

The generic-token stoplist (`_GENERIC_KEY_TOKENS`) already exists for exactly this
problem but holds only structural words (`name`, `number`, `code`, `id`, …). Tokens
that are generic *English* rather than generic *structure* — `last`, `first`,
`middle` — are not in it.

### 2 · A well-named column loses key evidence because the ontology is too fine

```
_decisive_key_entities(["PASSPORT"]) -> None    # 7 candidates, so ambiguous
```

Seven entities carry the token: `passport_number`, `us_`, `uk_`, `canadian_`,
`indian_`, `australian_`, `german_`. The ambiguity rule fires, key evidence is
dropped, NER decides — and on Synthea's `X60183820X` values it returned
**`genomic_variants`**, which is `genetic_data` and scores 0.90.

The variants are all *kinds of* one thing. Ambiguity among members of one family
should collapse to the parent (`passport_number`), not to `None`. `is_a` links
already exist in the ontology; this rule does not consult them.

### 3 · Vocabulary gaps, lower priority

`RACE`, `SUFFIX`, `FIRST`, `ADDRESS`, `BIRTHPLACE` resolve to nothing, so NER decides
unaided:

- `RACE` (`white`, `black`, `asian`, `hawaiian`) → `person_names`
- `SUFFIX` (`MD`, `JD`) → `state` — **`MD` is Maryland**, genuine two-letter ambiguity

`ADDRESS` and `BIRTHPLACE` happened to come out right, but by NER alone.

### Not a defect: `SSN` → `us_itin`

Worth recording so nobody "fixes" it. Synthea's SSNs are all `999-xx-xxxx`. Real
SSNs never begin with 9; **ITINs do**. The validator is correct and the fixture is
ITIN-shaped — the same class of problem as the checksum-invalid `provider_npi` gold
fixtures. If this is ever made to report `ssn`, the validator has been weakened.

### What would close this

- [ ] Add generic-English tokens to `_GENERIC_KEY_TOKENS`, or score decisiveness
      rather than treating any single-entity match as decisive.
- [ ] Collapse ambiguity among `is_a` siblings to the parent instead of `None`.
- [ ] Decide whether `race`, `suffix`, `sex`, `ethnicity` earn ontology entries —
      they are quasi-identifiers in their own right, not just unmatched keys.
- [ ] **Add a structured fixture with these column names.** The current structured
      set scores 1.000 and would still score 1.000 with every defect above present.
      That is the real gap: the gate cannot see this class of error at all.

---

## `date_of_birth` is classified `direct_identifier` — reconsider

Raised 2026-09-05 while building k-anonymity in seiba-assess. DOB is a Safe Harbor
identifier, so `direct_identifier` is defensible — but it is also **the** canonical
quasi-identifier: {DOB, ZIP, sex} is the combination every re-identification result
turns on.

Consumers build their k-anonymity grouping key from `data_class ==
quasi_identifier`. With DOB outside that set the key is missing its strongest
member, group sizes come out larger than reality, and **k reads as safer than it
is** — the failure direction that matters for a privacy claim.

The decision (2026-09-05) is to leave the class alone for now and rely on this
ontology as the single mapping, rather than have each consumer keep a private
override list. So the fix belongs here, not downstream.

- [ ] **Decide whether one `data_class` can carry both roles.** Safe Harbor
      category and re-identification role are different axes, and DOB is the case
      that proves it. Options: a second boolean (`quasi_identifying: true`
      alongside `direct_identifier`), or a `roles: [...]` list replacing the single
      class. Whichever, `age` / `dates` / `zip_code` / `city` / `state` / `county` /
      `sex` should come out as the QI set, **plus** DOB.
- [ ] Until then, any k-anonymity built on this ontology under-reports uniqueness.
      Say so wherever it is rendered.

---

## `race_ethnicity` is emitted by the model and dropped

Noticed 2026-09-05 alongside the `sex` addition. The OpenMed PII model emits
`race_ethnicity`, and `openmed_labels.yaml` drops it for want of an entity to map
it to — which is why Synthea's `RACE` column (`white`, `black`, `asian`,
`hawaiian`) comes back as **`person_names`**: with the label dropped, nothing
competes with the NER's name guess.

Race and ethnicity are quasi-identifiers in their own right and a protected
category under several regimes, so this is a real gap rather than a tidy-up.

- [ ] Add a `race_ethnicity` entity (quasi-identifier, likely also a restricted
      category for §9.4) and map the label — the same two-line shape the `sex`
      addition used. `sexuality`, `religious_belief` and `political_view` are also
      emitted and dropped; decide as a group.

---

## Gold corpus cannot see medication coverage

The wheel moved from the CHV-only gazetteer (1,817 medication surfaces) to the
RxNorm-complete one (**16,824**, 9.3×) and micro F1 moved by **0.000000** on both
corpora. The corpus barely exercises medications, so it can detect neither a
regression nor a gain in the largest dictionary the scanner ships.

- [ ] Add medication-bearing documents and cells to the gold set before the
      gazetteer is tuned further, or its accuracy is unmeasured either way.
