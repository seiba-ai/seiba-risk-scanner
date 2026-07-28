"""Shared helpers for eval runners and batch tools."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional


def bootstrap_repo_paths(repo_root: Path) -> None:
    parent = repo_root.parent
    src = repo_root / "src"
    for path in (parent, repo_root, src):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def model_slug(model_id: str) -> str:
    return model_id.replace("/", "__")


def now_run_id(*parts: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if not parts:
        return stamp
    return stamp + "".join(f"-{part}" for part in parts if part)


def ms_per_1k_chars(wall_s: float, char_len: int) -> float:
    if char_len <= 0:
        return 0.0
    return (wall_s / (char_len / 1000.0)) * 1000.0


def git_sha(repo_root: Path) -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or None
    except Exception:
        return None


def discover_txt(input_dir: Path, only: Optional[set[str]] = None) -> List[Path]:
    files = sorted(input_dir.glob("*.txt"))
    if only:
        files = [path for path in files if path.name in only]
        missing = only - {path.name for path in files}
        if missing:
            raise FileNotFoundError(f"Requested docs not found in {input_dir}: {sorted(missing)}")
    if not files:
        raise FileNotFoundError(f"No .txt files found in {input_dir}")
    return files
