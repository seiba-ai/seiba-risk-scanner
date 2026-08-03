"""Source-attributed scrubbing: origin routes each replacement back to its own input."""

from __future__ import annotations

import pytest

from seiba_risk_scanner import SeibaScanner
from seiba_risk_scanner.assessment import ReadinessAssessor
from seiba_risk_scanner.assessment.runner import scan_paths
from seiba_risk_scanner.policy import scrub_documents, scrub_rows, scrub_text

ALICE = "Patient Alice Brown, SSN 123-45-6789, seen today."
BOB = "Contact bob@example.com about the referral please."


@pytest.fixture(scope="module")
def scanner() -> SeibaScanner:
    return SeibaScanner(skip_ner=True)


def _plan(scanner: SeibaScanner, docs: dict[str, str]):
    results = [scanner.classify_text(t, source_id=n) for n, t in docs.items()]
    return ReadinessAssessor().assess(results, labels=list(docs)).policy_plan


def test_two_documents_scrub_against_their_own_offsets(scanner):
    docs = {"alice.txt": ALICE, "bob.txt": BOB}
    out = scrub_documents(_plan(scanner, docs), docs)

    assert "123-45-6789" not in out["alice.txt"]
    assert out["alice.txt"].startswith("Patient Alice Brown")  # bob's span never lands here
    assert "bob@example.com" not in out["bob.txt"]


def test_pooled_records_raise_instead_of_corrupting(scanner):
    docs = {"alice.txt": ALICE, "bob.txt": BOB}
    with pytest.raises(ValueError, match="span 2 sources"):
        scrub_text(ALICE, _plan(scanner, docs).records)


def test_two_tables_sharing_a_column_and_row_stay_separate(scanner):
    left, right = [{"mrn": "BH-MRN-789456"}], [{"mrn": "BH-MRN-111222"}]
    sources = {"dirty.csv": left, "clean.csv": right}
    results = [
        scanner.classify_structured_text(rows, source_id=name)
        for name, rows in sources.items()
    ]
    plan = ReadinessAssessor().assess(results, labels=list(sources)).policy_plan

    out = scrub_documents(plan, sources)
    assert out["dirty.csv"][0]["mrn"] != "BH-MRN-789456"
    assert out["clean.csv"][0]["mrn"] != "BH-MRN-111222"
    assert {r.origin.source_id for r in plan.records} == {"dirty.csv", "clean.csv"}


def test_same_filename_in_two_folders_keeps_distinct_ids(scanner, tmp_path):
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "notes.txt").write_text(f"SSN 123-45-678{len(folder)}")

    results, labels = scan_paths([tmp_path], scanner)
    ids = {d.origin.source_id for r in results for d in r.detections}

    assert labels == ["notes.txt", "notes.txt"]  # label stays readable
    assert len(ids) == 2  # id stays unique


def test_bare_string_still_scrubs_without_a_source(scanner):
    text = "Call 617-555-0143 now."
    plan = ReadinessAssessor(min_population=0).assess(scanner.classify_text(text)).policy_plan

    assert "617-555-0143" not in scrub_text(text, plan.records)
    assert plan.records[0].origin.source_id.startswith("doc-")


def test_wrong_source_and_stale_span_raise(scanner):
    plan = _plan(scanner, {"alice.txt": ALICE})

    with pytest.raises(ValueError, match="no records for source"):
        scrub_text(ALICE, plan.records, "not-a-real-source")
    with pytest.raises(ValueError, match="stale or wrong source"):
        scrub_text("A completely different document entirely!", plan.records, "alice.txt")


def test_scrub_documents_rejects_an_unsupplied_source(scanner):
    plan = _plan(scanner, {"alice.txt": ALICE, "bob.txt": BOB})

    with pytest.raises(ValueError, match="not supplied"):
        scrub_documents(plan, {"alice.txt": ALICE})


def test_rescanning_scrubbed_output_finds_no_identifiers(scanner):
    docs = {"alice.txt": ALICE, "bob.txt": BOB}
    out = scrub_documents(_plan(scanner, docs), docs)

    residual = [
        d.text
        for name, text in out.items()
        for d in scanner.classify_text(text, source_id=name).detections
    ]
    assert not [t for t in residual if "123-45-6789" in t or "bob@example.com" in t]


def test_origin_survives_into_the_plan_and_report_json(scanner):
    report = ReadinessAssessor().assess(
        [scanner.classify_text(ALICE, source_id="alice.txt")], labels=["alice.txt"]
    )
    dumped = report.model_dump()

    assert dumped["policy_plan"]["records"][0]["origin"]["source_id"] == "alice.txt"
    assert dumped["findings"][0]["detection"]["origin"]["source_label"] == "alice.txt"


def test_scrub_rows_refuses_a_non_tabular_record(scanner):
    plan = _plan(scanner, {"alice.txt": ALICE})

    with pytest.raises(ValueError, match="not tabular"):
        scrub_rows([{"note": ALICE}], plan.records, "alice.txt")
