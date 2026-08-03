"""Apply resolved policy actions to text/cells via OpenMed primitives (no vault)."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence

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


def _for_source(records: Sequence[ActionRecord], source_id: Optional[str]) -> List[ActionRecord]:
    """Records that actually belong to ``source_id``, refusing anything unattributable.

    Offsets only mean something against their own input, so a foreign record silently
    rewrites the wrong span — and, when it shortens the text, pushes a real record out of
    bounds so its identifier survives the scrub. Both failures are invisible; refuse instead.
    """
    live = [r for r in records if r.action != "keep"]
    seen = {r.origin.source_id if r.origin else None for r in live}
    if source_id is None:
        if len(seen) > 1:
            raise ValueError(
                f"records span {len(seen)} sources {sorted(map(str, seen))}; pass source_id "
                "to pick one, or use scrub_documents()"
            )
        return live
    missing = sum(1 for r in live if r.origin is None)
    if missing:
        raise ValueError(
            f"{missing} record(s) have no origin, so they cannot be matched to {source_id!r}"
        )
    mine = [r for r in live if r.origin and r.origin.source_id == source_id]
    if live and not mine:
        # Every record belongs to some other source: a typo here would otherwise return the
        # text untouched and read as a successful scrub.
        raise ValueError(f"no records for source {source_id!r}; have {sorted(map(str, seen))}")
    return mine


def scrub_text(
    text: str, records: Sequence[ActionRecord], source_id: Optional[str] = None
) -> str:
    """Apply replacements to ``text`` by descending span start.

    Every record must match ``text`` at its recorded span; a stale or foreign span raises
    rather than being skipped, because a silently skipped record leaves an identifier in
    output the caller believes is de-identified.
    """
    applied = [
        r if r.replacement is not None else apply_action_to_text(r)
        for r in _for_source(records, source_id)
    ]
    ordered = sorted(applied, key=lambda r: (r.start, r.end), reverse=True)
    for record, nxt in zip(ordered[1:], ordered):
        if record.end > nxt.start:
            raise ValueError(f"overlapping spans: {record.entity} and {nxt.entity}")
    out = text
    for record in ordered:
        if record.replacement is None:
            continue
        if not 0 <= record.start <= record.end <= len(out):
            raise ValueError(
                f"{record.entity} span [{record.start},{record.end}] is outside a "
                f"{len(out)}-character source"
            )
        if out[record.start : record.end] != record.text:
            raise ValueError(
                f"{record.entity} span [{record.start},{record.end}] holds "
                f"{out[record.start:record.end]!r}, not {record.text!r} — stale or wrong source"
            )
        out = out[: record.start] + record.replacement + out[record.end :]
    return out


def scrub_rows(
    rows: Sequence[Mapping[str, Any]],
    records: Sequence[ActionRecord],
    source_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Rebuild table rows with scrubbed cell values.

    Tables are addressed by row/column rather than character offsets, so this replaces the
    whole cell; a cell holding two findings keeps the last one applied.
    """
    out = [dict(row) for row in rows]
    for record in _for_source(records, source_id):
        applied = record if record.replacement is not None else apply_action_to_text(record)
        origin = applied.origin
        if origin is None or origin.row is None or origin.column is None:
            raise ValueError(f"{applied.entity} has no row/column origin; it is not tabular")
        if not isinstance(origin.row, int) or not 0 <= origin.row < len(out):
            raise ValueError(
                f"{applied.entity} row {origin.row!r} is outside a {len(out)}-row table"
            )
        out[origin.row][origin.column] = applied.replacement
    return out


def scrub_documents(
    plan: PolicyPlanSection, sources: Mapping[str, Any]
) -> Dict[str, Any]:
    """Scrub every input in ``sources``, keyed by ``origin.source_id``.

    The public multi-source path: a string is scrubbed by span, a list of rows by cell.
    Sources with no findings come back unchanged.
    """
    grouped: Dict[str, List[ActionRecord]] = defaultdict(list)
    for record in plan.records:
        if record.action == "keep":
            continue
        if record.origin is None:
            raise ValueError(f"{record.entity} has no origin; rescan so sources are identified")
        grouped[record.origin.source_id].append(record)

    unknown = sorted(set(grouped) - set(sources))
    if unknown:
        raise ValueError(f"plan references sources that were not supplied: {unknown}")
    return {
        source_id: (
            scrub_text(data, grouped.get(source_id, ()), source_id)
            if isinstance(data, str)
            else scrub_rows(data, grouped.get(source_id, ()), source_id)
        )
        for source_id, data in sources.items()
    }


__all__ = [
    "apply_action_to_text",
    "execute_plan",
    "scrub_documents",
    "scrub_rows",
    "scrub_text",
]
