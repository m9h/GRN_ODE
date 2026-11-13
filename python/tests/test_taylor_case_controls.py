"""Complete controls, consistent engines and full arrays are necessary for recovery."""

from copy import deepcopy
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from grn_memory import taylor_case_controls as controls
from grn_memory import taylor_partitions as partitions


CASES = ["DAp__up--DR__up", "DAp__up--DRp__up", "DAp__up--MR__up"]


@pytest.fixture(scope="module")
def real_plan():
    return controls.make_plan(35, CASES)


def test_original_case_plan_requires_32_full_branches_with_23_additional_controls(real_plan):
    assert len(real_plan["required_branch_ids"]) == 32
    assert len(real_plan["control_branch_ids"]) == 23
    assert len(real_plan["existing_failed_partition_indices"]) == 9
    assert real_plan["existing_failed_partition_count"] == 17
    assert all(len(case["branches"]) == 12 for case in real_plan["cases"].values())
    sham = "30bf95e7afa1537469c85b2cb2a37d0dc41c90079ffde21ff367a3a9d1f11074"
    assert sham in real_plan["control_branch_ids"]
    index = real_plan["control_branch_ids"].index(sham)
    _, _, times, core, selection = controls.problem(real_plan, index, 23)
    assert len(times) == selection["samples"] == 30001 and times[-1] == 300.
    assert selection["branch_id"] == sham and selection["reset_trains"] == []
    assert core["case_plan_sha256"] == controls.signature(real_plan)
    assert core["requests"] == partitions.REQUESTS


@pytest.mark.parametrize("field", ["cases", "branches", "grid", "requests", "control_branch_ids", "source_report_sha256"])
def test_altered_plan_is_rejected_before_integration(real_plan, monkeypatch, field):
    monkeypatch.setattr(controls, "make_plan", lambda *a: deepcopy(real_plan))
    plan = deepcopy(real_plan)
    if field == "cases": plan[field].pop(CASES[0])
    elif field == "branches": next(iter(plan[field].values()))["reset_trains"] = [{"altered": True}]
    elif field == "grid": plan[field]["duration"] = 50.
    elif field == "requests": plan[field]["taylor128"]["tolerance"] = "1e-15"
    elif field == "control_branch_ids": plan[field].pop()
    else: plan[field] = "changed"
    with pytest.raises(ValueError, match="Case plan differs"):
        controls.problem(plan, 0, len(plan["control_branch_ids"]))


def test_control_partition_count_cannot_omit_controls(real_plan, monkeypatch):
    monkeypatch.setattr(controls, "validate_plan", lambda plan: 35)
    for index, count in ((0, 22), (23, 23), (-1, 23), (True, 23)):
        with pytest.raises(ValueError, match="Partition inventory"):
            controls.problem(real_plan, index, count)


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    """Only scheduling is synthetic; real source/grid reconstruction is tested above."""
    ids = [f"{i+1:064x}" for i in range(12)]
    roles = [f"{h}_{p}" for h in ("none", "ucs", "cs", "paired") for p in ("sham", "normal", "delayed")]
    plan = {"model_id": "BIOMD0000000035", "required_branch_ids": ids,
            "control_branch_ids": ids[1:], "existing_failed_partition_indices": {ids[0]: 1},
            "existing_failed_partition_count": 2,
            "cases": {"case": {"branches": dict(zip(roles, ids)), "responses": ["A"]}}}
    times = np.linspace(0., 300., 61)
    info = {"sha256": "a"*64, "observables": ["A", "B"]}
    runtime = {"versions": {p: "test" for p in ("heyoka", "numpy", "python-libsbml", "libroadrunner", "pandas")},
               "python": "test", "system": "test", "machine": "test"}
    def make_problem(bid, index, count):
        selection = {"index": index, "count": count, "branch_id": bid, "reset_trains": [],
                     "samples": len(times), "times_sha256": hashlib.sha256(times.tobytes()).hexdigest()}
        return None, info, times, {"model_id": plan["model_id"]}, selection
    monkeypatch.setattr(controls, "validate_plan", lambda p: 35)
    monkeypatch.setattr(controls, "verify_attempts", lambda r: None)
    monkeypatch.setattr(controls, "problem", lambda p, i, n: make_problem(ids[i+1], i, n))
    monkeypatch.setattr(partitions, "problem", lambda m, i, n: make_problem(ids[0], i, n))
    directories = []
    for n, bid in enumerate(ids):
        _, _, _, core, selection = make_problem(bid, n-1 if n else 1, 11 if n else 2)
        directory = tmp_path/bid; directory.mkdir(); directories.append(directory)
        report = {"core": core, "selection": selection, "environment": deepcopy(runtime),
                  "status": "completed", "case_recovery_claimed": False, "integrations": {}, "traces": {}}
        report["fingerprint"] = controls.signature({k: report[k] for k in ("core", "selection", "environment")})
        traces = {}
        for label, request in partitions.REQUESTS.items():
            values = np.ones((len(times), 2))
            path = directory/(label+".npz")
            partitions.save_trace(path, times, info["observables"], values)
            report["traces"][label] = {"file": path.name, "sha256": partitions.digest(path)}
            evidence = {"completed": True, "request": deepcopy(request), "times_sha256": selection["times_sha256"],
                        "sample_count": len(times), "observables": info["observables"],
                        "model_sha256": info["sha256"], "absolute_time_preserved": True}
            if label == "roadrunner":
                evidence["event_counters_checked_by_adapter"] = True
            else:
                evidence.update(precision_bits=request["precision"], tolerance=request["tolerance"], high_accuracy=True,
                    numeric_inputs="binary64 values promoted exactly", expected_resets=0, performed_resets=0,
                    expected_train_reset_counts=[], train_reset_counts=[], expected_segments=1, completed_segments=1,
                    last_interval=[0., 300.], integration_steps=1)
            report["integrations"][label] = evidence
            traces[label] = pd.DataFrame({"time": times, "A": values[:,0], "B": values[:,1]})
        report.update(partitions.assess(traces))
        (directory/"report.json").write_text(json.dumps(report))
    return plan, directories


def test_complete_case_uses_arrays_from_both_partition_scopes(synthetic):
    plan, directories = synthetic
    result = controls.audit_cases(plan, directories)
    assert result["complete_selected_case_coverage"] and result["all_selected_cases_validated"]
    assert result["recovered_cases"] == 1 and result["case_recovery_claimed"]
    assert result["engines_in_every_arm"] == ["taylor128", "taylor192", "roadrunner"]


def test_missing_control_cannot_recover_case(synthetic):
    plan, directories = synthetic
    with pytest.raises(ValueError, match="All full-protocol"):
        controls.audit_cases(plan, directories[:-1])
    result = controls.audit_cases(plan, directories[:-1], allow_partial=True)
    assert result["recovered_cases"] == 0 and not result["case_recovery_claimed"]
    assert result["cases"]["case"]["status"] == "incomplete"


@pytest.mark.parametrize("change", ["short_baseline", "duplicate", "environment", "partial", "truncate", "false_comparison"])
def test_inconsistent_evidence_cannot_establish_recovery(synthetic, change):
    plan, directories = synthetic
    path = directories[-1]/"report.json"
    report = json.loads(path.read_text())
    if change == "short_baseline": report["selection"]["branch_id"] = "untreated_baseline"
    elif change == "duplicate": directories.append(directories[-1])
    elif change == "environment": report["environment"]["python"] = "different"
    elif change == "partial": report["status"] = "checkpointed"
    elif change == "truncate":
        trace_path = directories[-1]/"taylor192.npz"
        with np.load(trace_path) as data:
            arrays = {key: data[key].copy() for key in data.files}
        arrays["values"] = arrays["values"][:-1]
        np.savez_compressed(trace_path, **arrays)
        report["traces"]["taylor192"]["sha256"] = partitions.digest(trace_path)
    else: report["comparisons"]["taylor128_vs_roadrunner"]["max_scaled_error"] = 4.
    report["fingerprint"] = controls.signature({k: report[k] for k in ("core", "selection", "environment")})
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        controls.audit_cases(plan, directories)


def test_branch_mismatch_keeps_case_failed(synthetic):
    plan, directories = synthetic
    records = {bid: {"status": "confirmed"} for bid in plan["required_branch_ids"]}
    records[plan["required_branch_ids"][-1]]["status"] = "precision_converged_native_mismatch"
    result = controls.score_cases(plan, records)
    assert result["case"]["status"] == "failed" and result["case"]["unconfirmed_branches"]


def test_pointwise_agreement_does_not_override_classification_disagreement(synthetic):
    plan, directories = synthetic
    bid = plan["cases"]["case"]["branches"]["paired_normal"]
    directory = next(path for path in directories if path.name == bid)
    report = json.loads((directory/"report.json").read_text())
    traces = {}
    for label in partitions.REQUESTS:
        path = directory/(label+".npz")
        with np.load(path) as data:
            arrays = {key: data[key].copy() for key in data.files}
        arrays["values"][:,0] = 1.0000404 if label == "roadrunner" else 1.0000400
        np.savez_compressed(path, **arrays)
        report["traces"][label]["sha256"] = partitions.digest(path)
        traces[label] = pd.DataFrame({"time": arrays["times"], "A": arrays["values"][:,0], "B": arrays["values"][:,1]})
    report.update(partitions.assess(traces))
    assert report["diagnostic_status"] == "confirmed"
    (directory/"report.json").write_text(json.dumps(report))
    result = controls.audit_cases(plan, directories)
    assert result["cases"]["case"]["status"] == "mismatch"
    assert result["cases"]["case"]["controlled_classification_disagreements"] == ["A"]
    assert result["recovered_cases"] == 0


def test_producer_provenance_checks_new_control_code():
    with pytest.raises(ValueError, match="Producer source differs"):
        controls.verify_committed_sources(controls.ORIGINAL_REVISION, (("grn_memory/taylor_case_controls.py", "0"*64),))
