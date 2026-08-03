"""Elect one canonical span per overlap cluster, keeping the losers as evidence."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Literal, Mapping, Sequence, Tuple

from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import EntityConfig
from seiba_risk_scanner.classification_engine.pipeline_models import (
    CombinedDetectionRow,
    SpanAlternate,
)


class SpanElection:
    """Resolve overlapping detections to exactly one span each.

    Replaces confidence-only containment plus a hand-written entity priority table. Both
    could decline to act on the same pair — one because the inner span was the more
    confident, the other because the two entities shared a tier — leaving an overlap that
    no scrub can apply. Election is total, so every cluster yields one span.

    Ranking is derived from the ontology rather than typed per entity, so a newly added
    entity needs no priority entry to resolve correctly.
    """

    def __init__(self, configs: Mapping[str, EntityConfig]) -> None:
        self.configs = configs

    def resolve(self, rows: Sequence[CombinedDetectionRow]) -> List[CombinedDetectionRow]:
        if len(rows) <= 1:
            return list(rows)
        nested = {
            id(inner)
            for outer in rows
            for inner in rows
            if inner is not outer and self._contains(outer, inner)
        }
        # Strongest first, each span taken only if the range is still free. Keeping a
        # maximal set rather than one winner per overlapping chain matters: where A meets B
        # and B meets C but A never meets C, only B has to go. Nested spans are ranked last
        # so their container gets first refusal, but they are still taken if it lost.
        accepted: List[CombinedDetectionRow] = []
        losers: List[CombinedDetectionRow] = []
        for row in sorted(
            rows, key=lambda r: (id(r) not in nested, *self._rank(r)), reverse=True
        ):
            if any(self._overlaps(kept, row) for kept in accepted):
                losers.append(row)
            else:
                accepted.append(row)
        return self._attach(accepted, losers)

    def _attach(
        self, accepted: List[CombinedDetectionRow], losers: List[CombinedDetectionRow]
    ) -> List[CombinedDetectionRow]:
        """Record each dropped span on the accepted span that displaced it."""
        by_winner: Dict[int, List[SpanAlternate]] = defaultdict(list)
        for row in losers:
            winner = next((kept for kept in accepted if self._overlaps(kept, row)), None)
            if winner is None:
                continue
            by_winner[id(winner)].append(
                SpanAlternate(
                    entity_id=row.entity_id,
                    entity=row.entity,
                    start=row.start,
                    end=row.end,
                    text=row.text,
                    confidence=row.confidence,
                    reason=self._reason(winner, row),
                )
            )
        out = [
            row.model_copy(update={"alternates": by_winner[id(row)]})
            if by_winner.get(id(row))
            else row
            for row in accepted
        ]
        out.sort(key=lambda row: (row.start, -row.confidence))
        return out

    def _reason(
        self, winner: CombinedDetectionRow, row: CombinedDetectionRow
    ) -> Literal["absorbed", "nested", "outranked"]:
        """Why this span lost — separating an expected roll-up from a real disagreement."""
        if not self._contains(winner, row):
            return "outranked"
        return "absorbed" if self._related(winner.entity_id, row.entity_id) else "nested"

    @staticmethod
    def _overlaps(a: CombinedDetectionRow, b: CombinedDetectionRow) -> bool:
        return a.start < b.end and b.start < a.end

    @staticmethod
    def _contains(outer: CombinedDetectionRow, inner: CombinedDetectionRow) -> bool:
        """True when ``inner`` sits wholly inside a strictly wider ``outer``.

        Containment outranks every other criterion. A short sub-span that merely validates
        would otherwise carve up the span that actually names the value — two digits of an
        age parse as a date, ten digits of an IMEI as a phone number. Nothing is lost by
        preferring the wider reading: the inner one survives as an alternate, and policy
        escalates to its action if it was the more protective of the two.
        """
        return (
            outer.start <= inner.start
            and inner.end <= outer.end
            and outer.end - outer.start > inner.end - inner.start
        )

    def _related(self, outer_id: str, inner_id: str) -> bool:
        """Whether a nested span is the same claim at finer grain rather than a rival."""
        if outer_id == inner_id:
            return True
        inner = self.configs.get(inner_id)
        return inner is not None and outer_id in (inner.is_a, inner.part_of)

    def _rank(self, row: CombinedDetectionRow) -> Tuple[int, float, int, str]:
        """Order contenders; entity_id last so a tie never depends on detector order."""
        return (self._evidence(row), row.confidence, row.end - row.start, row.entity_id)

    def _evidence(self, row: CombinedDetectionRow) -> int:
        """How the span was recognised: 2 validated, 1 matched a format, 0 inferred.

        A validator that is configured but does *not* pass drops the span to its pattern
        strength, so a regex-shaped date no longer outranks a confident name on the claim
        of a checksum it never satisfied.
        """
        config = self.configs.get(row.entity_id)
        if config is None:
            return 0
        if config.validator_enum is not None and config.validates(row.text):
            return 2
        return 1 if config.accepted_patterns else 0


__all__ = ["SpanElection"]
