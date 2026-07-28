#!/usr/bin/env python3
"""Deterministic-only pipeline demo."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "src"
for _p in (_SRC, REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from seiba_risk_scanner import SeibaScanner
from utils import reader

OUTPUT_DIR = REPO_ROOT / "demo_scripts" / "local_runs"
SAMPLE_FILE = reader.read_text_file(
    str(REPO_ROOT / "test_data/unstructured/pii_confidential_customer_service.txt")
)


def main() -> None:
    sdk = SeibaScanner(verbose=True)
    result = sdk.classify_deterministic_text(SAMPLE_FILE)
    json_output = result.model_dump_json(indent=2)
    print(json_output)
    print(f"\nTotal detections: {len(result.detections)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "pii_confidential_customer_service.json"
    output_path.write_text(json_output, encoding="utf-8")
    print(f"\nResults saved to {output_path.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except ModuleNotFoundError:
        print("Run from repo root after: pip install -e .", file=sys.stderr)
        raise SystemExit(1) from None
