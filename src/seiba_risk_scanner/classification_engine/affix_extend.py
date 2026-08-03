"""Grow a span over adjacent words that belong inside it.

A detector that finds "Jennifer Smith" but not the "Dr." in front of it leaves that title
standing in scrubbed output. Affixes are declared per entity in the ontology YAML and
resolved through ``is_a``, so a title configured on physician_names extends a span reported
as its person_names parent — the subtype owns the vocabulary, the parent gets the benefit.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Sequence, Tuple

from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import EntityConfig
from seiba_risk_scanner.classification_engine.pipeline_models import CombinedDetectionRow

Affixes = Tuple[List[str], List[str]]


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _affix_map(configs: Mapping[str, EntityConfig]) -> Dict[str, Affixes]:
    """entity_id -> (prefixes, suffixes), each subtype also crediting its is_a ancestors."""
    merged: Dict[str, Affixes] = {}
    for config in configs.values():
        if not config.affix_prefix and not config.affix_suffix:
            continue
        seen: set[str] = set()
        node: EntityConfig | None = config
        while node is not None and node.entity_id not in seen:
            seen.add(node.entity_id)
            prefixes, suffixes = merged.setdefault(node.entity_id, ([], []))
            prefixes += config.affix_prefix
            suffixes += config.affix_suffix
            node = configs.get(node.is_a) if node.is_a else None
    return merged


def _grow(text: str, start: int, end: int, affixes: Affixes) -> Tuple[int, int]:
    """Pull in the longest adjacent affix on each side, whitespace between allowed."""
    prefixes, suffixes = affixes
    head = text[:start].rstrip()
    for affix in sorted(prefixes, key=len, reverse=True):
        cut = len(head) - len(affix)
        if cut < 0 or head[cut:].lower() != affix.lower():
            continue
        if cut and _is_word_char(text[cut - 1]):
            continue  # the affix is the tail of a longer word
        start = cut
        break
    tail = text[end:]
    lead = len(tail) - len(tail.lstrip())
    for affix in sorted(suffixes, key=len, reverse=True):
        stop = end + lead + len(affix)
        if text[end + lead : stop].lower() != affix.lower():
            continue
        if stop < len(text) and _is_word_char(text[stop]):
            continue
        end = stop
        break
    return start, end


def extend_spans(
    rows: Sequence[CombinedDetectionRow],
    text: str,
    configs: Mapping[str, EntityConfig],
) -> List[CombinedDetectionRow]:
    """Return ``rows`` with configured affixes absorbed into their spans.

    An extension that would collide with another span is dropped: overlapping spans break
    the scrub, and a title left in is a smaller failure than a corrupted replacement.
    """
    affix_map = _affix_map(configs)
    if not affix_map:
        return list(rows)
    out: List[CombinedDetectionRow] = []
    for row in rows:
        affixes = affix_map.get(row.entity_id)
        if affixes is None:
            out.append(row)
            continue
        start, end = _grow(text, row.start, row.end, affixes)
        if (start, end) == (row.start, row.end) or any(
            other is not row and start < other.end and other.start < end for other in rows
        ):
            out.append(row)
            continue
        out.append(row.model_copy(update={"start": start, "end": end, "text": text[start:end]}))
    return out


__all__ = ["extend_spans"]
