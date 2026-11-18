"""Missing-evidence repair must retain the entire predetermined case scope."""

from pathlib import Path

import pytest

from scripts.recompute_ciliberto_evidence import read, verify_selection

INPUTS = Path(__file__).parents[1] / "results/catalog-breaking-ciliberto-case-recovery-20261118"


@pytest.fixture
def inputs():
    return [read(INPUTS / name) for name in (
        "recomputation-plan.json", "preservation-manifest.json", "report.json", "reused-report.json")]


def test_original_selection_covers_all_missing_evidence(inputs):
    verify_selection(*inputs)
    assert inputs[2]["full_untreated_control"] in inputs[0]["selected_branch_ids"]


def test_cannot_drop_untreated_baseline(inputs):
    inputs[0]["selected_branch_ids"].remove(inputs[2]["full_untreated_control"])
    with pytest.raises(ValueError):
        verify_selection(*inputs)


def test_cannot_recompute_published_import_to_pick_new_result(inputs):
    inputs[0]["selected_branch_ids"] += inputs[0]["restore_from_release_branch_ids"]
    inputs[0]["selected_branch_ids"].sort()
    with pytest.raises(ValueError):
        verify_selection(*inputs)


def test_branch_repair_cannot_shrink_complete_case_scope(inputs):
    inputs[0]["expected_full_branches"] = 18
    with pytest.raises(ValueError):
        verify_selection(*inputs)


def test_branch_repair_cannot_claim_case_recovery(inputs):
    inputs[0]["full_case_recovery_claimed"] = True
    with pytest.raises(ValueError):
        verify_selection(*inputs)
