#!/usr/bin/env python3
"""NER on/off comparison demo for unstructured samples."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "src"
for _p in (_SRC, REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from seiba_risk_scanner import SeibaScanner
from seiba_risk_scanner.classification_engine.pipeline_models import PipelineStageResult

UNSTRUCTURED_DIR = REPO_ROOT / "test_data" / "unstructured"
OUTPUT_DIR = REPO_ROOT / "demo_scripts" / "local_runs"


def classify_text_with_ner(text: str, *, verbose: bool = True) -> tuple[PipelineStageResult, float]:
    sdk = SeibaScanner(verbose=verbose)
    start = time.perf_counter()
    result = sdk.classify_text(text)
    return result, time.perf_counter() - start


def classify_text_skip_ner(text: str, *, verbose: bool = False) -> tuple[PipelineStageResult, float]:
    sdk = SeibaScanner(verbose=verbose, skip_ner=True)
    start = time.perf_counter()
    result = sdk.classify_text(text)
    return result, time.perf_counter() - start


def list_unstructured_txt_files(unstructured_dir: Path) -> list[Path]:
    if not unstructured_dir.is_dir():
        raise FileNotFoundError(f"Missing unstructured test dir: {unstructured_dir}")
    files = sorted(path for path in unstructured_dir.iterdir() if path.is_file() and path.suffix.lower() == ".txt")
    if not files:
        raise FileNotFoundError(f"No .txt files under {unstructured_dir}")
    return files


def save_run_artifact(
    *,
    source_stem: str,
    source_path: Path,
    text: str,
    full: PipelineStageResult,
    skip_ner: PipelineStageResult,
    elapsed_full: float,
    elapsed_skip: float,
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"ner_flow_{source_stem}_run.json"
    payload = {
        "source_file": str(source_path.resolve()),
        "text_length_chars": len(text),
        "timings_seconds": {
            "full_pipeline": round(elapsed_full, 6),
            "skip_ner": round(elapsed_skip, 6),
        },
        "full_pipeline": full.model_dump(mode="json"),
        "skip_ner": skip_ner.model_dump(mode="json"),
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NER flow demo on unstructured test_data sample.")
    parser.add_argument("--file", type=Path, default=None, help="Path to a .txt file")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for random file selection")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)

    chosen = args.file.resolve() if args.file is not None else rng.choice(list_unstructured_txt_files(UNSTRUCTURED_DIR))
    if not chosen.is_file():
        raise FileNotFoundError(f"Not a file: {chosen}")

    text = chosen.read_text(encoding="utf-8")
    print(f"Source: {chosen}")
    print(f"Characters: {len(text)}\n")

    full, elapsed_full = classify_text_with_ner(text, verbose=True)
    print(f"classify_text (full pipeline): {elapsed_full:.3f}s")
    print(f"stage={full.stage!r} detections={len(full.detections)}")

    no_ner, elapsed_skip = classify_text_skip_ner(text, verbose=False)
    print(f"classify_text (skip_ner=True): {elapsed_skip:.3f}s")
    print(f"stage={no_ner.stage!r} detections={len(no_ner.detections)}")

    artifact = save_run_artifact(
        source_stem=chosen.stem,
        source_path=chosen,
        text=text,
        full=full,
        skip_ner=no_ner,
        elapsed_full=elapsed_full,
        elapsed_skip=elapsed_skip,
    )
    print(f"\nRun artifact saved to {artifact.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except ModuleNotFoundError:
        print("Run from repo root after: pip install -r requirements.txt", file=sys.stderr)
        raise SystemExit(1) from None
