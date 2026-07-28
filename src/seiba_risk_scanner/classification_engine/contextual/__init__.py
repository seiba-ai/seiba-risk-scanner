"""Contextual phrase scoring around deterministic spans."""

from seiba_risk_scanner.classification_engine.contextual.contextual_words import (
    DEFAULT_CONTEXTUAL_PHRASE_WEIGHT,
    DEFAULT_CONTEXT_WINDOW_AFTER,
    DEFAULT_CONTEXT_WINDOW_BEFORE,
    ContextualWordsScorer,
    fuse_confidence,
)

__all__ = [
    "ContextualWordsScorer",
    "DEFAULT_CONTEXTUAL_PHRASE_WEIGHT",
    "DEFAULT_CONTEXT_WINDOW_BEFORE",
    "DEFAULT_CONTEXT_WINDOW_AFTER",
    "fuse_confidence",
]
