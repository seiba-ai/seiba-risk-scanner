from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class GoldSpan:
    start: int
    end: int
    text: str
    entity_id: str
    source_file: Optional[str] = None


@dataclass(frozen=True)
class PredSpan:
    start: int
    end: int
    text: str
    entity_id: str
    confidence: float
    winner_kind: Optional[Literal["deterministic", "ner", "context_candidate", "llm"]] = None
    confidence_llm: Optional[float] = None
    rescue_applied: bool = False
    original_entity_id: Optional[str] = None
    provenance: Optional[dict[str, Any]] = None

    @classmethod
    def from_combined(cls, doc: str, row: Any) -> "PredSpan":
        prov = dict(row.provenance) if getattr(row, "provenance", None) else {}
        prov.setdefault("doc", doc)
        return cls(
            start=int(row.start),
            end=int(row.end),
            text=str(row.text),
            entity_id=str(row.entity_id),
            confidence=float(row.confidence),
            winner_kind=getattr(row, "winner_kind", None),
            confidence_llm=getattr(row, "confidence_llm", None),
            rescue_applied=bool(getattr(row, "rescue_applied", False)),
            original_entity_id=getattr(row, "original_entity_id", None),
            provenance=prov,
        )


def span_len(start: int, end: int) -> int:
    return max(0, int(end) - int(start))


def overlap_len(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    s = max(int(a_start), int(b_start))
    e = min(int(a_end), int(b_end))
    return max(0, e - s)

