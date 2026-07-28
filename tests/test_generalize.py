"""Generalization as a policy action: per-value transforms, wiring, and its utility payoff."""
from __future__ import annotations

import pytest

from seiba_risk_scanner.assessment.utility import utility_loss
from seiba_risk_scanner.policy import (
    DEFAULT_LEVELS,
    apply_action_to_text,
    generalize,
    kind_for_label,
)
from seiba_risk_scanner.policy.models import ActionRecord


def record(text, label, action="generalize", level=None, row=0, column=None):
    return ActionRecord(
        entity_id=f"x::{label.lower()}",
        entity=label.lower(),
        text=text,
        start=0,
        end=len(text),
        openmed_label=label,
        policy_name="hipaa_safe_harbor",
        action=action,
        generalization_level=level,
        source="seiba_action_override",
        detail="",
        provenance={"column": column or label.lower(), "row": row},
    )


# --------------------------------------------------------------------------- transforms


@pytest.mark.parametrize(
    "label,text,expected",
    [
        ("DATE_OF_BIRTH", "March 15, 1989", "1989"),  # prose date, dateutil not ISO regex
        ("DATE_OF_BIRTH", "03/15/1989", "1989"),
        ("DATE", "2024-03-07", "2024"),
        ("AGE", "34 years old", "30-34"),
        ("ZIPCODE", "02139", "021**"),
        ("GPS_COORDINATES", "42.360081", "42.4"),
    ],
)
def test_default_level_matches_safe_harbor(label, text, expected):
    assert generalize(text, kind_for_label(label)) == expected


def test_ages_over_89_collapse_into_one_bucket():
    # Safe Harbor: a 5-year band at the top of the range would re-identify.
    assert generalize("93", "age") == "90+"
    assert generalize("89", "age") == "85-89"


def test_ladders_coarsen_monotonically():
    assert [generalize("March 15, 1989", "date", l) for l in ("month", "year", "decade")] == [
        "1989-03",
        "1989",
        "1980s",
    ]
    assert [generalize("34", "age", l) for l in ("5_year_band", "10_year_band")] == [
        "30-34",
        "30-39",
    ]


def test_unparseable_value_returns_none_rather_than_guessing():
    assert generalize("not a date at all", "date") is None


def test_labels_without_a_defensible_ladder_are_not_generalizable():
    # A name or SSN must be removed, not coarsened; a city needs a geo hierarchy we lack.
    for label in ("SSN", "PERSON", "EMAIL", "LOCATION", "STREET_ADDRESS"):
        assert kind_for_label(label) is None


def test_unknown_level_is_rejected():
    with pytest.raises(ValueError):
        generalize("2024-01-01", "date", "century")


# --------------------------------------------------------------------------- executor


def test_executor_applies_the_generalized_value():
    assert apply_action_to_text(record("March 15, 1989", "DATE_OF_BIRTH")).replacement == "1989"


def test_executor_falls_back_to_mask_when_the_value_will_not_parse():
    done = apply_action_to_text(record("garbage", "DATE_OF_BIRTH"))
    assert done.execute_fallback == "generalize→mask"
    assert done.replacement == "[DATE_OF_BIRTH]"


def test_every_kind_has_a_default_level_on_its_ladder():
    from seiba_risk_scanner.policy.generalize import LABEL_KINDS, LADDERS

    for kind in set(LABEL_KINDS.values()):
        assert DEFAULT_LEVELS[kind] in LADDERS[kind]


# --------------------------------------------------------------------------- utility payoff


def test_generalizing_retains_more_than_masking():
    """The point of the action: safer than keeping, far more usable than masking."""
    zips = ["02139", "10001", "94105", "60601", "33101", "98101"]

    def retained(action, level=None):
        rows = [
            apply_action_to_text(record(z, "ZIPCODE", action=action, level=level, row=i))
            for i, z in enumerate(zips)
        ]
        return 1.0 - utility_loss(rows).overall

    assert retained("keep") == pytest.approx(1.0)
    assert retained("mask") < retained("generalize") < retained("keep")


def test_caller_override_selects_the_action_and_default_rung():
    from seiba_risk_scanner.policy import PolicyResolver
    from seiba_risk_scanner.classification_engine.pipeline_models import (
        CombinedDetectionRow,
    )

    row = CombinedDetectionRow(
        entity_id="phi_entity_ontology::date_of_birth",
        entity="date_of_birth",
        start=0,
        end=14,
        text="March 15, 1989",
        confidence=0.9,
        confidence_deterministic=0.9,
        confidence_contextual=0.0,
    )
    plan = PolicyResolver(action_overrides={"date_of_birth": "generalize"}).resolve([row])
    assert plan.records[0].action == "generalize"
    assert plan.records[0].generalization_level == "year"  # Safe Harbor default
    assert plan.records[0].source == "seiba_action_override"

    explicit = PolicyResolver(
        action_overrides={"date_of_birth": "generalize:month"}
    ).resolve([row])
    assert explicit.records[0].generalization_level == "month"


def test_override_rejects_generalizing_an_entity_with_no_ladder():
    from seiba_risk_scanner.policy import PolicyResolver
    from seiba_risk_scanner.classification_engine.pipeline_models import (
        CombinedDetectionRow,
    )

    row = CombinedDetectionRow(
        entity_id="pii_entity_ontology::ssn",
        entity="ssn",
        start=0,
        end=11,
        text="123-45-6789",
        confidence=0.9,
        confidence_deterministic=0.9,
        confidence_contextual=0.0,
    )
    with pytest.raises(ValueError, match="cannot be generalized"):
        PolicyResolver(action_overrides={"ssn": "generalize"}).resolve([row])


# --------------------------------------------------------------------------- precision


@pytest.mark.parametrize(
    "label,text,expected_level",
    [
        ("DATE_OF_BIRTH", "March 15, 1989", "exact"),
        ("DATE_OF_BIRTH", "1989-03", "month"),
        ("DATE_OF_BIRTH", "1989", "year"),
        ("DATE_OF_BIRTH", "1980s", "decade"),
        ("ZIPCODE", "02139", "exact"),
        ("ZIPCODE", "021**", "3_digit"),
        ("AGE", "34", "exact"),
        ("AGE", "30-34", "5_year_band"),
        ("AGE", "90+", "20_year_band"),
        ("GPS_COORDINATES", "42.4", "1_decimal"),
    ],
)
def test_precision_is_read_from_the_value(label, text, expected_level):
    from seiba_risk_scanner.policy.generalize import precision_factor

    factor, level = precision_factor(text, label)
    assert level == expected_level
    assert (factor == 1.0) == (expected_level == "exact")


def test_entities_without_a_precision_axis_are_never_discounted():
    from seiba_risk_scanner.policy.generalize import precision_factor

    for label in ("SSN", "PERSON", "EMAIL"):
        assert precision_factor("anything", label) == (1.0, None)


def test_coarser_values_score_lower_severity():
    """A bare year links against outside data far worse than a full date of birth."""
    from seiba_risk_scanner import load_entity_configs
    from seiba_risk_scanner.assessment.resolver import SeverityResolver
    from seiba_risk_scanner.classification_engine.pipeline_models import (
        CombinedDetectionRow,
    )

    configs = load_entity_configs()
    resolver = SeverityResolver()

    def score(text):
        row = CombinedDetectionRow(
            entity_id="phi_entity_ontology::date_of_birth",
            entity="date_of_birth",
            start=0,
            end=len(text),
            text=text,
            confidence=0.95,
            confidence_deterministic=0.95,
            confidence_contextual=0.0,
        )
        return resolver.resolve(row, configs["phi_entity_ontology::date_of_birth"]).risk_score

    exact, month, year, decade = (score(t) for t in ("March 15, 1989", "1989-03", "1989", "1980s"))
    assert exact > month > year > decade

    trace = " ".join(
        r.rule_id
        for r in SeverityResolver()
        .resolve(
            CombinedDetectionRow(
                entity_id="phi_entity_ontology::date_of_birth",
                entity="date_of_birth",
                start=0,
                end=4,
                text="1989",
                confidence=0.95,
                confidence_deterministic=0.95,
                confidence_contextual=0.0,
            ),
            configs["phi_entity_ontology::date_of_birth"],
        )
        .rule_trace
    )
    assert "precision:year" in trace  # the discount has to be explained, not silent


def test_distinguishability_is_graded_not_binary():
    """Collapsing some values must score above collapsing all, or generalization is invisible."""
    # Same 3-digit region: generalizing collapses everything, like masking.
    same_region = ["02139", "02140", "02141", "02142"]
    # Different regions: generalizing keeps them apart.
    spread = ["02139", "10001", "94105", "60601"]

    def retained(values):
        rows = [
            apply_action_to_text(record(v, "ZIPCODE", row=i)) for i, v in enumerate(values)
        ]
        return 1.0 - utility_loss(rows).overall

    assert retained(spread) > retained(same_region)
