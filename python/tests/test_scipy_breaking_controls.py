"""Real source inventories plus explicitly synthetic integration/cache fixtures."""

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from grn_memory.scipy_breaking_recovery import common_eligibility, prepare_inventory, trial_specifications
from grn_memory.catalog_runner import ROOT
from scripts import diagnose_scipy_breaking_controls as producer


BASE = ROOT / "results/catalog-breaking-scipy-ciliberto28-shard0"
REVISION = "e5ff9bb131b3a815feb584793b9f68dda53ce7a7"


@pytest.fixture(scope="module")
def inventory():
    return prepare_inventory(BASE / "source-evidence.json", BASE / "original-case-plan.json", REVISION)[0]


def test_real_inventory_includes_all_possible_trials_and_full_baseline(inventory):
    assert inventory["original_case_branches"] == 214
    assert inventory["expected_branches"] == len(inventory["branches"]) == 215
    assert len(inventory["cases"]) == 2
    assert all(len(case["potential_trials"]) == 24 for case in inventory["cases"].values())
    control = inventory["branches"][inventory["full_untreated_control"]]
    assert control["reset_trains"] == [] and control["stop"] == 2210.
    assert inventory["case_recovery_claimed"] is False
    assert inventory["conditional_search_must_be_recomputed"] is True


def test_original_eligibility_conflict_cannot_be_silently_assigned_to_radau(inventory):
    plan = deepcopy(next(iter(inventory["cases"].values()))["original_plan"])
    row = next(iter(plan["responses"].values()))
    row["copasi"]["eligible"] = not row["roadrunner"]["eligible"]
    with pytest.raises(ValueError, match="eligibility differs"):
        common_eligibility(plan)


def test_third_trial_sham_retains_both_previous_rechallenges(inventory):
    case = next(iter(inventory["cases"].values()))
    third = next(v for k, v in case["potential_trials"].items() if k.startswith("third__"))
    spec = inventory["branches"][third["branches"]["none_sham"]]
    assert [t["start"] for t in spec["reset_trains"]] == [1210., 1610.]
    assert all(t["include_start"] is False and t["include_stop"] is False for t in spec["reset_trains"])
    assert spec["stop"] == 2210.


@pytest.mark.parametrize("change", ["branch", "trial", "reset", "summary"])
def test_changed_captured_case_evidence_is_rejected(tmp_path, change):
    plan = json.loads((BASE / "original-case-plan.json").read_text())
    if change == "branch":
        key = next(k for k, b in plan["selected_branches"].items() if b["original_passed"])
        del plan["selected_branches"][key]
        plan["required_branch_count"] -= 1
    elif change == "trial":
        case = next(iter(plan["cases"].values()))["case"]
        del case["trials"][next(k for k in case["trials"] if k.startswith("third__"))]
    elif change == "reset":
        branch = next(b for b in plan["selected_branches"].values() if b["specification"]["reset_trains"])
        branch["specification"]["reset_trains"][0]["start"] += .1
    else:
        next(iter(plan["cases"].values()))["summary"]["status"] = "passed"
    path = tmp_path / "case-plan.json"
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError):
        prepare_inventory(BASE / "source-evidence.json", path, REVISION, BASE / "source-branches.jsonl.gz")


def test_changed_original_producer_revision_is_rejected():
    with pytest.raises(ValueError, match="producer source differs"):
        prepare_inventory(BASE / "source-evidence.json", BASE / "original-case-plan.json",
                          "70a3afad61357e94873ff62a7300c099b4c7ae3e")


@pytest.fixture
def synthetic(monkeypatch):
    requests = {"roadrunner": {"rtol": 1e-13, "atol": 1e-15},
                "roadrunner_refined": {"rtol": 5e-14, "atol": 5e-16},
                "scipy": {"method": "Radau", "rtol": 1e-10, "atol": 1e-12},
                "scipy_refined": {"method": "Radau", "rtol": 1e-11, "atol": 1e-13}}
    metadata = {"fingerprint": "synthetic-fixture", "requests": requests}
    grid = np.array([0., 2210.])
    spec = {"reset_trains": [], "stop": 2210., "integration_settings": {}}
    info = {"observables": ["x"], "sha256": "synthetic-model"}
    def native(path, times, trains, engine, **request):
        return pd.DataFrame({"time": times, "x": np.ones(len(times))})
    def scipy(path, times, trains, *, evidence, progress, **request):
        evidence.update(completed=True, sample_count=len(times), model_sha256=info["sha256"],
                        **request, x64=True, absolute_time_preserved=True,
                        expected_resets=0, performed_resets=0, expected_train_reset_counts=[], train_reset_counts=[],
                        expected_segments=1, completed_segments=1, last_interval=[0., float(times[-1])])
        return pd.DataFrame({"time": times, "x": np.ones(len(times))})
    monkeypatch.setattr(producer, "protocol_trajectory", native)
    monkeypatch.setattr(producer, "scipy_protocol_trajectory", scipy)
    return metadata, grid, spec, info, scipy


def compute(tmp_path, fixture, **kw):
    metadata, grid, spec, info, _ = fixture
    return producer.compute_branch("synthetic", spec, tmp_path, metadata, grid, Path("fixture.xml"), info, **kw)


def test_all_four_integrations_and_six_comparisons_are_required(tmp_path, synthetic):
    assert compute(tmp_path, synthetic)["status"] == "confirmed"
    row = producer.read(tmp_path / "synthetic.json")
    assert len(row["integrations"]) == len(row["traces"]) == 4
    assert len(row["comparisons"]) == 6
    assert row["case_recovery_claimed"] is False


def test_final_observation_only_discrepancy_cannot_pass(tmp_path, synthetic, monkeypatch):
    original = synthetic[-1]
    def different(*args, **kw):
        trace = original(*args, **kw)
        if kw["rtol"] == 1e-11:
            trace.loc[len(trace) - 1, "x"] = 2.
        return trace
    monkeypatch.setattr(producer, "scipy_protocol_trajectory", different)
    assert compute(tmp_path, synthetic)["status"] == "mismatch"


def test_failed_integration_is_retained_and_never_promoted(tmp_path, synthetic, monkeypatch):
    def fail(*args, **kw):
        raise RuntimeError("synthetic failed integration")
    monkeypatch.setattr(producer, "scipy_protocol_trajectory", fail)
    assert compute(tmp_path, synthetic)["status"] == "incomplete"
    row = producer.read(tmp_path / "synthetic.json")
    assert row["integrations"]["scipy"]["completed"] is False
    assert "synthetic failed integration" in row["integrations"]["scipy"]["error"]
    assert len(row["traces"]) == 2
    monkeypatch.setattr(producer, "scipy_protocol_trajectory", synthetic[-1])
    assert compute(tmp_path, synthetic, resume=True)["status"] == "confirmed"
    row = producer.read(tmp_path / "synthetic.json")
    assert row["previous_incomplete_attempts"]["scipy"][0]["completed"] is False


def test_resume_reuses_verified_arrays_without_new_integration(tmp_path, synthetic, monkeypatch):
    first = compute(tmp_path, synthetic)
    def unexpected(*args, **kw):
        raise AssertionError("No integration should be called")
    monkeypatch.setattr(producer, "protocol_trajectory", unexpected)
    monkeypatch.setattr(producer, "scipy_protocol_trajectory", unexpected)
    assert compute(tmp_path, synthetic, resume=True) == first


@pytest.mark.parametrize("change", ["array", "fingerprint", "request", "reset_counter", "missing_trace"])
def test_corrupt_or_changed_cache_is_rejected(tmp_path, synthetic, change):
    compute(tmp_path, synthetic)
    p = tmp_path / "synthetic.json"
    record = producer.read(p)
    if change == "array":
        (tmp_path / record["traces"]["scipy"]["file"]).write_bytes(b"changed")
    elif change == "fingerprint":
        record["fingerprint"] = "different"
    elif change == "request":
        record["integrations"]["scipy"]["request"]["rtol"] = 1e-8
    elif change == "reset_counter":
        record["integrations"]["scipy"]["performed_resets"] = 1
    else:
        del record["traces"]["scipy"]
    p.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        compute(tmp_path, synthetic, resume=True)
