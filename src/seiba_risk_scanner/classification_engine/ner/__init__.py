"""NER stage and merge with deterministic + contextual fusion."""

from seiba_risk_scanner.classification_engine.ner.backends.spacy_backend import DEFAULT_NER_CONFIDENCE_WEIGHT
from seiba_risk_scanner.classification_engine.ner.backends.base import NerSpanRecord
from seiba_risk_scanner.classification_engine.ner.merge_hypotheses import resolve_deterministic_and_ner_to_combined
from seiba_risk_scanner.classification_engine.ner.ner_runner import BACKENDS, run_combined_ner, run_combined_ner_with_override

__all__ = [
    "BACKENDS",
    "DEFAULT_NER_CONFIDENCE_WEIGHT",
    "NerSpanRecord",
    "resolve_deterministic_and_ner_to_combined",
    "run_combined_ner",
    "run_combined_ner_with_override",
]
