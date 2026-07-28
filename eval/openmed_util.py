"""Shared OpenMed helpers for eval runners."""

from __future__ import annotations

from typing import Any, Dict, List


def openmed_eager_config():
    from openmed import OpenMedConfig

    return OpenMedConfig(torch_attention_backend="eager")


def entities_from_result(result) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if result is None:
        return out
    for ent in getattr(result, "entities", []) or []:
        out.append(
            {
                "label": getattr(ent, "label", None),
                "text": getattr(ent, "text", None),
                "start": getattr(ent, "start", None),
                "end": getattr(ent, "end", None),
                "confidence": getattr(ent, "confidence", getattr(ent, "score", None)),
                "metadata": getattr(ent, "metadata", None),
            }
        )
    return out
