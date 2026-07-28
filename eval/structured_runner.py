"""Structured (JSON-rows) eval: synthetic fixtures + cell-keyed gold.

Structured detections carry cell-local offsets, so every cell would start at 0 and
spans from different cells could match each other. Each cell is therefore given a
disjoint offset window before scoring, which keeps the flat scorer correct and lets
this reuse the unstructured matchers/metrics unchanged.

    python3 -m eval.structured_runner --generate   # (re)write fixtures + gold
    python3 -m eval.structured_runner              # score spacy vs openmed
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

_repo_root = Path(__file__).resolve().parents[1]
for _p in (_repo_root / "src", _repo_root):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from eval.metrics import (  # noqa: E402
    macro_from_entity_metrics,
    micro_from_entity_metrics,
    prf1_from_counts,
)
from eval.scoring import score_predictions  # noqa: E402
from eval.types import GoldSpan, PredSpan  # noqa: E402
from eval.util import ensure_dir  # noqa: E402
from seiba_risk_scanner import SeibaScanner  # noqa: E402
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (  # noqa: E402
    load_entity_configs,
    resolve_entity_alias,
)
from seiba_risk_scanner.config import ScannerConfig  # noqa: E402

DATA_DIR = _repo_root / "test_data" / "structured"
GOLD_DIR = _repo_root / "eval" / "ground_truth" / "structured_v1"
CELL_STRIDE = 1_000_000  # disjoint offset window per cell
BASELINE_PATH = _repo_root / "eval" / "baselines" / "structured_baseline.json"

# column -> (entity_id, value factory). Value is the whole cell, so gold spans the cell.
_FIRST = ["Jennifer", "Marcus", "Priya", "Diego", "Aisha", "Tomas", "Leila", "Noah"]
_LAST = ["Whitfield", "Okonkwo", "Ramaswamy", "Herrera", "Nakamura", "Boateng", "Lindqvist", "Ali"]
_CITY = ["Boston", "Austin", "Denver", "Seattle", "Miami", "Portland", "Atlanta", "Phoenix"]
_STATE = ["MA", "TX", "CO", "WA", "FL", "OR", "GA", "AZ"]
_EMPLOYER = ["TechCorp Industries", "Northwind Logistics", "Vertex Analytics", "Blue Harbor Foods"]
_HOSPITAL = ["Springfield Memorial Hospital", "Mercy Medical Center", "Lakeside Clinic"]


def _rows(n: int, seed: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build JSON rows plus the gold cells they contain (gold is exact by construction)."""
    rnd = random.Random(seed)
    rows: List[Dict[str, Any]] = []
    gold: List[Dict[str, Any]] = []
    for i in range(n):
        full_name = f"{rnd.choice(_FIRST)} {rnd.choice(_LAST)}"
        city = rnd.choice(_CITY)
        state = _STATE[_CITY.index(city)]
        row = {
            "patient_name": full_name,
            "email": f"{full_name.split()[0].lower()}.{full_name.split()[1].lower()}@example.com",
            "phone": f"(617) 555-{1000 + i:04d}",
            "ssn": f"{200 + i % 600:03d}-45-{6000 + i:04d}",
            "city": city,
            "state": state,
            "zip_code": f"{2000 + i % 8000:05d}",
            "visit_date": f"2024-0{1 + i % 9}-1{i % 9}",
            "employer": rnd.choice(_EMPLOYER),
            "facility": rnd.choice(_HOSPITAL),
            "account_ref": f"ACC-{700000 + i}",
            "amount_usd": f"{100 + i * 7}.{i % 100:02d}",
        }
        rows.append(row)
        for key, eid in (
            ("patient_name", "pii_entity_ontology::person_names"),
            ("email", "pii_entity_ontology::email_address"),
            ("phone", "pii_entity_ontology::phone_number"),
            ("ssn", "pii_entity_ontology::ssn"),
            ("city", "pii_entity_ontology::city"),
            ("state", "pii_entity_ontology::state"),
            ("zip_code", "pii_entity_ontology::zip_code"),
            ("visit_date", "pii_entity_ontology::dates"),
            ("employer", "pii_entity_ontology::employer_organization"),
            ("facility", "phi_entity_ontology::hospital_names"),
            ("account_ref", "pii_entity_ontology::account_reference_number"),
        ):
            value = row[key]
            gold.append(
                {"row": i, "key": key, "start": 0, "end": len(value), "text": value, "entity_id": eid}
            )
        # amount_usd intentionally has no gold entity (distractor column)
    return rows, gold


# --- messy fixture ---------------------------------------------------------
# Real tabular exports are not one-clean-value-per-column. A cell may be empty, carry a
# field label, hold two entities, or use any of several formats. Gold is still exact by
# construction: each builder returns the cell string plus (entity_id, start, end) spans
# located inside it, so sub-cell offsets stay correct without hand annotation.

_PII = "pii_entity_ontology"
_PHI = "phi_entity_ontology"


def _span(cell: str, core: str, entity_id: str) -> Dict[str, Any]:
    start = cell.index(core)
    return {"start": start, "end": start + len(core), "text": core, "entity_id": entity_id}


def _messy_rows(n: int, seed: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rnd = random.Random(seed)
    rows: List[Dict[str, Any]] = []
    gold: List[Dict[str, Any]] = []

    for i in range(n):
        first, last = rnd.choice(_FIRST), rnd.choice(_LAST)
        cell_spans: Dict[str, List[Dict[str, Any]]] = {}

        # patient: plain, doctor-prefixed, "LAST, First", or missing
        name_style = i % 4
        if name_style == 0:
            v = f"{first} {last}"; spans = [_span(v, v, f"{_PII}::person_names")]
        elif name_style == 1:
            v = f"Dr. {first} {last}"; spans = [_span(v, f"{first} {last}", f"{_PII}::person_names")]
        elif name_style == 2:
            v = f"{last}, {first}"; spans = [_span(v, last, f"{_PII}::person_names"),
                                             _span(v, first, f"{_PII}::person_names")]
        else:
            v = rnd.choice(["", "N/A", "—"]); spans = []
        cell_spans["patient"] = spans
        patient = v

        # phone: several real formats, sometimes labelled, sometimes empty
        core = f"617-555-{1000 + i:04d}"
        phone_style = i % 5
        phone = [core, f"(617) 555-{1000 + i:04d}", f"+1 617 555 {1000 + i:04d}",
                 f"Cell: {core}", ""][phone_style]
        if phone_style == 1:
            cell_spans["phone"] = [_span(phone, phone, f"{_PII}::phone_number")]
        elif phone == "":
            cell_spans["phone"] = []
        else:
            core_here = core if "555" in core and phone_style in (0, 3) else phone
            cell_spans["phone"] = [_span(phone, core_here, f"{_PII}::phone_number")]

        # ssn: labelled, plain, masked (a real recall-hardener), or empty
        ssn_style = i % 4
        ssn_core = f"{200 + i % 600:03d}-45-{6000 + i % 4000:04d}"
        if ssn_style == 0:
            ssn = f"SSN: {ssn_core}"; cell_spans["ssn"] = [_span(ssn, ssn_core, f"{_PII}::ssn")]
        elif ssn_style == 1:
            ssn = ssn_core; cell_spans["ssn"] = [_span(ssn, ssn_core, f"{_PII}::ssn")]
        elif ssn_style == 2:
            ssn = f"XXX-XX-{6000 + i % 4000:04d}"; cell_spans["ssn"] = []  # masked: expected miss
        else:
            ssn = ""; cell_spans["ssn"] = []

        # notes: free text carrying two entities in one cell
        note_first, note_last = rnd.choice(_FIRST), rnd.choice(_LAST)
        note_phone = f"617-555-{2000 + i:04d}"
        notes = f"Contact {note_first} {note_last} at {note_phone} re: follow-up"
        cell_spans["notes"] = [
            _span(notes, f"{note_first} {note_last}", f"{_PII}::person_names"),
            _span(notes, note_phone, f"{_PII}::phone_number"),
        ]

        # mrn: labelled or plain
        mrn_core = f"{700000 + i}"
        mrn = f"MRN {mrn_core}" if i % 2 else mrn_core
        cell_spans["mrn"] = [_span(mrn, mrn_core, f"{_PHI}::medical_record_number_mrn")]

        # account: prefixed id, masked, or empty
        acct_style = i % 3
        if acct_style == 0:
            account = f"ACC-{500000 + i}"; cell_spans["account"] = [_span(account, account, f"{_PII}::account_reference_number")]
        elif acct_style == 1:
            account = f"****{7000 + i % 3000:04d}"; cell_spans["account"] = []  # masked: expected miss
        else:
            account = "N/A"; cell_spans["account"] = []

        # zip: 5-digit or ZIP+4
        zc = f"{2000 + i % 8000:05d}"
        zip_code = f"{zc}-{1000 + i % 9000:04d}" if i % 2 else zc
        cell_spans["zip_code"] = [_span(zip_code, zip_code, f"{_PII}::zip_code")]

        # distractor columns: hold no PII -> must stay empty (tests precision under noise)
        amount = f"${1000 + i * 13}.{i % 100:02d}"
        status = ["active", "pending", "closed", "in review"][i % 4]

        rows.append({
            "patient": patient, "phone": phone, "ssn": ssn, "notes": notes,
            "mrn": mrn, "account": account, "zip_code": zip_code,
            "amount_due": amount, "status": status,
        })
        for key, spans in cell_spans.items():
            for s in spans:
                gold.append({"row": i, "key": key, **s})

    return rows, gold


def generate(n: int = 40) -> None:
    ensure_dir(DATA_DIR)
    ensure_dir(GOLD_DIR)
    builders = {
        "patient_registry": (_rows, 11),
        "billing_contacts": (_rows, 29),
        "clinical_intake_messy": (_messy_rows, 47),
    }
    for name, (builder, seed) in builders.items():
        rows, gold = builder(n, seed)
        (DATA_DIR / f"{name}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        meta = {
            "_meta": {
                "file": f"{name}.json",
                "allowed_entity_ids": sorted({g["entity_id"] for g in gold}),
            }
        }
        lines = [json.dumps(meta)] + [json.dumps(g) for g in gold]
        (GOLD_DIR / f"{name}.gold.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {name}.json ({len(rows)} rows) + {name}.gold.jsonl ({len(gold)} spans)")


def _load(name: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    gold_lines = (GOLD_DIR / f"{name}.gold.jsonl").read_text(encoding="utf-8").splitlines()
    meta = json.loads(gold_lines[0])["_meta"]
    rows = json.loads((DATA_DIR / meta["file"]).read_text(encoding="utf-8"))
    return rows, [json.loads(x) for x in gold_lines[1:] if x.strip()], meta["allowed_entity_ids"]


def _cell_base(rows: List[Dict[str, Any]]) -> Dict[Tuple[int, str], int]:
    """Disjoint offset window per (row, key) so cells cannot collide when scored flat."""
    return {(r, k): i * CELL_STRIDE for i, (r, k) in enumerate((r, k) for r, row in enumerate(rows) for k in row)}


def evaluate(name: str, scanner_config: ScannerConfig) -> Dict[str, Any]:
    rows, gold_cells, allowed = _load(name)
    base = _cell_base(rows)

    # Score in the same taxonomy the scanner reports in: gold annotated as a subtype
    # (employer_organization, hospital_names) must match the parent (organization) the
    # scanner now emits under is_a. Predictions already arrive rolled up.
    configs = load_entity_configs()
    allowed = sorted({resolve_entity_alias(a, configs) for a in allowed})

    sdk = SeibaScanner(**scanner_config.model_dump(exclude_none=True, exclude={"ner_runner_override", "detector_callable"}))
    t0 = time.perf_counter()
    result = sdk.classify_structured_text(rows)
    wall = time.perf_counter() - t0

    preds: List[PredSpan] = []
    for d in result.detections:
        prov = d.provenance or {}
        off = base.get((prov.get("row"), prov.get("key")))
        if off is None:
            continue
        preds.append(
            PredSpan(start=d.start + off, end=d.end + off, text=d.text, entity_id=d.entity_id,
                     confidence=d.confidence, winner_kind=d.winner_kind, provenance={**prov, "doc": name})
        )
    golds = [
        GoldSpan(start=g["start"] + base[(g["row"], g["key"])], end=g["end"] + base[(g["row"], g["key"])],
                 text=g["text"], entity_id=resolve_entity_alias(g["entity_id"], configs), source_file=name)
        for g in gold_cells
    ]
    scored = score_predictions(golds, preds, entity_ids=set(allowed))
    return {
        "doc": name,
        "cells": len(base),
        "wall_s": wall,
        "per_entity": scored["per_entity"],
        "micro": micro_from_entity_metrics(scored["per_entity"]),
        "macro": macro_from_entity_metrics(scored["per_entity"]),
        "strict_micro": micro_from_entity_metrics(scored["per_entity_strict"]),
    }


def build_baseline(backend: str) -> Dict[str, Any]:
    """Score every structured fixture and aggregate into a checked-in baseline shape.

    Mirrors the unstructured baseline so the regression gates can stay symmetrical.
    """
    docs = sorted(p.name[: -len(".gold.jsonl")] for p in GOLD_DIR.glob("*.gold.jsonl"))
    tp = fp = fn = 0
    per_entity: Dict[str, Dict[str, float]] = {}
    cells = 0

    for doc in docs:
        result = evaluate(doc, ScannerConfig(ner_backend=backend))
        cells += result["cells"]
        for eid, em in result["per_entity"].items():
            agg = per_entity.setdefault(eid, {"tp": 0, "fp": 0, "fn": 0})
            agg["tp"] += em.counts.tp
            agg["fp"] += em.counts.fp
            agg["fn"] += em.counts.fn

    for eid, agg in per_entity.items():
        agg_tp, agg_fp, agg_fn = agg["tp"], agg["fp"], agg["fn"]
        tp, fp, fn = tp + agg_tp, fp + agg_fp, fn + agg_fn
        prf1 = prf1_from_counts(agg_tp, agg_fp, agg_fn)
        agg.update(
            {
                "support": agg_tp + agg_fn,
                "precision": prf1.precision,
                "recall": prf1.recall,
                "f1": prf1.f1,
            }
        )

    micro = prf1_from_counts(tp, fp, fn)
    return {
        "config": {"ner_backend": backend, "docs": docs, "cells": cells},
        "headline": {
            "micro": {"precision": micro.precision, "recall": micro.recall, "f1": micro.f1},
            "matcher": "type_overlap",
        },
        "per_entity": dict(sorted(per_entity.items())),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Structured (JSON rows) eval.")
    ap.add_argument("--generate", action="store_true", help="(Re)write synthetic fixtures + gold.")
    ap.add_argument("--rows", type=int, default=40)
    ap.add_argument("--ner-backend", default=None, help="Score a single backend (default: spacy + openmed).")
    ap.add_argument(
        "--update-baseline",
        action="store_true",
        default=False,
        help="Write eval/baselines/structured_baseline.json for --ner-backend (default spacy).",
    )
    args = ap.parse_args()

    if args.update_baseline:
        backend = args.ner_backend or "spacy"
        baseline = build_baseline(backend)
        ensure_dir(BASELINE_PATH.parent)
        BASELINE_PATH.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        micro = baseline["headline"]["micro"]
        print(
            f"wrote {BASELINE_PATH.relative_to(_repo_root)} (backend={backend}, "
            f"cells={baseline['config']['cells']}, F1={micro['f1']:.4f})"
        )
        return 0

    if args.generate:
        generate(args.rows)
        return 0

    backends = [args.ner_backend] if args.ner_backend else ["spacy", "openmed"]
    docs = sorted(p.name[: -len(".gold.jsonl")] for p in GOLD_DIR.glob("*.gold.jsonl"))
    for backend in backends:
        print(f"\n===== STRUCTURED EVAL — ner_backend={backend} =====")
        agg_cells = agg_wall = 0.0
        for doc in docs:
            r = evaluate(doc, ScannerConfig(ner_backend=backend))
            agg_cells += r["cells"]
            agg_wall += r["wall_s"]
            m, s = r["micro"], r["strict_micro"]
            print(f"  {doc:20} cells={r['cells']:4}  P={m.precision:.3f} R={m.recall:.3f} F1={m.f1:.3f}"
                  f"  | strictF1={s.f1:.3f}  | {r['wall_s']:.2f}s")
            for eid in sorted(r["per_entity"]):
                em = r["per_entity"][eid]
                print(f"      {eid:48} P={em.prf1.precision:.3f} R={em.prf1.recall:.3f} "
                      f"F1={em.prf1.f1:.3f} sup={em.counts.tp + em.counts.fn}")
        print(f"  TOTAL cells={int(agg_cells)}  wall={agg_wall:.2f}s  ({agg_wall/agg_cells*1000:.1f} ms/cell)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
