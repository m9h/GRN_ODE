"""A precision diagnostic cannot silently become independent case validation."""

import json
import shutil

import numpy as np
import pytest

from scripts import audit_taylor_paired as auditor


EVIDENCE = auditor.ROOT/"results/catalog-paired-taylor-marhl"


@pytest.fixture
def editable(tmp_path):
    shutil.copytree(EVIDENCE, tmp_path, dirs_exist_ok=True)
    return tmp_path


def change(path, mutate):
    data = json.loads(path.read_text())
    mutate(data)
    path.write_text(json.dumps(data))


def first_record(directory):
    report = json.loads((directory/"report.json").read_text())
    return directory/report["branches"][0]["file"]


def test_all_precision_convergence_retains_native_disagreement():
    result = auditor.audit(EVIDENCE)
    assert result["complete_original_failure_coverage"]
    assert result["full_protocol_branches"] == result["precision_converged_branches"] == 3
    assert result["native_agreeing_branches"] == 0
    assert result["baseline_status"] == "confirmed"
    assert not result["case_recovery_claimed"]
    assert all(row["samples"] == 30001 and row["resets"] == 998 for row in result["summaries"][1:])


def test_incomplete_run_cannot_pass(editable):
    change(editable/"report.json", lambda row: row.update(status="running"))
    with pytest.raises(ValueError, match="still running"):
        auditor.audit(editable)


def test_missing_original_failure_is_rejected(editable):
    change(editable/"report.json", lambda row: row["branches"].pop())
    with pytest.raises(ValueError, match="inventory is incomplete"):
        auditor.audit(editable)


def test_changed_saved_array_is_rejected(editable):
    with (editable/"untreated_baseline-taylor128.npz").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="Trajectory digest differs"):
        auditor.audit(editable)


def test_truncated_array_is_rejected_even_with_updated_checksum(editable):
    path = editable/"untreated_baseline-taylor128.npz"
    with np.load(path, allow_pickle=False) as data:
        arrays = {key: data[key].copy() for key in data.files}
    arrays["times"] = arrays["times"][:-1]
    arrays["values"] = arrays["values"][:-1]
    np.savez_compressed(path, **arrays)
    change(editable/"untreated_baseline.json", lambda row: row["traces"]["taylor128"].update(sha256=auditor.digest(path)))
    with pytest.raises(ValueError, match="Observation inventory differs"):
        auditor.audit(editable)


def test_changed_comparison_cannot_hide_native_mismatch(editable):
    change(first_record(editable), lambda row: row["comparisons"]["taylor192_vs_roadrunner"].update(passed=True))
    with pytest.raises(ValueError, match="comparisons do not reproduce"):
        auditor.audit(editable)


def test_missed_reset_is_rejected(editable):
    change(first_record(editable), lambda row: row["integrations"]["taylor192"].update(performed_resets=997))
    with pytest.raises(ValueError, match="Reset or segment coverage"):
        auditor.audit(editable)


def test_precision_convergence_cannot_be_reported_as_native_agreement(editable):
    change(first_record(editable), lambda row: row.update(native_agreement=True))
    with pytest.raises(ValueError, match="Diagnostic outcome differs"):
        auditor.audit(editable)
