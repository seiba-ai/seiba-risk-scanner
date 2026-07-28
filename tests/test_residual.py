"""Residual measurement: what the scrub left behind, and how severity is re-scored for it."""
from __future__ import annotations


from seiba_risk_scanner.assessment.residual import (
    ACTION_SEVERITY_RETENTION,
    residual_risk,
    residual_score,
)
from seiba_risk_scanner.policy.models import ActionRecord


def record(
    field,
    text,
    replacement,
    *,
    action="mask",
    data_class="direct_identifier",
    label=None,
    row=0,
):
    return ActionRecord(
        entity_id=f"x::{field}",
        entity=field,
        text=text,
        start=0,
        end=len(text),
        openmed_label=label or field.upper(),
        seiba_data_class=data_class,
        policy_name="hipaa_safe_harbor",
        action=action,
        source="openmed_action_for",
        detail="",
        replacement=replacement,
        provenance={"column": field, "row": row},
    )


# --------------------------------------------------------------------------- leakage


def test_a_clean_scrub_leaks_nothing():
    groups = [
        [record("ssn", "123-45-6789", "[SSN]", row=0)],
        [record("ssn", "987-65-4321", "[SSN]", row=1)],
    ]
    assert residual_risk(groups).leakage_rate == 0.0


def test_a_value_that_survived_untouched_is_a_leak():
    groups = [
        [record("ssn", "123-45-6789", "123-45-6789", row=0)],  # mask silently failed
        [record("ssn", "987-65-4321", "[SSN]", row=1)],
    ]
    assert residual_risk(groups).leakage_rate == 0.5


def test_a_hash_is_not_a_leak():
    """OpenMed's own check counts any non-uppercase value as surviving; ours compares."""
    groups = [
        [record("email", "a@x.com", "EMAIL_2f9c1a", action="hash", row=0)],
        [record("email", "b@x.com", "EMAIL_77bd30", action="hash", row=1)],
    ]
    assert residual_risk(groups).leakage_rate == 0.0


def test_a_generalized_date_is_not_a_leak():
    groups = [
        [record("dob", "March 15, 1989", "1989", action="generalize", label="DATE_OF_BIRTH")],
        [record("dob", "June 2, 1990", "1990", action="generalize", label="DATE_OF_BIRTH", row=1)],
    ]
    assert residual_risk(groups).leakage_rate == 0.0


def test_only_identifying_classes_count_as_leakage():
    """A kept city is a re-identification risk, not a leaked identifier — different metric."""
    groups = [
        [record("city", "Austin", "Austin", action="keep", data_class="quasi_identifier")],
        [record("city", "Boston", "Boston", action="keep", data_class="quasi_identifier", row=1)],
    ]
    assert residual_risk(groups).leakage_rate == 0.0


def test_nothing_to_compare_returns_none():
    assert residual_risk([]) is None
    assert residual_risk([[]]) is None


def test_kept_quasi_identifiers_still_fingerprint_records():
    """Direct identifiers gone but distinct quasi-identifiers left: re-identifiable."""
    groups = [
        [
            record("ssn", "123-45-6789", "[SSN]", row=0),
            record("city", "Austin", "Austin", action="keep", data_class="quasi_identifier"),
        ],
        [
            record("ssn", "987-65-4321", "[SSN]", row=1),
            record("city", "Boston", "Boston", action="keep", data_class="quasi_identifier", row=1),
        ],
    ]
    result = residual_risk(groups)
    assert result.leakage_rate == 0.0
    assert result.reid_rate > 0.0


# --------------------------------------------------------------------------- severity re-score


def test_destroyed_values_carry_no_residual_severity():
    for action in ("mask", "redact"):
        assert residual_score(0.9, record("ssn", "x", "[SSN]", action=action)) == 0.0


def test_kept_values_carry_their_full_severity():
    assert residual_score(0.9, record("ssn", "x", "x", action="keep")) == 0.9


def test_surrogates_keep_a_little_because_records_stay_linkable():
    score = residual_score(0.9, record("ssn", "x", "TOKEN", action="hash"))
    assert 0.0 < score < 0.9


def test_generalized_values_keep_what_their_precision_is_worth():
    exact = residual_score(
        0.9, record("dob", "March 15, 1989", "March 15, 1989", action="generalize", label="DATE_OF_BIRTH")
    )
    year = residual_score(
        0.9, record("dob", "March 15, 1989", "1989", action="generalize", label="DATE_OF_BIRTH")
    )
    decade = residual_score(
        0.9, record("dob", "March 15, 1989", "1980s", action="generalize", label="DATE_OF_BIRTH")
    )
    assert exact > year > decade > 0.0


def test_retention_table_is_ordered_least_to_most_destructive():
    table = ACTION_SEVERITY_RETENTION
    assert table["keep"] == 1.0
    assert table["mask"] == table["redact"] == 0.0
    assert table["mask"] < table["replace"] <= table["hash"] < table["keep"]


def test_an_unknown_action_is_treated_as_fully_destructive():
    # Safer to under-report residual risk than to assume an unrecognised action kept nothing.
    assert residual_score(0.9, record("ssn", "x", "y", action="something_new")) == 0.0
