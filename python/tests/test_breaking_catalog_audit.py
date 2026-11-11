"""Full-model coverage cannot be inferred from a selected or interrupted run."""

import json
import shutil

import pytest

from grn_memory.catalog_validation import ROOT
from scripts import audit_breaking_catalog as auditor


EVIDENCE = ROOT/"results/catalog-breaking-original-completed"
REVISION = "70a3afad61357e94873ff62a7300c099b4c7ae3e"
CATALOG = json.loads((ROOT/"models/catalog.json").read_text())["models"]


def entry(network):
    return next(e for e in CATALOG if e["network"] == network)


@pytest.fixture(autouse=True)
def source_inventory(monkeypatch):
    # CI may use a shallow checkout. The actual Git-object comparison is also
    # exercised by the documented local CLI audit before publication.
    report = json.loads((EVIDENCE/"BIOMD0000000031.json").read_text())
    hashes = {"grn_memory/"+name: sha for name, sha in report["implementation_sha256"].items()}
    def lookup(revision, name):
        assert revision == REVISION
        return hashes[name]
    monkeypatch.setattr(auditor, "source_hash", lookup)


def editable_model(network, tmp_path):
    path = EVIDENCE/(entry(network)["biomodel_id"]+".json")
    report = json.loads(path.read_text())
    shutil.copy2(path, tmp_path/path.name)
    for group in report["evidence_archives"].values():
        for item in group:
            target = tmp_path/item["file"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(EVIDENCE/item["file"], target)
    return report, tmp_path/path.name


def save(report, path):
    path.write_text(json.dumps(report))


def test_complete_native_model_retains_all_cases_and_branches():
    result = auditor.audit_model(EVIDENCE, entry(19), REVISION)
    assert result["cases"] == result["passed_cases"] == 14
    assert result["branches"] == result["passed_branches"] == 137
    assert result["complete_conditional_search"] and result["all_numerical_validations_passed"]


def test_zero_candidate_delay_model_still_requires_validated_control():
    result = auditor.audit_model(EVIDENCE, entry(14), REVISION)
    assert result["cases"] == 0 and result["branches"] == result["passed_branches"] == 1
    assert result["all_numerical_validations_passed"]


def test_attempted_initial_cases_do_not_resolve_failed_continuations():
    result = auditor.audit_model(EVIDENCE, entry(3), REVISION)
    assert result["cases"] == 8 and result["passed_cases"] == 6
    assert result["complete_initial_case_coverage"]
    assert not result["complete_conditional_search"] and not result["all_numerical_validations_passed"]
    assert len(result["unresolved_conditional_decisions"]) == 2
    assert result["incomplete_branches"] == len(result["failed_branches"]) == 4


def test_running_model_is_rejected_even_when_cases_are_present(tmp_path):
    report, path = editable_model(19, tmp_path)
    report["status"] = "running"
    save(report, path)
    with pytest.raises(ValueError, match="Only terminal"):
        auditor.audit_model(tmp_path, entry(19), REVISION)


def test_partial_case_selection_is_rejected(tmp_path):
    report, path = editable_model(19, tmp_path)
    del report["cases"][next(iter(report["cases"]))]
    report["evaluated_cases"] -= 1
    save(report, path)
    with pytest.raises(ValueError, match="Complete initial-case coverage"):
        auditor.audit_model(tmp_path, entry(19), REVISION)


def test_zero_candidates_without_control_cannot_pass(tmp_path):
    report, path = editable_model(17, tmp_path)
    report["evidence_archives"]["branches"] = []
    report["evaluated_unique_branches"] = 0
    save(report, path)
    with pytest.raises(ValueError, match="Full untreated control"):
        auditor.audit_model(tmp_path, entry(17), REVISION)


def test_changed_producer_source_is_rejected(monkeypatch):
    monkeypatch.setattr(auditor, "source_hash", lambda *args: "0"*64)
    with pytest.raises(ValueError, match="Worker source differs"):
        auditor.audit_model(EVIDENCE, entry(19), REVISION)


def test_selected_models_cannot_be_promoted_to_catalog_coverage():
    result = auditor.audit(EVIDENCE, REVISION, [17, 19])
    assert result["complete_selected_initial_case_coverage"] and result["complete_selected_conditional_search"]
    assert result["all_numerical_validations_passed"]
    assert not result["complete_catalog_initial_case_coverage"] and not result["complete_catalog_conditional_search"]
    assert result["catalog_model_count"] == 35 and result["totals"]["models"] == 2


def test_default_catalog_audit_requires_every_model():
    with pytest.raises(FileNotFoundError):
        auditor.audit(EVIDENCE, REVISION)
