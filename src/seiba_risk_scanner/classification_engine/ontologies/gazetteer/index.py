"""Runtime dictionary matcher + term normalizer over curated medical surfaces.

Dependency-free by design so it lifts cleanly into seiba-assess: two faces off one
index — :meth:`GazetteerIndex.iter_matches` for detection, :meth:`GazetteerIndex.normalize`
for surface -> canonical term standardization. The curated artifact is produced offline
by ``gazetteer/build.py``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterator, Optional

_ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent
    / "med_ontology_sources"
    / "cleaned"
    / "medical_terms_gazetteer.json"
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def normalize_term(text: str) -> str:
    """Lowercase and collapse every non-alphanumeric run to a single space.

    Shared by the builder and the matcher so a curated surface form and a span of
    scanned text reduce to the same key (``Type-2 Diabetes`` -> ``type 2 diabetes``).
    """
    return " ".join(_TOKEN_RE.findall(text.lower()))


@dataclass(frozen=True)
class CanonicalTerm:
    """A curated concept a surface form resolves to."""

    entity: str  # short entity name: "medical_condition" | "medication_name"
    canonical: str  # preferred label
    code: Optional[str]  # source concept id (MONDO IRI / RxCUI / CHV CUI)
    source: str  # "mondo" | "rxnorm" | "chv"


@dataclass(frozen=True)
class GazetteerMatch:
    start: int
    end: int
    text: str
    term: CanonicalTerm


class GazetteerIndex:
    """Longest-match-wins token n-gram lookup over a curated surface -> concept map.

    Word-boundary aware (matching is token-based), case/punctuation-insensitive, and
    linear in tokens so it stays cheap on large documents.
    """

    def __init__(self, terms: Dict[str, CanonicalTerm], max_ngram: int):
        self._terms = terms
        self._max_ngram = max(1, max_ngram)

    @classmethod
    def from_artifact(cls, path: Optional[Path] = None) -> "GazetteerIndex":
        data = json.loads(Path(path or _ARTIFACT_PATH).read_text(encoding="utf-8"))
        terms = {
            surface: CanonicalTerm(entity=v[0], canonical=v[1], code=v[2], source=v[3])
            for surface, v in data["terms"].items()
        }
        return cls(terms, int(data.get("max_ngram", 1)))

    def normalize(self, term: str) -> Optional[CanonicalTerm]:
        """Resolve a full surface form to its canonical concept, or None if unknown."""
        return self._terms.get(normalize_term(term))

    def iter_matches(self, text: str) -> Iterator[GazetteerMatch]:
        tokens = [(m.group(0).lower(), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
        n = len(tokens)
        i = 0
        while i < n:
            j_end = min(n, i + self._max_ngram)
            for j in range(j_end, i, -1):  # longest window first
                term = self._terms.get(" ".join(tok for tok, _, _ in tokens[i:j]))
                if term is not None:
                    start, end = tokens[i][1], tokens[j - 1][2]
                    yield GazetteerMatch(start=start, end=end, text=text[start:end], term=term)
                    i = j
                    break
            else:
                i += 1


@lru_cache(maxsize=1)
def get_default_index() -> GazetteerIndex:
    """Process-wide singleton over the bundled artifact (built once, reused).

    Degrades to an empty index if the artifact is absent (e.g. a partial checkout)
    so the gazetteer disables itself rather than breaking every scan.
    """
    try:
        return GazetteerIndex.from_artifact()
    except FileNotFoundError:
        return GazetteerIndex({}, 1)
