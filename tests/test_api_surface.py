"""The declared surface is a contract: it must resolve, and stay cheap to import."""

from __future__ import annotations

import subprocess
import sys

from seiba_risk_scanner import api


def test_every_exported_name_resolves():
    assert [n for n in api.__all__ if not hasattr(api, n)] == []


def test_importing_the_surface_does_not_load_a_model():
    """A consumer wanting only validators or the gazetteer must not pay for torch.

    Checked in a fresh interpreter: torch is imported lazily inside the NER backend,
    so an eager import anywhere on the surface would only show up before any scan runs.
    """
    code = "import seiba_risk_scanner.api, sys; print('torch' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_fingerprint_identifies_code_rules_dictionary_and_model():
    fp = api.fingerprint()
    assert set(fp) == {"version", "ontologies", "gazetteer", "gazetteer_artifact",
                       "ner_backend", "ner_model"}
    assert fp["version"] == api.__version__
    assert fp["ontologies"] and fp["gazetteer"]
    assert api.fingerprint() == fp  # stable across calls
