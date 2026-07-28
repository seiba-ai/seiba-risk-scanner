from __future__ import annotations

import sys
from pathlib import Path

# Repo root is the package; parent must be on path for `seiba_risk_scanner.*`.
repo_root = Path(__file__).resolve().parents[1]
parent = repo_root.parent
for path in (parent, repo_root):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
