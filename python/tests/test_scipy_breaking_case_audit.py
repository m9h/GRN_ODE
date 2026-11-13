"""Synthetic control cubes test scientific gates; these are not simulation data."""

from copy import deepcopy
import json
import gzip
from pathlib import Path

import numpy as np
import pytest

from grn_memory.catalog_breaking import trial_windows
from grn_memory.catalog_runner import fingerprint
from grn_memory.native_protocols import ResetTrain
from grn_memory.scipy_breaking_recovery import LABELS, potential_trials, trial_specifications
from scripts import audit_scipy_breaking_cases as audit


@pytest.fixture
def cube():
    eligibility = {"eligible": True, "resistance": True, "sensitization": False, "last_code": 1}
    plan = {"ucs": "A__up", "breaker": "B__up",
            "responses": {"R": {"roadrunner": deepcopy(eligibility), "copasi": deepcopy(eligibility)}}}
    reference = {"cases": {name + "__up": {"input": name, "level": float(i + 1)}
                           for i, name in enumerate(("A", "B", "C", "D"))}}
    config = {"integration_settings": {"roadrunner": {"rtol": 1e-12, "atol": 1e-14},
                                        "copasi": {"rtol": 1e-12, "atol": 1e-14}},
              "case_integration_overrides": {}}
    branches, roles = {}, {}
    for name, breakers in potential_trials(plan, reference).items():
        roles[name] = {}
        for role, spec in trial_specifications(plan, breakers, reference, config).items():
            bid = fingerprint(spec)
            roles[name][role] = bid
            branches[bid] = {"status": "confirmed", "windows": {label: {
                window: {"R": {"minimum": 1., "mean": 1., "maximum": 1.}}
                for window in trial_windows(len(breakers))} for label in LABELS}}
    return plan, reference, config, branches, roles


def set_mean(branch, label, window, value):
    branch["windows"][label][window]["R"] = {"minimum": value, "mean": value, "maximum": value}


def evaluate(cube, baseline=True):
    return audit.evaluate_case(*cube[:4], baseline)


def test_all_three_stages_and_every_eligible_third_breaker_are_replayed(cube):
    result = evaluate(cube)
    assert result["passed"] and result["conditional_paths_agree"]
    assert set(result["primary_search"]["trials"]) == {"first", "second", "third__C__up", "third__D__up"}
    assert all(t["responses"] == ["R"] and len(t["branches"]) == 8
               for t in result["primary_search"]["trials"].values())


def stop_after_first(cube):
    branch = cube[3][cube[4]["first"]["history_breaker_cue"]]
    for label in LABELS:
        set_mean(branch, label, "cue_1", .5)


def test_raw_positive_first_trial_stops_each_declared_search(cube):
    stop_after_first(cube)
    result = evaluate(cube)
    assert result["passed"]
    assert set(result["primary_search"]["trials"]) == {"first"}
    assert set(result["refined_search"]["trials"]) == {"first"}


def test_unreached_original_control_failure_still_prevents_recovery(cube):
    stop_after_first(cube)
    cube[3][cube[4]["third__C__up"]["history_breaker_cue"]]["status"] = "mismatch"
    result = evaluate(cube)
    assert result["primary_search"]["passed"]
    assert not result["all_original_and_potential_controls_confirmed"]
    assert not result["passed"]


def test_missing_unreached_control_cannot_be_ignored(cube):
    stop_after_first(cube)
    del cube[3][cube[4]["third__C__up"]["history_breaker_cue"]]
    with pytest.raises(ValueError, match="possible conditional control is missing"):
        evaluate(cube)


def test_failed_untreated_baseline_prevents_case_promotion(cube):
    result = evaluate(cube, baseline=False)
    assert result["primary_search"]["passed"] and result["all_original_and_potential_controls_confirmed"]
    assert not result["passed"]


def test_missing_refined_trajectory_leaves_search_unresolved(cube):
    del cube[3][cube[4]["first"]["history_breaker_cue"]]["windows"]["scipy_refined"]
    result = evaluate(cube)
    assert result["primary_search"]["complete_conditional_search"]
    assert result["refined_search"]["unresolved_conditional_decisions"] == ["first"]
    assert not result["passed"]


def test_controlled_label_boundary_can_fail_even_for_close_observations(cube):
    branch = cube[3][cube[4]["first"]["history_cue"]]
    threshold = 8.04e-5 / (1 - 2e-5)
    for label in LABELS:
        set_mean(branch, label, "cue_1", 1 + threshold + (1e-9 if label == "scipy_refined" else -1e-9))
    result = evaluate(cube)
    assert result["primary_search"]["trials"]["first"]["controlled_classification_disagreements"] == ["R"]
    assert not result["passed"]


def test_near_zero_raw_paths_are_compared_without_claiming_unique_continuation(cube):
    for branch in cube[3].values():
        for label in LABELS:
            for window in branch["windows"][label]:
                set_mean(branch, label, window, 0.)
    for name, breakers in potential_trials(cube[0], cube[1]).items():
        branch = cube[3][cube[4][name]["history_breaker_cue"]]
        for label in audit.PRIMARY:
            set_mean(branch, label, f"cue_{len(breakers)}", 1e-30)
    result = evaluate(cube)
    assert result["passed"] and not result["conditional_paths_agree"]
    assert len(result["primary_search"]["trials"]) == 4
    assert len(result["refined_search"]["trials"]) == 1


def test_source_eligibility_disagreement_is_not_reassigned(cube):
    cube[0]["responses"]["R"]["copasi"]["last_code"] = 2
    with pytest.raises(ValueError, match="eligibility differs"):
        evaluate(cube)


@pytest.mark.parametrize("field,value", [("x64", False), ("absolute_time_preserved", False),
    ("backend", "unknown"), ("rhs_backend", "unknown"), ("jacobian", "finite-difference"),
    ("performed_resets", 998), ("completed_segments", 999), ("method", "BDF"),
    ("last_interval", [1109.9, 1409.]), ("sample_count", 1)])
def test_independent_outcome_check_rejects_incomplete_protocols(field, value):
    request = {"method": "Radau", "rtol": 1e-10, "atol": 1e-12}
    trains = [ResetTrain(1010., 1110., {"A": 1.})]
    times = np.array([0., 1410.])
    row = {"request": request, "completed": True, "sample_count": 2, "observables": ["R"],
           "backend": "scipy.solve_ivp", "rhs_backend": "Jaxkineticmodel", "jacobian": "jax.jacfwd",
           "model_sha256": "synthetic", **request, "x64": True, "absolute_time_preserved": True,
           "expected_resets": 999, "performed_resets": 999, "expected_train_reset_counts": [999],
           "train_reset_counts": [999], "expected_segments": 1000, "completed_segments": 1000,
           "last_interval": [1109.9, 1410.]}
    assert audit.check_outcome(row, "scipy", request, times, ["R"], trains, "synthetic")
    row[field] = value
    with pytest.raises(ValueError):
        audit.check_outcome(row, "scipy", request, times, ["R"], trains, "synthetic")


def test_completed_report_is_required(tmp_path):
    (tmp_path / "report.json").write_text(json.dumps({"status": "running"}))
    with pytest.raises(ValueError, match="still running"):
        audit.audit(tmp_path)


def test_old_window_contradictions_are_reported_separately(cube):
    branch = next(iter(cube[3].values()))
    old = {"windows": {"roadrunner": deepcopy(branch["windows"]["roadrunner"])}}
    assert audit.summary_discrepancy(old, branch)["max_scaled_error"] == 0.
    set_mean(branch, "scipy_refined", "prefix", 2.)
    result = audit.summary_discrepancy(old, branch)
    assert result["max_scaled_error"] > 1 and result["new_engine"] == "scipy_refined"


@pytest.fixture
def saved_cube(tmp_path, cube, monkeypatch):
    """A tiny invented dataset exercises complete-file audit wiring only."""
    root, directory = tmp_path / "root", tmp_path / "diagnostic"
    directory.mkdir()
    plan, reference, config, branches, roles = cube
    specs = {fingerprint(spec): spec for breakers in potential_trials(plan, reference).values()
             for spec in trial_specifications(plan, breakers, reference, config).values()}
    baseline = {"reset_trains": [], "stop": 2210., "integration_settings": config["integration_settings"]}
    baseline_id = fingerprint(baseline)
    specs[baseline_id] = baseline
    grid = np.array([0., 1010.01, 1110.01, 1210.01, 1310.01, 1410., 1410.01,
                     1510.01, 1610.01, 1710.01, 1810., 1810.01, 1910.01, 2010.01, 2110.01, 2210.])
    info = {"sha256": "synthetic-model", "observables": ["R"]}
    inventory = {"model_id": "SYNTHETIC", "model_sha256": info["sha256"], "source_revision": "synthetic",
                 "source_report_sha256": "synthetic-original-report", "branches": specs,
                 "cases": {"case": {"original_plan": plan}}, "expected_branches": len(specs),
                 "expected_model_cases": 100, "full_untreated_control": baseline_id}
    monkeypatch.setattr(audit, "ROOT", root)
    monkeypatch.setattr(audit, "source_hashes", lambda: {})
    monkeypatch.setattr(audit, "prepare_inventory", lambda *args: (deepcopy(inventory), None, info, grid))
    for name in set((*audit.SOURCES, *audit.EXTRA_SOURCES)):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic source fixture\n")
    reference_path = root / "results/catalog-repeated/SYNTHETIC.json"
    reference_path.parent.mkdir(parents=True)
    reference_path.write_text(json.dumps(reference))
    requests = {"roadrunner": {"rtol": 1e-13, "atol": 1e-15},
                "roadrunner_refined": {"rtol": 5e-14, "atol": 5e-16},
                "scipy": {"method": "Radau", "rtol": 1e-10, "atol": 1e-12},
                "scipy_refined": {"method": "Radau", "rtol": 1e-11, "atol": 1e-13}}
    versions = {name: "synthetic-version" for name in audit.PACKAGES}
    records = {}
    for bid, spec in specs.items():
        times = grid[grid <= spec["stop"]]
        trains = [ResetTrain(**t) for t in spec["reset_trains"]]
        resets = sorted({float(v) for t in trains if t.values for v in t.times()})
        counts = [len(t.indices()) if t.values else 0 for t in trains]
        integrations, traces, frames = {}, {}, {}
        for label, request in requests.items():
            path = directory / (bid + "-" + label + ".npz")
            np.savez_compressed(path, times=times, values=np.ones((len(times), 1)), observables=np.array(["R"]))
            traces[label] = {"file": path.name, "sha256": audit.digest(path)}
            integrations[label] = {"completed": True, "request": request, "sample_count": len(times), "observables": ["R"]}
            if label.startswith("scipy"):
                integrations[label].update(model_sha256=info["sha256"], **request, x64=True,
                    backend="scipy.solve_ivp", rhs_backend="Jaxkineticmodel", jacobian="jax.jacfwd",
                    absolute_time_preserved=True, expected_resets=len(resets), performed_resets=len(resets),
                    expected_train_reset_counts=counts, train_reset_counts=counts,
                    expected_segments=len(resets) + 1, completed_segments=len(resets) + 1,
                    last_interval=[resets[-1] if resets else 0., float(times[-1])])
            frames[label] = audit.trajectory(directory, bid, label, traces[label], times, ["R"])
        comparisons = {a + "_vs_" + b: audit.comparison(frames[a], frames[b], **audit.ACCEPTANCE)
                       for i, a in enumerate(LABELS) for b in LABELS[i+1:]}
        records[bid] = {"record_id": bid, "specification": spec, "integrations": integrations,
                        "traces": traces, "comparisons": comparisons, "status": "confirmed", "case_recovery_claimed": False}
    imported_id = next(bid for bid in records if bid != baseline_id)
    source = {"model_id": "SYNTHETIC", "source_report_sha256": inventory["source_report_sha256"],
              "versions": versions, "requests": requests,
              "branches": [{"record_id": imported_id, "sha256": "synthetic-original-record"}]}
    (directory / "reused-report.json").write_text(json.dumps(source))
    source_audit = {"report_sha256": audit.digest(directory / "reused-report.json"),
                    "all_selected_branches_confirmed": True, "complete_captured_failure_coverage": True,
                    "branches": [{"record_id": imported_id, "traces": records[imported_id]["traces"]}]}
    (directory / "reused-audit.json").write_text(json.dumps(source_audit))
    metadata = {"model_id": "SYNTHETIC", "model_sha256": info["sha256"], "inventory_sha256": fingerprint(inventory),
                "requests": requests, "acceptance": audit.ACCEPTANCE, "versions": versions,
                "implementation_sha256": {n: audit.digest(root / n) for n in (*audit.SOURCES, *audit.EXTRA_SOURCES)},
                "sample_grid_sha256": audit.hashlib.sha256(grid.tobytes()).hexdigest(),
                "reused_report_sha256": audit.digest(directory / "reused-report.json"),
                "reused_audit_sha256": fingerprint(source_audit), "case_recovery_claimed": False,
                "full_model_coverage_claimed": False}
    signature = fingerprint(metadata)
    records[imported_id]["reused_from"] = {"report_sha256": metadata["reused_report_sha256"],
                                          "record_sha256": "synthetic-original-record"}
    entries = []
    for bid, record in records.items():
        record["fingerprint"] = signature
        path = directory / (bid + ".json")
        path.write_text(json.dumps(record))
        entries.append({"record_id": bid, "file": path.name, "sha256": audit.digest(path), "status": "confirmed"})
    report = {**metadata, "fingerprint": signature, "status": "completed", "expected_branches": len(specs),
              "confirmed_branches": len(specs), "expected_model_cases": 100, "branches": entries,
              "selected_case_keys": ["case"], "full_untreated_control": baseline_id}
    (directory / "report.json").write_text(json.dumps(report))
    (directory / "inventory.json").write_text(json.dumps(inventory))
    (directory / "source-evidence.json").write_text(json.dumps({"original_report": {"configuration": config}}))
    original_trials = audit.replay_case(plan, reference, config, branches, audit.PRIMARY)["trials"]
    (directory / "original-case-plan.json").write_text(json.dumps({"cases": {"case": {"case": {"trials": original_trials}}}}))
    with gzip.open(directory / "source-branches.jsonl.gz", "wt") as stream:
        for bid, branch in branches.items():
            stream.write(json.dumps({"record_id": bid, "passed": True, "windows": branch["windows"]}) + "\n")
    return directory, baseline_id


def test_complete_saved_array_audit_and_case_replay(saved_cube):
    result = audit.audit(saved_cube[0])
    assert result["selected_cases"] == result["recovered_selected_cases"] == 1
    assert result["baseline_passed"] and result["complete_selected_control_inventory"]
    assert result["cases"]["case"]["primary_matches_original_path"]
    assert result["cases"]["case"]["refined_matches_original_path"]
    assert result["original_passing_cases_included"] is False
    assert result["full_model_coverage_claimed"] is False


@pytest.mark.parametrize("change", ["truncate", "last_observation"])
def test_saved_array_audit_rejects_damage_even_when_hashes_are_updated(saved_cube, change):
    directory, bid = saved_cube
    record_path = directory / (bid + ".json")
    record = audit.read(record_path)
    array_path = directory / record["traces"]["scipy"]["file"]
    with np.load(array_path, allow_pickle=False) as archive:
        times, values, names = archive["times"].copy(), archive["values"].copy(), archive["observables"].copy()
    if change == "truncate":
        times, values = times[:-1], values[:-1]
    else:
        values[-1, 0] = 2.
    np.savez_compressed(array_path, times=times, values=values, observables=names)
    record["traces"]["scipy"]["sha256"] = audit.digest(array_path)
    record_path.write_text(json.dumps(record))
    report = audit.read(directory / "report.json")
    next(e for e in report["branches"] if e["record_id"] == bid)["sha256"] = audit.digest(record_path)
    (directory / "report.json").write_text(json.dumps(report))
    with pytest.raises(ValueError, match="observation inventory differs|comparisons do not reproduce"):
        audit.audit(directory)
