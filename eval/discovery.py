from __future__ import annotations

from pathlib import Path
from typing import List, Optional


def resolve_gold_dir(
    repo_root: Path,
    *,
    gold_dir_arg: Optional[str] = None,
) -> Path:
    """Resolve gold directory: CLI override > ACTIVE file > unstructured_v2."""
    if gold_dir_arg:
        return (repo_root / gold_dir_arg).resolve()

    active_file = repo_root / "eval" / "ground_truth" / "ACTIVE"
    if active_file.is_file():
        name = active_file.read_text(encoding="utf-8").strip()
        if name:
            candidate = repo_root / "eval" / "ground_truth" / name
            if candidate.is_dir():
                return candidate.resolve()

    return (repo_root / "eval" / "ground_truth" / "unstructured_v2").resolve()


def discover_gold_files(gold_dir: Path) -> List[Path]:
    """Find top-level *.gold.jsonl under gold_dir (sorted, stable).

    Nested copies (e.g. llm_test_gold/) are ignored so source_file names do not collide.
    """
    if not gold_dir.is_dir():
        raise FileNotFoundError(f"Gold directory not found: {gold_dir}")
    paths = sorted(gold_dir.glob("*.gold.jsonl"))
    if not paths:
        raise FileNotFoundError(f"No gold files found under: {gold_dir}")
    return paths
