"""is_a hierarchy, non-lossy subtype retention, and the pattern-less detection guard.

The guard operationalises a standing requirement: an entity with no regex pattern must not
silently become undetectable. Detection for such entities comes from NER, from being an
is_a parent that children roll up into, or from a validator-gated context override — never
from the deterministic pattern loop, which skips them by design.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

repo_root = Path(__file__).resolve().parents[1]
for _p in (repo_root / "src", repo_root):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from seiba_risk_scanner import SeibaScanner  # noqa: E402
from seiba_risk_scanner.classification_engine.ontologies.gazetteer.build import (  # noqa: E402
    MEDICAL_CONDITION,
    MEDICATION_NAME,
)
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (  # noqa: E402
    load_entity_configs,
    load_ner_label_to_entity_map,
    make_entity_id,
    resolve_entity_alias,
)
from seiba_risk_scanner.config import ONTOLOGY_STEM_PHI  # noqa: E402

# Pattern-less but detected by the gazetteer dictionary pass (a distinct source from
# the regex loop and NER).
_GAZETTEER_IDS = {
    make_entity_id(ONTOLOGY_STEM_PHI, name) for name in (MEDICAL_CONDITION, MEDICATION_NAME)
}

_OPENMED_MAP = (
    repo_root
    / "src/seiba_risk_scanner/classification_engine/ner/label_maps/openmed_labels.yaml"
)

# Pattern-less entities that are, by nature, not detectable from text — biometric and image
# identifiers exist in the taxonomy for severity/coverage, not for text scanning. Anything
# NOT here must have a real detection path, or the guard fails.
_TAXONOMY_ONLY = {
    "phi_entity_ontology::dna_sequences",
    "phi_entity_ontology::facial_photographs",
    "phi_entity_ontology::fingerprints",
    "phi_entity_ontology::retinal_scans",
    "phi_entity_ontology::voiceprints",
}

# Pattern-less entities that are text-detectable in principle but not yet wired to any
# detector. Frozen here so the set is explicit and cannot grow silently; shrinking it (by
# wiring one up) is welcome. This is the "don't let pattern-less entities be ignored" gate.
_KNOWN_UNWIRED = {
    "phi_entity_ontology::authorization_precertification_code",
    "phi_entity_ontology::hcpcs_codes",
    "phi_entity_ontology::lab_results",
    "phi_entity_ontology::measurement_units",
    "phi_entity_ontology::ndc_codes",
    "phi_entity_ontology::provider_tax_id_ein",
    "pii_entity_ontology::po_box",
    "pii_entity_ontology::uk_national_insurance_number_nino",
}


def _ner_reachable_ids() -> set:
    ids: set = set()
    for targets in load_ner_label_to_entity_map().values():
        ids.update(targets)
    raw = yaml.safe_load(_OPENMED_MAP.read_text(encoding="utf-8")) or {}
    for value in raw.values():
        if isinstance(value, str):
            ids.add(value)
        elif isinstance(value, dict):
            for key in ("entity_id", "fallback_entity_id"):
                if value.get(key):
                    ids.add(value[key])
    return ids


def test_every_patternless_entity_has_a_detection_path_or_is_declared():
    configs = load_entity_configs()
    ner_ids = _ner_reachable_ids()
    is_a_parents = {cfg.is_a for cfg in configs.values() if cfg.is_a}

    def reachable(eid: str) -> bool:
        cfg = configs[eid]
        return (
            eid in ner_ids  # emitted by a NER backend
            or eid in _GAZETTEER_IDS  # emitted by the gazetteer dictionary pass
            or cfg.is_a is not None  # rolls up to a detectable parent
            or eid in is_a_parents  # is a parent that children roll up into
            or (cfg.validator_enum is not None and cfg.contextual_phrases)  # validator-gated override
        )

    undetectable = [
        eid
        for eid, cfg in configs.items()
        if not cfg.accepted_patterns
        and not reachable(eid)
        and eid not in _TAXONOMY_ONLY
        and eid not in _KNOWN_UNWIRED
    ]
    assert not undetectable, (
        "Pattern-less entities with no detection path (add a NER mapping / is_a / context "
        f"override, or declare them taxonomy-only/unwired): {sorted(undetectable)}"
    )


def test_certificate_license_number_is_detectable_by_proximity_and_ner():
    """The entity the requirement named: pattern-less, but reachable via NER + context."""
    configs = load_entity_configs()
    cfg = configs["phi_entity_ontology::certificate_license_number"]
    assert not cfg.accepted_patterns  # judged by proximity, not regex
    assert cfg.contextual_phrases  # proximity phrases present
    assert "phi_entity_ontology::certificate_license_number" in _ner_reachable_ids()
    # The old PII duplicate is gone.
    assert "pii_entity_ontology::certificate_license_number" not in configs


def test_bank_account_is_a_standalone_financial_entity_not_an_identifier():
    """A bank account is its own concept — no is_a to unique_identifier, despite the
    shared digit shape. unique_identifier is the renamed former account_number."""
    configs = load_entity_configs()
    assert "fin_entity_ontology::account_number" not in configs  # dead duplicate removed
    assert "pii_entity_ontology::account_number" not in configs  # renamed
    assert "pii_entity_ontology::unique_identifier" in configs
    assert configs["fin_entity_ontology::bank_account_number"].is_a is None
    assert (
        resolve_entity_alias("fin_entity_ontology::bank_account_number", configs)
        == "fin_entity_ontology::bank_account_number"
    )

    def fake_ner(_text):
        return []

    sdk = SeibaScanner(ner_runner_override=fake_ner)
    # 11 digits dodges the fixed-length ID collisions (phone/fax 10, aadhaar 12, ssn 9).
    res = sdk.classify_text("Please debit checking account 44567812309 for the balance.")
    hits = [r for r in res.detections if "44567812309" in r.text]
    assert hits, "bank account digits with bank context should be detected"
    assert hits[0].entity_id == "fin_entity_ontology::bank_account_number"


def test_is_a_parent_is_at_least_as_sensitive_as_child():
    """Design invariant: a generic parent is never less sensitive than an is_a child.

    Detection reports a child as its parent (a physician as a person), and severity scores
    the parent — which is only safe if the parent rates >= the child. A child that would
    outrank its parent is a modelling error: the fix is to drop the is_a link so the child
    scores as itself, not to let the subtype raise the parent's severity.
    """
    from seiba_risk_scanner.assessment.resolver import DEFAULT_BASE, DEFAULT_BASE_SCORES

    configs = load_entity_configs()
    offenders = []
    for eid, cfg in configs.items():
        parent = configs.get(cfg.is_a) if cfg.is_a else None
        if parent is None:
            continue
        child_sev = DEFAULT_BASE_SCORES.get(cfg.data_class, DEFAULT_BASE)
        parent_sev = DEFAULT_BASE_SCORES.get(parent.data_class, DEFAULT_BASE)
        if parent_sev < child_sev:
            offenders.append(f"{eid} ({child_sev:.2f}) > is_a {cfg.is_a} ({parent_sev:.2f})")
    assert not offenders, "is_a child more sensitive than parent — remove the is_a: " + "; ".join(offenders)


def test_date_of_birth_overrides_generic_dates_on_context():
    sdk = SeibaScanner(skip_ner=True)
    res = sdk.classify_text("Date of Birth: August 14, 1983")
    dob = [r for r in res.detections if r.text == "August 14, 1983"]
    assert dob and dob[0].entity_id == "phi_entity_ontology::date_of_birth"

    # A plain date with no birth/death context stays generic.
    res2 = sdk.classify_text("Appointment scheduled for August 14, 2024")
    plain = [r for r in res2.detections if r.text == "August 14, 2024"]
    assert plain and plain[0].entity_id == "pii_entity_ontology::dates"
