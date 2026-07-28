"""The SDK path: data files in, report (and written JSON + Markdown) out."""
from __future__ import annotations

import csv
import json

import pytest

from seiba_risk_scanner import SeibaScanner
from seiba_risk_scanner.assessment import report_from_paths, scan_paths
from seiba_risk_scanner.assessment.runner import _expand


@pytest.fixture(scope="module")
def scanner():
    # Regex only: these tests are about file handling and wiring, not detection quality.
    return SeibaScanner(skip_ner=True)


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / "notes.txt").write_text(
        "Contact Jane Doe at jane.doe@example.com or 617-555-0142.", encoding="utf-8"
    )
    (tmp_path / "readme.md").write_text("Reach us on 617-555-0199.", encoding="utf-8")
    # Enough rows that the policy table truncates, so the "rest is in the JSON" pointer fires.
    (tmp_path / "people.json").write_text(
        json.dumps([{"email": f"u{i}@example.com", "zip": f"021{i:02d}"} for i in range(15)]),
        encoding="utf-8",
    )
    with (tmp_path / "rows.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["email", "zip"])
        writer.writerow(["a@example.com", "10001"])
    (tmp_path / "ignore.log").write_text("not scanned", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.txt").write_text("SSN 123-45-6789", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- discovery


def test_expand_finds_supported_files_recursively_and_skips_others(data_dir):
    names = {p.name for p in _expand([data_dir])}
    assert names == {"notes.txt", "readme.md", "people.json", "rows.csv", "deep.txt"}


def test_expand_accepts_individual_files(data_dir):
    assert [p.name for p in _expand([data_dir / "notes.txt"])] == ["notes.txt"]


def test_expand_ignores_an_unsupported_file_given_directly(data_dir):
    assert _expand([data_dir / "ignore.log"]) == []


# --------------------------------------------------------------------------- scanning


def test_each_source_becomes_one_result_with_its_filename_as_label(data_dir, scanner):
    results, labels = scan_paths([data_dir], scanner)
    assert len(results) == len(labels) == 5
    assert set(labels) == {"notes.txt", "readme.md", "deep.txt", "people.json", "rows.csv"}


def test_text_and_tables_are_scanned_in_one_pass(data_dir, scanner):
    results, labels = scan_paths([data_dir], scanner)
    found = {
        row.entity
        for result, label in zip(results, labels)
        for row in result.detections
    }
    assert "email_address" in found  # from both the .txt and the .json
    assert "ssn" in found  # from the nested .txt


def test_max_rows_limits_tabular_input(data_dir, scanner):
    results, labels = scan_paths([data_dir], scanner, max_rows=1)
    people = results[labels.index("people.json")]
    rows = {row.provenance.get("row") for row in people.detections if row.provenance}
    assert rows == {0}


def test_csv_is_read_as_rows(data_dir, scanner):
    results, labels = scan_paths([data_dir / "rows.csv"], scanner)
    assert any(row.entity == "email_address" for row in results[0].detections)


# --------------------------------------------------------------------------- report


def test_report_from_paths_produces_a_report(data_dir, scanner):
    report = report_from_paths([data_dir], scanner=scanner)
    assert report.findings
    assert report.policy_plan is not None  # policy is on by default


def test_writing_emits_both_files_and_the_markdown_cites_the_json(data_dir, scanner, tmp_path):
    out = tmp_path / "out"
    report_from_paths([data_dir], scanner=scanner, out_dir=out, stem="run1")
    written = {p.name for p in out.iterdir()}
    assert written == {"run1.json", "run1.md"}
    # The pointer to "every record is in the JSON" has to name the file that was written.
    assert "run1.json" in (out / "run1.md").read_text(encoding="utf-8")


def test_written_json_round_trips(data_dir, scanner, tmp_path):
    out = tmp_path / "out"
    report_from_paths([data_dir], scanner=scanner, out_dir=out, stem="run1")
    payload = json.loads((out / "run1.json").read_text(encoding="utf-8"))
    assert payload["findings"] and "exposure_index" in payload


def test_nothing_is_written_unless_an_output_directory_is_given(data_dir, scanner, tmp_path):
    out = tmp_path / "out"
    report_from_paths([data_dir], scanner=scanner)
    assert not out.exists()


def test_a_path_with_no_scannable_files_fails_loudly(tmp_path, scanner):
    (tmp_path / "only.log").write_text("nothing here", encoding="utf-8")
    with pytest.raises(ValueError, match="No .txt"):
        report_from_paths([tmp_path], scanner=scanner)
