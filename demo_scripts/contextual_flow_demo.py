#!/usr/bin/env python3
"""Deterministic + contextual fusion demo."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Union

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "src"
for _p in (_SRC, REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from seiba_risk_scanner import SeibaScanner
from utils import reader

OUTPUT_DIR = REPO_ROOT / "demo_scripts" / "local_runs"

SAMPLE_NOTE = """
Billing contacts:
Primary: jane.doe@hospital.example.org
Secondary: billing-team@hospital.example.org
Notes: callback requested for invoice #9921.
"""
SAMPLE_FILE = reader.read_text_file(
    str(REPO_ROOT / "test_data/unstructured/pii_confidential_customer_service.txt")
)
SAMPLE_STRUCTURED_DICT = {
    "email": "case.manager@hospital.example.org",
    "phone": "(310) 555-1234",
    "memo": "Fax documents to fax@clinic.example when ready.",
}
STRUCTURED_JSON_FIXTURE = REPO_ROOT / "test_data/structured/sample_records.json"


def load_structured_json(path: Union[str, Path]) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    sdk = SeibaScanner(verbose=True)

    note_result = sdk.classify_text(SAMPLE_NOTE.strip())
    print("=== Inline narrative ===\n")
    print(note_result.model_dump_json(indent=2))
    print(f"\nTotal detections: {len(note_result.detections)}")

    text_result = sdk.classify_text(SAMPLE_FILE)
    print("\n=== Unstructured file ===\n")
    print(text_result.model_dump_json(indent=2))
    print(f"\nTotal detections: {len(text_result.detections)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "pii_confidential_v1.json"
    output_path.write_text(text_result.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nResults saved to {output_path.resolve()}")

    structured_dict_result = sdk.classify_structured_text(SAMPLE_STRUCTURED_DICT)
    print("\n=== Structured dict ===\n")
    print(structured_dict_result.model_dump_json(indent=2))

    if STRUCTURED_JSON_FIXTURE.is_file():
        structured_file_result = sdk.classify_structured_text(load_structured_json(STRUCTURED_JSON_FIXTURE))
        print("\n=== Structured JSON file ===\n")
        print(structured_file_result.model_dump_json(indent=2))
        out_struct = OUTPUT_DIR / "structured_contextual_from_json.json"
        out_struct.write_text(structured_file_result.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nStructured results saved to {out_struct.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except ModuleNotFoundError:
        print("Run from repo root after: pip install -e .", file=sys.stderr)
        raise SystemExit(1) from None
