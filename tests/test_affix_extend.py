"""Affix extension: adjacent titles and facility words get pulled into the span."""

from __future__ import annotations

import pytest

from seiba_risk_scanner.classification_engine.affix_extend import extend_spans
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    load_entity_configs,
)
from seiba_risk_scanner.classification_engine.pipeline_models import CombinedDetectionRow

PERSON = "pii_entity_ontology::person_names"
ORG = "pii_entity_ontology::organization"


@pytest.fixture(scope="module")
def configs():
    return load_entity_configs()


def _row(entity_id: str, text: str, start: int, end: int) -> CombinedDetectionRow:
    return CombinedDetectionRow(
        entity_id=entity_id,
        entity=entity_id.split("::")[-1],
        start=start,
        end=end,
        text=text[start:end],
        confidence=0.9,
        confidence_deterministic=0.9,
        confidence_contextual=0.0,
    )


def _only(text: str, entity_id: str, start: int, end: int, configs) -> CombinedDetectionRow:
    return extend_spans([_row(entity_id, text, start, end)], text, configs)[0]


def test_title_on_a_subtype_extends_the_parent_span(configs):
    """'Dr.' is declared on physician_names; the span is reported as person_names."""
    text = "Referred to Dr. Jennifer Smith for evaluation."
    out = _only(text, PERSON, text.index("Jennifer"), text.index(" for"), configs)

    assert out.text == "Dr. Jennifer Smith"


def test_facility_suffix_is_absorbed(configs):
    text = "Seen at RIVERBEND SPECIALTY CLINIC yesterday."
    out = _only(text, ORG, text.index("RIVERBEND"), text.index(" CLINIC"), configs)

    assert out.text == "RIVERBEND SPECIALTY CLINIC"


def test_affix_must_be_a_whole_word(configs):
    """'Dr' must not be found inside 'Drew'."""
    text = "The drill was routine and Drew Barnes led it."
    out = _only(text, PERSON, text.index("Drew"), text.index(" led"), configs)

    assert out.text == "Drew Barnes"


def test_span_without_an_adjacent_affix_is_untouched(configs):
    text = "Patient Alice Brown was seen today."
    out = _only(text, PERSON, text.index("Alice"), text.index(" was"), configs)

    assert (out.start, out.end, out.text) == (8, 19, "Alice Brown")


def test_entity_with_no_configured_affixes_is_untouched(configs):
    text = "Email alice@example.com now."
    eid = "pii_entity_ontology::email_address"
    out = _only(text, eid, text.index("alice"), text.index(" now"), configs)

    assert out.text == "alice@example.com"


def test_extension_that_would_collide_is_dropped(configs):
    """A title already claimed by another span must not be swallowed twice."""
    text = "Referred to Dr. Jennifer Smith for evaluation."
    rows = [
        _row(PERSON, text, text.index("Jennifer"), text.index(" for")),
        _row(ORG, text, text.index("Dr."), text.index(" Jennifer")),
    ]
    out = extend_spans(rows, text, configs)

    assert out[0].text == "Jennifer Smith"  # unchanged: would have overlapped the ORG span


def test_longest_matching_affix_wins(configs):
    text = "Care at Lakeside MEDICAL CENTER continues."
    out = _only(text, ORG, text.index("Lakeside"), text.index(" MEDICAL"), configs)

    assert out.text == "Lakeside MEDICAL CENTER"
