"""Generalization: coarsen a value instead of destroying it.

seiba owns this action. OpenMed's policy vocabulary is closed over
``keep|redact|replace|mask|hash|format_preserve`` and its generalization transforms live
inside ``enforce_kanon``'s corpus-level lattice search with no per-value entry point, so a
"round this date to its year" action has nowhere to come from. Choosing a *level* across a
whole corpus stays delegated to ``openmed.risk.enforce_kanon``; this module only applies one.

Default levels follow HIPAA Safe Harbor, which prescribes generalization rather than deletion
for exactly these fields: dates keep the year only, ages over 89 aggregate, zip codes keep
three digits. Masking them outright is over-compliance that destroys usable data.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from dateutil import parser as date_parser

# OpenMed canonical label -> the kind of ladder that applies. Labels absent here have no
# defensible coarsening: a city or street generalizes only against a geographic hierarchy,
# which was judged over-engineering, so those keep their existing action.
LABEL_KINDS: Dict[str, str] = {
    "AGE": "age",
    "DATE": "date",
    "DATE_OF_BIRTH": "date",
    "ZIPCODE": "zip",
    "GPS_COORDINATES": "coordinates",
}

# Gentlest first; the optimizer will later walk these toward a target k.
LADDERS: Dict[str, Tuple[str, ...]] = {
    "age": ("5_year_band", "10_year_band", "20_year_band"),
    "date": ("month", "year", "decade"),
    "zip": ("3_digit", "1_digit"),
    "coordinates": ("1_decimal", "integer"),
}

# Safe Harbor's own thresholds, so the default action is the compliant one.
DEFAULT_LEVELS: Dict[str, str] = {
    "age": "5_year_band",
    "date": "year",
    "zip": "3_digit",
    "coordinates": "1_decimal",
}

# Safe Harbor: ages over 89 must collapse into one bucket, or the band re-identifies.
_AGE_CEILING = 90
_DIGITS = re.compile(r"\d+")


def kind_for_label(label: Optional[str]) -> Optional[str]:
    """The generalization ladder for an OpenMed label, or None if it cannot be coarsened."""
    return LABEL_KINDS.get(label.upper()) if label else None


def _age(text: str, level: str) -> Optional[str]:
    match = _DIGITS.search(text)
    if match is None:
        return None
    value = int(match.group())
    if value >= _AGE_CEILING:
        return f"{_AGE_CEILING}+"
    width = int(level.split("_")[0])
    lower = (value // width) * width
    return f"{lower}-{lower + width - 1}"


def _date(text: str, level: str) -> Optional[str]:
    try:  # dateutil handles "March 15, 1989" and "03/15/1989" alike; OpenMed's is ISO-only
        parsed = date_parser.parse(text, fuzzy=True)
    except (ValueError, OverflowError):
        return None
    if level == "month":
        return f"{parsed.year:04d}-{parsed.month:02d}"
    if level == "year":
        return f"{parsed.year:04d}"
    return f"{(parsed.year // 10) * 10:04d}s"


def _zip(text: str, level: str) -> Optional[str]:
    digits = "".join(_DIGITS.findall(text))
    if not digits:
        return None
    keep = 3 if level == "3_digit" else 1
    return digits[:keep].ljust(keep, "0") + "*" * max(len(digits[:5]) - keep, 0)


def _coordinates(text: str, level: str) -> Optional[str]:
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return f"{value:.1f}" if level == "1_decimal" else f"{value:.0f}"


_TRANSFORMS = {"age": _age, "date": _date, "zip": _zip, "coordinates": _coordinates}


def generalize(text: str, kind: str, level: Optional[str] = None) -> Optional[str]:
    """Coarsen ``text`` one rung of ``kind``'s ladder; None when the value will not parse.

    A None result is the caller's signal to fall back to a destructive action rather than
    silently leave an identifier in place.
    """
    transform = _TRANSFORMS.get(kind)
    if transform is None:
        return None
    level = level or DEFAULT_LEVELS[kind]
    if level not in LADDERS[kind]:
        raise ValueError(f"Unknown {kind} generalization level {level!r}; use {LADDERS[kind]}")
    return transform(text, level)


# How much identifying power a value keeps at each rung. A full date of birth links against
# an outside voter roll or breach dump far better than a bare year does, so a coarse value is
# genuinely less dangerous — independently of whether it is unique inside this dataset, which
# is what k already measures.
PRECISION_FACTORS: Dict[str, Dict[str, float]] = {
    "date": {"exact": 1.0, "month": 0.8, "year": 0.6, "decade": 0.4},
    "age": {"exact": 1.0, "5_year_band": 0.8, "10_year_band": 0.6, "20_year_band": 0.4},
    "zip": {"exact": 1.0, "3_digit": 0.6, "1_digit": 0.3},
    "coordinates": {"exact": 1.0, "1_decimal": 0.6, "integer": 0.3},
}

_YEAR = re.compile(r"^\d{4}$")
_DECADE = re.compile(r"^\d{4}s$")
_MONTH = re.compile(r"^\d{4}-\d{1,2}$")
_BAND = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def _date_precision(text: str) -> str:
    if _DECADE.match(text):
        return "decade"
    if _YEAR.match(text):
        return "year"
    if _MONTH.match(text):
        return "month"
    return "exact"


def _age_precision(text: str) -> str:
    if text.strip().endswith("+"):
        return "20_year_band"  # the 90+ bucket is the coarsest thing an age can be
    band = _BAND.match(text.strip())
    if band is None:
        return "exact"
    width = int(band.group(2)) - int(band.group(1)) + 1
    return {5: "5_year_band", 10: "10_year_band", 20: "20_year_band"}.get(width, "5_year_band")


def _zip_precision(text: str) -> str:
    if "*" not in text:
        return "exact"
    kept = len("".join(_DIGITS.findall(text.split("*")[0])))
    return "3_digit" if kept >= 3 else "1_digit"


def _coordinate_precision(text: str) -> str:
    _, _, decimals = text.strip().partition(".")
    if not decimals:
        return "integer"
    return "1_decimal" if len(decimals) <= 1 else "exact"


_PRECISION = {
    "date": _date_precision,
    "age": _age_precision,
    "zip": _zip_precision,
    "coordinates": _coordinate_precision,
}


def precision_factor(text: str, label: Optional[str]) -> Tuple[float, Optional[str]]:
    """How much of its identifying power this value still holds, and the rung it sits at.

    Read from the value itself, so it works the same whether we coarsened it or the source
    data arrived that way. Returns 1.0 for anything with no precision axis — a name has no
    half-form, so only the laddered kinds can be partially identifying.
    """
    kind = kind_for_label(label)
    if kind is None:
        return 1.0, None
    level = _PRECISION[kind](text)
    return PRECISION_FACTORS[kind][level], level


__all__ = [
    "DEFAULT_LEVELS",
    "LABEL_KINDS",
    "LADDERS",
    "PRECISION_FACTORS",
    "generalize",
    "kind_for_label",
    "precision_factor",
]
