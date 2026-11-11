"""Recovery must establish every arm, original observable and scoring gate."""

from copy import deepcopy

import pytest

from grn_memory.catalog_paired import WINDOWS, branch_id, case_branches
from grn_memory.paired_recovery import (COMPARISONS, ENGINES, REQUIRED_INTEGRATIONS,
    recover_cases, validate_comparison, validate_diagnostic_branch)


def comparison_record(error=0.1):
    return {"samples": 30001, "observables": 1, "per_observable_max_scaled_error": {"R": error},
            "max_scaled_error": error, "passed": error <= 1}


def diagnostic_fixture():
    original = {"branch_id": "branch", "specification": {"training": ["U"]},
                "reset_trains": [{"start": 50., "stop": 100., "values": {"U": 2.}}]}
    report = {"fingerprint": "signature", "model_sha256": "model", "scipy_method": "Radau",
              "integration_requests": {e: {"rtol": 1e-10, "atol": 1e-12} for e in REQUIRED_INTEGRATIONS}}
    record = {**deepcopy(original), "fingerprint": "signature", "status": "confirmed",
              "integrations": {}, "comparisons": {k: comparison_record() for k in COMPARISONS}, "windows": {}}
    for engine in REQUIRED_INTEGRATIONS:
        record["integrations"][engine] = {"request": report["integration_requests"][engine],
            "completed": True, "samples": 30001, "observables": 1}
        if engine.startswith("scipy"):
            record["integrations"][engine].update(model_sha256="model", x64=True, method="Radau", rtol=1e-10, atol=1e-12,
                absolute_time_preserved=True, expected_train_reset_counts=[499], train_reset_counts=[499],
                expected_resets=499, performed_resets=499, expected_segments=500, completed_segments=500,
                sample_count=30001)
        record["windows"][engine] = {w: {"R": {"mean": 1., "minimum": 1., "maximum": 1.}} for w in WINDOWS}
    return original, report, record


def case_fixture():
    plan = {"ucs": "U__up", "cs": "C__up", "responses": ["R"]}
    records = {}
    for spec in case_branches(plan).values():
        records[branch_id(spec)] = {"status": "confirmed", "windows": {
            engine: {w: {"R": {"mean": 1., "minimum": 1., "maximum": 1.}} for w in WINDOWS}
            for engine in ENGINES}}
    return {"case": plan}, {"case": {"status": "failed"}}, records


def test_complete_evidence_and_complete_controls_are_required():
    original, report, record = diagnostic_fixture()
    assert validate_diagnostic_branch(record, report, original, ["R"])
    plans, cases, records = case_fixture()
    result = recover_cases(plans, cases, records)["case"]
    assert result["status"] == "passed"
    assert result["scores"][ENGINES[0]]["R"]["normal"]["category"] == "unresolved_cue_effect"
    # Even a no-training sham is indispensable; success of the stimulated
    # branches cannot stand in for this missing control.
    bid = result["branches"]["none_sham"]
    del records[bid]
    result = recover_cases(plans, cases, records)["case"]
    assert result["status"] == "incomplete" and result["missing_branches"] == {"none_sham": bid}
    assert "scores" not in result


@pytest.mark.parametrize("corruption", ["missing_gate", "truncated_grid", "dropped_species",
    "unperformed_reset", "changed_schedule", "nonfinite_window", "false_pass", "missing_window"])
def test_diagnostic_cannot_promote_incomplete_or_inconsistent_evidence(corruption):
    original, report, record = diagnostic_fixture()
    if corruption == "missing_gate":
        del record["comparisons"][COMPARISONS[-1]]
    elif corruption == "truncated_grid":
        record["comparisons"][COMPARISONS[0]]["samples"] = 25001
    elif corruption == "dropped_species":
        record["comparisons"][COMPARISONS[0]]["per_observable_max_scaled_error"] = {"other": .1}
    elif corruption == "unperformed_reset":
        record["integrations"]["scipy_refined"]["train_reset_counts"] = [498]
    elif corruption == "changed_schedule":
        record["reset_trains"][0]["stop"] = 90.
    elif corruption == "nonfinite_window":
        record["windows"]["scipy_refined"]["late"]["R"]["mean"] = float("nan")
    elif corruption == "false_pass":
        record["comparisons"][COMPARISONS[0]] = comparison_record(2.)
    elif corruption == "missing_window":
        del record["windows"]["scipy_refined"]["late"]
    with pytest.raises(ValueError):
        validate_diagnostic_branch(record, report, original, ["R"])


def test_valid_failures_remain_evidence_but_do_not_recover_cases():
    original, report, record = diagnostic_fixture()
    record["status"] = "mismatch"
    record["comparisons"][COMPARISONS[0]] = comparison_record(2.)
    assert not validate_diagnostic_branch(record, report, original, ["R"])
    plans, cases, records = case_fixture()
    records[next(iter(records))]["status"] = "mismatch"
    result = recover_cases(plans, cases, records)["case"]
    assert result["status"] == "failed" and result["unconfirmed_branches"]
    assert "scores" not in result


def test_controlled_scores_are_recomputed_in_each_engine():
    plans, cases, records = case_fixture()
    spec = case_branches(plans["case"])["paired_normal"]
    # Both engines could satisfy the full-trajectory tolerance while a contrast
    # very near a scoring boundary changes category. The categorical gate is
    # therefore additional to the recorded trajectory gate.
    records[branch_id(spec)]["windows"][ENGINES[0]]["probe"]["R"] = {
        "mean": 1.0000805, "minimum": 1.0000805, "maximum": 1.0000805}
    records[branch_id(spec)]["windows"][ENGINES[1]]["probe"]["R"] = {
        "mean": 1.0000803, "minimum": 1.0000803, "maximum": 1.0000803}
    result = recover_cases(plans, cases, records)["case"]
    assert result["status"] == "mismatch"
    assert result["controlled_classification_disagreements"] == ["R"]


def test_original_passing_cases_are_not_relabelled_as_new_recoveries():
    plans, cases, records = case_fixture()
    cases["case"]["status"] = "passed"
    assert recover_cases(plans, cases, records) == {}


def test_comparison_rejects_a_fabricated_pass_flag():
    record = comparison_record(2.)
    record["passed"] = True
    with pytest.raises(ValueError, match="pass flag"):
        validate_comparison(record, ["R"])
