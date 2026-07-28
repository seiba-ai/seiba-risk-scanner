"""Apply resolved policy actions to text/cells via OpenMed primitives (no vault)."""

from __future__ import annotations

import hashlib
from typing import List, Optional, Sequence

from seiba_risk_scanner.policy.bridge import seiba_mask_token
from seiba_risk_scanner.policy.generalize import generalize, kind_for_label
from seiba_risk_scanner.policy.models import ActionRecord, PolicyPlanSection


def _hash_token(text: str, label: Optional[str]) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    prefix = (label or "VALUE").upper()
    return f"{prefix}_{digest}"


def _mask_for(record: ActionRecord) -> str:
    if record.openmed_label:
        return f"[{record.openmed_label}]"
    return seiba_mask_token(record.entity)


def apply_action_to_text(record: ActionRecord) -> ActionRecord:
    """Return a copy of ``record`` with ``replacement`` filled; may set execute_fallback.

    Class-fallback / unlabeled ``replace`` and ``format_preserve`` downgrade to mask so
    we never invent a PERSON surrogate for an ITIN or biometric.
    """
    action = record.action
    execute_fallback: Optional[str] = None

    if action == "keep":
        replacement = record.text
    elif action == "generalize":
        kind = kind_for_label(record.openmed_label)
        coarsened = (
            generalize(record.text, kind, record.generalization_level) if kind else None
        )
        if coarsened is None:  # unparseable value: never leave an identifier standing
            execute_fallback = "generalize→mask"
            replacement = _mask_for(record)
        else:
            replacement = coarsened
    elif action in {"mask", "redact"}:
        replacement = _mask_for(record)
    elif action == "hash":
        replacement = _hash_token(record.text, record.openmed_label or record.entity)
    elif action in {"replace", "format_preserve"}:
        if record.openmed_label and record.source == "openmed_action_for":
            try:
                from openmed import Anonymizer

                anon = Anonymizer(lang="en", consistent=True, seed=0)
                if action == "format_preserve" and hasattr(anon, "format_preserving_surrogate"):
                    fp = anon.format_preserving_surrogate(
                        record.text, record.openmed_label
                    )
                    replacement = fp if fp else anon.surrogate(
                        record.text, record.openmed_label
                    )
                else:
                    replacement = anon.surrogate(record.text, record.openmed_label)
            except Exception:
                execute_fallback = f"{action}→mask"
                replacement = _mask_for(record)
        else:
            execute_fallback = f"{action}→mask"
            replacement = _mask_for(record)
    else:
        # Unknown action — safe mask
        execute_fallback = f"{action}→mask"
        replacement = _mask_for(record)

    return record.model_copy(
        update={
            "replacement": replacement,
            "execute_fallback": execute_fallback or record.execute_fallback,
        }
    )


def execute_plan(plan: PolicyPlanSection) -> PolicyPlanSection:
    """Apply every record's action; no mapping vault is retained."""
    executed: List[ActionRecord] = [apply_action_to_text(r) for r in plan.records]
    return plan.model_copy(update={"records": executed, "executed": True})


def scrub_text(text: str, records: Sequence[ActionRecord]) -> str:
    """Apply replacements to ``text`` by descending span start (non-overlapping assumed)."""
    applied = [
        r if r.replacement is not None else apply_action_to_text(r) for r in records
    ]
    ordered = sorted(applied, key=lambda r: (r.start, r.end), reverse=True)
    out = text
    for record in ordered:
        if record.action == "keep" or record.replacement is None:
            continue
        if 0 <= record.start <= record.end <= len(out):
            out = out[: record.start] + record.replacement + out[record.end :]
    return out


__all__ = ["apply_action_to_text", "execute_plan", "scrub_text"]
