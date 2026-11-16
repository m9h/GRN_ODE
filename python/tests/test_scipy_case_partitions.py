"""Full real Fuss scope and synthetic partition-integrity checks."""

from copy import deepcopy

import pytest

from grn_memory.catalog_runner import ROOT
from grn_memory.scipy_case_partitions import (branch_order, load_experiment, selected_branches,
                                             validate_partition_inventory, validate_requests, metadata, validate_metadata)


@pytest.fixture(scope="module")
def fuss():
    return load_experiment(ROOT / "results/catalog-breaking-fuss-full-case-plan-20261116")


def test_complete_fuss_scope_keeps_all_failed_cases_controls_and_untreated_baseline(fuss):
    plan, inventory, _, _, grid = fuss
    assert len(inventory["cases"]) == 18
    assert inventory["expected_model_cases"] == 332
    assert inventory["original_case_branches"] == 1308
    assert inventory["expected_branches"] == 1309
    assert len(grid) == 221001 and grid[-1] == 2210.
    groups = [selected_branches(inventory, 32, index) for index in range(32)]
    ids = [bid for group in groups for bid in group]
    assert len(ids) == len(set(ids)) == 1309 and set(ids) == set(inventory["branches"])
    assert groups[0][0] == inventory["full_untreated_control"]
    assert inventory["branches"][groups[0][0]]["reset_trains"] == []
    assert plan["reference_engine"] == "copasi"
    assert sum(len(group) * 4 for group in groups) == 5236


@pytest.fixture
def partition_fixture():
    inventory = {"branches": {k: {} for k in ("baseline", "a", "b", "c", "d")},
                 "full_untreated_control": "baseline", "expected_branches": 5}
    plan = {"shard_count": 3}
    reports = []
    for index in range(3):
        ids = selected_branches(inventory, 3, index)
        reports.append({"metadata": {"shard_index": index, "selected_branch_ids": ids,
                                      "experiment_fingerprint": "same-experiment"},
                        "status": "completed", "complete_selected_inventory": True,
                        "branches": [{"record_id": bid} for bid in ids]})
    return reports, plan, inventory


def test_disjoint_complete_partition_union_is_valid(partition_fixture):
    validate_partition_inventory(*partition_fixture)
    assert branch_order(partition_fixture[2])[0] == "baseline"


@pytest.mark.parametrize("change", ["missing_partition", "duplicate_partition", "missing_branch",
                                   "duplicate_branch", "incomplete", "changed_environment", "wrong_selection"])
def test_partial_or_mixed_evidence_cannot_promote_coverage(partition_fixture, change):
    reports, plan, inventory = deepcopy(partition_fixture)
    if change == "missing_partition":
        reports.pop()
    elif change == "duplicate_partition":
        reports[-1] = deepcopy(reports[0])
    elif change == "missing_branch":
        reports[0]["branches"].pop()
    elif change == "duplicate_branch":
        reports[0]["branches"].append(reports[0]["branches"][0])
    elif change == "incomplete":
        reports[0]["status"] = "checkpointed"
    elif change == "changed_environment":
        reports[0]["metadata"]["experiment_fingerprint"] = "different-versions"
    else:
        reports[0]["metadata"]["selected_branch_ids"].reverse()
    with pytest.raises(ValueError):
        validate_partition_inventory(reports, plan, inventory)


@pytest.mark.parametrize("count,index", [(0, 0), (6, 0), (2, -1), (2, 2), (True, 0), (2, False)])
def test_invalid_partition_selection_is_rejected(partition_fixture, count, index):
    with pytest.raises(ValueError):
        selected_branches(partition_fixture[2], count, index)


@pytest.mark.parametrize("change", ["omit_refinement", "weaken_native", "wrong_factor", "not_radau", "nan"])
def test_request_changes_cannot_silently_weaken_validation(fuss, change):
    plan, inventory, *_ = fuss
    requests = deepcopy(plan["requests"])
    if change == "omit_refinement":
        del requests["copasi_refined"]
    elif change == "weaken_native":
        requests["copasi"]["rtol"] = 1e-4
        requests["copasi_refined"]["rtol"] = 5e-5
    elif change == "wrong_factor":
        requests["scipy_refined"]["rtol"] = 5e-12
    elif change == "not_radau":
        requests["scipy"]["method"] = "RK45"
    else:
        requests["scipy"]["atol"] = float("nan")
    with pytest.raises(ValueError):
        validate_requests(requests, "copasi", inventory)


@pytest.mark.parametrize("change", ["source", "inventory", "request", "environment", "grid", "selection"])
def test_resume_metadata_binds_source_scope_grid_and_environment(fuss, change):
    pytest.importorskip("jaxkineticmodel")
    plan, inventory, _, _, grid = fuss
    path = ROOT / "results/catalog-breaking-fuss-full-case-plan-20261116/execution-plan.json"
    saved = metadata(path, plan, inventory, grid, 0)
    validate_metadata(saved, path, plan, inventory, grid, live_environment=True)
    if change == "source":
        saved["experiment"]["implementation_sha256"]["grn_memory/breaking_scores.py"] = "0" * 64
    elif change == "inventory":
        saved["experiment"]["inventory_sha256"] = "0" * 64
    elif change == "request":
        saved = deepcopy(saved)
        saved["experiment"]["requests"]["copasi"]["rtol"] = 1e-6
    elif change == "environment":
        saved["experiment"]["versions"]["python-copasi"] = "changed"
    elif change == "grid":
        saved["experiment"]["sample_grid_sha256"] = "0" * 64
    else:
        saved["selected_branch_ids"].pop()
    with pytest.raises(ValueError, match="fingerprint differs"):
        validate_metadata(saved, path, plan, inventory, grid, live_environment=True)
