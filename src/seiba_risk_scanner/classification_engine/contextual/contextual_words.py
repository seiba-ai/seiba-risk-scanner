from __future__ import annotations

import re
from dataclasses import dataclass

from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import EntityConfig

# Used when ontology YAML has contextual_phrases.confidence_weight: null
DEFAULT_CONTEXTUAL_PHRASE_WEIGHT = 0.4

# Default asymmetric phrase windows (chars); prohibited prefix/suffix uses prohibited_context_window on SDK
DEFAULT_CONTEXT_WINDOW_BEFORE = 50
DEFAULT_CONTEXT_WINDOW_AFTER = 25

# Side multipliers: text before the span (labels, field names) weighted slightly higher
DEFAULT_BEFORE_SIDE_MULTIPLIER = 1.25
DEFAULT_AFTER_SIDE_MULTIPLIER = 1.0

# Extra boost per additional distinct phrase match after the first
_EXTRA_PHRASE_INCREMENT = 0.05


@dataclass(frozen=True)
class ContextEvidence:
    score: float
    matched_phrases: list[str]
    matched_in_before: list[str]
    matched_in_after: list[str]


class ContextualWordsScorer:
    """
    Scores how well surrounding text matches an entity's contextual_phrases.

    Uses asymmetric before/after windows and proximity-weighted contributions.
    The span text itself is excluded (only before + after).
    """

    def __init__(
        self,
        *,
        default_phrase_weight: float = DEFAULT_CONTEXTUAL_PHRASE_WEIGHT,
        extra_phrase_increment: float = _EXTRA_PHRASE_INCREMENT,
        before_side_multiplier: float = DEFAULT_BEFORE_SIDE_MULTIPLIER,
        after_side_multiplier: float = DEFAULT_AFTER_SIDE_MULTIPLIER,
    ) -> None:
        self.default_phrase_weight = default_phrase_weight
        self.extra_phrase_increment = extra_phrase_increment
        self.before_side_multiplier = before_side_multiplier
        self.after_side_multiplier = after_side_multiplier

    def score_span(
        self,
        text: str,
        start: int,
        end: int,
        config: EntityConfig,
        context_window_before: int,
        context_window_after: int,
        *,
        extra_before_text: str | None = None,
        extra_after_text: str | None = None,
    ) -> float:
        return self.score_span_with_evidence(
            text,
            start,
            end,
            config,
            context_window_before,
            context_window_after,
            extra_before_text=extra_before_text,
            extra_after_text=extra_after_text,
        ).score

    def score_span_with_evidence(
        self,
        text: str,
        start: int,
        end: int,
        config: EntityConfig,
        context_window_before: int,
        context_window_after: int,
        *,
        extra_before_text: str | None = None,
        extra_after_text: str | None = None,
    ) -> ContextEvidence:
        phrases = config.contextual_phrases
        if not phrases:
            return ContextEvidence(
                score=0.0,
                matched_phrases=[],
                matched_in_before=[],
                matched_in_after=[],
            )

        wb = config.contextual_window_before
        wa = config.contextual_window_after
        eff_wb = wb if wb is not None else context_window_before
        eff_wa = wa if wa is not None else context_window_after

        before = text[max(0, start - eff_wb) : start]
        after = text[end : end + eff_wa]
        before_lower = before.lower()
        after_lower = after.lower()
        if extra_before_text:
            before_lower = f"{extra_before_text} {before_lower}".lower()
        if extra_after_text:
            after_lower = f"{after_lower} {extra_after_text}".lower()

        base = config.contextual_phrases_confidence_weight
        if base is None:
            base = self.default_phrase_weight
        else:
            base = float(base)

        matched_before: list[str] = []
        matched_after: list[str] = []
        per_phrase_best: list[float] = []

        for p in phrases:
            if not p or not isinstance(p, str):
                continue
            pl = p.strip()
            if not pl:
                continue

            cb = _best_side_contribution(
                pl,
                before_lower,
                base,
                self.before_side_multiplier,
                side="before",
            )
            ca = _best_side_contribution(
                pl,
                after_lower,
                base,
                self.after_side_multiplier,
                side="after",
            )
            best = max(cb, ca)
            if best > 0.0:
                per_phrase_best.append(best)
                if cb >= ca:
                    matched_before.append(pl)
                else:
                    matched_after.append(pl)

        matches = len(per_phrase_best)
        if matches == 0:
            return ContextEvidence(
                score=0.0,
                matched_phrases=[],
                matched_in_before=[],
                matched_in_after=[],
            )

        total = sum(per_phrase_best)
        if matches > 1:
            total += self.extra_phrase_increment * (matches - 1)

        score = max(0.0, min(1.0, total))
        merged_matches = list(dict.fromkeys(matched_before + matched_after))
        return ContextEvidence(
            score=score,
            matched_phrases=merged_matches,
            matched_in_before=matched_before,
            matched_in_after=matched_after,
        )


def _best_side_contribution(
    phrase: str,
    haystack_lower: str,
    base: float,
    side_mult: float,
    *,
    side: str,
) -> float:
    """Best single-match contribution on one side using proximity to span edge."""
    spans = _phrase_match_spans(phrase, haystack_lower)
    if not spans:
        return 0.0
    n = len(haystack_lower)
    if n == 0:
        return 0.0

    best = 0.0
    for ms, me in spans:
        if side == "before":
            # Match ends at me; span starts after `before` string -> distance from match end to span
            gap = float(n - me)
            prox = 1.0 - min(1.0, gap / max(1.0, float(n)))
        else:
            # After: match starts at ms; gap from span end to phrase start
            gap = float(ms)
            prox = 1.0 - min(1.0, gap / max(1.0, float(n)))
        contrib = base * prox * side_mult
        if contrib > best:
            best = contrib
    return best


def _phrase_match_spans(phrase: str, haystack_lower: str) -> list[tuple[int, int]]:
    pl = phrase.strip().lower()
    if not pl:
        return []
    if " " in pl:
        spans: list[tuple[int, int]] = []
        start = 0
        while True:
            i = haystack_lower.find(pl, start)
            if i < 0:
                break
            spans.append((i, i + len(pl)))
            start = i + 1
        return spans
    spans = []
    for m in re.finditer(r"\b" + re.escape(pl) + r"\b", haystack_lower):
        spans.append((m.start(), m.end()))
    return spans


def fuse_confidence(
    confidence_deterministic: float,
    confidence_contextual: float,
    *,
    weight_deterministic: float = 0.65,
    weight_contextual: float = 0.35,
) -> float:
    """
    Boost-only fusion, clamped to [0, 1].

    Contextual confidence only increases the score; it never lowers the deterministic
    confidence. Weight controls how much contextual score contributes to the remaining
    headroom (1 - det).
    """
    _ = weight_deterministic
    det = float(confidence_deterministic)
    ctx = float(confidence_contextual)
    if ctx <= 0.0:
        return max(0.0, min(1.0, det))
    w_ctx = float(weight_contextual)
    boosted = det + (w_ctx * ctx * (1.0 - det))
    return max(0.0, min(1.0, boosted))


def rank_entity_candidates(
    *,
    text: str,
    start: int,
    end: int,
    context_window_before: int,
    context_window_after: int,
    configs: dict[str, EntityConfig],
    scorer: ContextualWordsScorer,
    detected_entity_id: str,
    top_k: int = 3,
    extra_before_text: str | None = None,
    extra_after_text: str | None = None,
) -> list[tuple[str, ContextEvidence]]:
    """
    Score contextual phrases for all other entities and return best candidates.

    Returns list of (entity_id, evidence) sorted by evidence.score descending.
    """
    scored: list[tuple[str, ContextEvidence]] = []
    for entity_id, cfg in configs.items():
        if entity_id == detected_entity_id:
            continue
        if not cfg.contextual_phrases:
            continue
        ev = scorer.score_span_with_evidence(
            text,
            start,
            end,
            cfg,
            context_window_before,
            context_window_after,
            extra_before_text=extra_before_text,
            extra_after_text=extra_after_text,
        )
        if ev.score > 0.0:
            scored.append((entity_id, ev))

    scored.sort(key=lambda t: t[1].score, reverse=True)
    return scored[: max(0, int(top_k))]


__all__ = [
    "ContextualWordsScorer",
    "DEFAULT_CONTEXTUAL_PHRASE_WEIGHT",
    "DEFAULT_CONTEXT_WINDOW_BEFORE",
    "DEFAULT_CONTEXT_WINDOW_AFTER",
    "fuse_confidence",
    "ContextEvidence",
    "rank_entity_candidates",
]