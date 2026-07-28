"""Offline builder: raw MONDO / RxNorm / CHV -> curated medical-term gazetteer.

Run from the package root:  ``python -m ...gazetteer.build``

Emits ``med_ontology_sources/cleaned/medical_terms_gazetteer.json`` — a
``surface -> {entity, canonical, code, source}`` map consumed by
:class:`GazetteerIndex`. Re-run when a raw source changes. MONDO and RxNorm are the
typed backbones (disease / medication); CHV lay terms are joined onto them by
canonical string, which types them and drops CHV's non-clinical concepts.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterator, Set, Tuple

from seiba_risk_scanner.classification_engine.ontologies.gazetteer.index import (
    CanonicalTerm,
    normalize_term,
)
from seiba_risk_scanner.classification_engine.ontologies.ontology_extractors.rxnorm_drug_extractor import (
    VALID_TTYS,
    clean_drug_name,
)

_SOURCES = Path(__file__).resolve().parent.parent / "med_ontology_sources"
_MONDO = _SOURCES / "MONDO.csv"
_RXNORM = _SOURCES / "RXNCONSO.RRF"
_CHV = _SOURCES / "CHV_concepts_terms_flatfile_20110204.csv"
_OUT = _SOURCES / "cleaned" / "medical_terms_gazetteer.json"

MEDICAL_CONDITION = "medical_condition"
MEDICATION_NAME = "medication_name"
MAX_NGRAM = 8

# Short but clinically meaningful single tokens that beat the length gate.
ALLOW_SHORT = {"hiv", "flu", "std", "sti", "dvt", "copd", "uti", "ibs", "als", "tb", "ocd", "adhd"}

# Pure function words: a surface must never begin or end on one (drops synonym
# fragments like "and hypertension"). Distinct from STOPLIST, which holds common
# nouns (heart, blood) that are illegal alone but legal inside "heart attack".
EDGE_STOPWORDS = {
    "and", "or", "the", "a", "an", "of", "in", "to", "for", "with", "without",
    "not", "by", "on", "at", "as", "from", "due",
}

# Common English / ambiguous single words that also appear as medical surfaces and
# would fire on ordinary prose. Multi-word surfaces are specific and skip this gate.
STOPLIST = {
    "cold", "gas", "aids", "male", "female", "man", "woman", "death", "pain", "mass",
    "stress", "cancer", "tumor", "tumour", "wound", "burn", "cut", "fall", "shock",
    "cough", "fever", "rash", "chill", "ache", "sick", "well", "good", "bad", "high",
    "low", "old", "new", "age", "born", "birth", "life", "blood", "bone", "skin",
    "eye", "ear", "arm", "leg", "hand", "foot", "head", "face", "back", "chest",
    "heart", "lung", "liver", "brain", "colon", "spot", "lump", "growth", "sore",
    "flat", "hard", "soft", "cost", "loss", "gain", "care", "test", "type", "class",
    "grade", "stage", "level", "rate", "size", "form", "unit", "case", "code", "name",
    "date", "time", "year", "state", "county", "city", "area", "zone", "site",
    "black", "white", "brown", "green", "yellow", "orange", "silver", "gold",
    "acute", "chronic", "mild", "severe", "normal", "positive", "negative",
    "the", "and", "for", "with", "not", "all", "any", "one", "two", "may",
}


def _acceptable(surface: str) -> bool:
    toks = surface.split()
    if not toks or len(toks) > MAX_NGRAM:
        return False
    if toks[0] in EDGE_STOPWORDS or toks[-1] in EDGE_STOPWORDS:
        return False
    if len(toks) == 1:
        t = toks[0]
        if t in ALLOW_SHORT:
            return True
        if len(t) < 4 or t in STOPLIST or t.isdigit():
            return False
    return True


def _iter_mondo(*, synonyms: bool) -> Iterator[Tuple[str, str, str]]:
    """Preferred labels (``synonyms=False``) or synonyms (``synonyms=True``).

    Split into two passes so preferred labels are indexed as the authoritative
    surface/canonical before the noisier synonym set is layered underneath.
    """
    csv.field_size_limit(10**7)
    with _MONDO.open("r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if len(row) < 3 or (len(row) > 4 and row[4].strip().upper() == "TRUE"):
                continue
            code, preferred = row[0].strip(), row[1].strip().strip('"')
            if not preferred:
                continue
            if synonyms:
                # Pipe is MONDO's only synonym separator; commas occur *inside* terms
                # ("enteritis, transmissible, of turkeys"). Splitting on comma shreds
                # them into junk fragments ("Center", "Blue") that then match prose.
                for syn in row[2].strip().strip('"').split("|"):
                    if syn.strip():
                        yield syn.strip(), preferred, code
            else:
                yield preferred, preferred, code


def _iter_rxnorm() -> Iterator[Tuple[str, str, str]]:
    with _RXNORM.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            cols = line.rstrip("\n").split("|")
            if len(cols) < 15 or cols[12] not in VALID_TTYS:
                continue
            name = clean_drug_name(cols[14].strip().lower())
            if name:
                yield name, name, cols[0].strip()


def _iter_chv() -> Iterator[Tuple[str, str, str]]:
    with _CHV.open("r", encoding="utf-8", errors="ignore") as f:
        for row in csv.reader(f):
            if len(row) < 4 or not row[1].strip() or not row[3].strip():
                continue
            yield row[1].strip(), row[3].strip(), row[0].strip()  # lay term, umls pref, cui


def build() -> Dict:
    terms: Dict[str, CanonicalTerm] = {}
    typed_surfaces: Dict[str, Set[str]] = {MEDICAL_CONDITION: set(), MEDICATION_NAME: set()}

    def add(surface_raw: str, entity: str, canonical: str, code: str, source: str) -> None:
        s = normalize_term(surface_raw)
        if not _acceptable(s) or s in terms:  # typed backbones added before CHV -> they win
            return
        terms[s] = CanonicalTerm(entity, canonical, code, source)
        typed_surfaces[entity].add(s)

    # Precedence via first-wins: authoritative disease labels, then drug names, then
    # noisy disease synonyms (so a drug like "aspirin" is not claimed by a MONDO synonym).
    for surface, canonical, code in _iter_mondo(synonyms=False):
        add(surface, MEDICAL_CONDITION, canonical, code, "mondo")
    for surface, canonical, code in _iter_rxnorm():
        add(surface, MEDICATION_NAME, canonical, code, "rxnorm")
    for surface, canonical, code in _iter_mondo(synonyms=True):
        add(surface, MEDICAL_CONDITION, canonical, code, "mondo")
    # CHV: type each lay term by its UMLS-preferred-name landing on a known surface.
    for lay, umls_pref, cui in _iter_chv():
        key = normalize_term(umls_pref)
        if key in typed_surfaces[MEDICAL_CONDITION]:
            add(lay, MEDICAL_CONDITION, umls_pref, cui, "chv")
        elif key in typed_surfaces[MEDICATION_NAME]:
            add(lay, MEDICATION_NAME, umls_pref, cui, "chv")

    max_ngram = min(MAX_NGRAM, max((len(s.split()) for s in terms), default=1))
    return {
        "max_ngram": max_ngram,
        "terms": {s: [t.entity, t.canonical, t.code, t.source] for s, t in terms.items()},
    }


if __name__ == "__main__":
    artifact = build()
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    counts: Dict[str, int] = {}
    for v in artifact["terms"].values():
        counts[v[0]] = counts.get(v[0], 0) + 1
    print(f"Wrote {len(artifact['terms']):,} surfaces (max_ngram={artifact['max_ngram']}) -> {_OUT}")
    print("  by entity:", counts)
