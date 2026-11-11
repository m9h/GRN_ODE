"""Sharding preserves the complete candidate inventory and honest coverage gates."""

import json

import pytest

from grn_memory.breaking_shards import outcome, select_cases
from grn_memory.catalog_breaking import candidate_plans
from grn_memory.catalog_validation import ROOT


def test_all_7324_initial_cases_appear_in_exactly_one_partition():
    total = 0
    for entry in json.loads((ROOT/"models/catalog.json").read_text())["models"]:
        reference = json.loads((ROOT/"results/catalog-repeated"/(entry["biomodel_id"]+".json")).read_text())
        plans = candidate_plans(reference)
        for count in (1, 4, 7):
            chunks = [select_cases(plans,i,count) for i in range(count)]
            joined = [key for chunk in chunks for key in chunk]
            assert joined == sorted(plans)
            assert len(joined) == len(set(joined))
            assert max(map(len,chunks))-min(map(len,chunks)) <= 1
        total += len(plans)
    assert total == 7324


@pytest.mark.parametrize("index,count", [(-1,4),(4,4),(0,0)])
def test_invalid_partition_is_rejected(index,count):
    with pytest.raises(ValueError):
        select_cases({"case": {}},index,count)


def test_partial_selection_success_never_promotes_the_full_model():
    report = {"cases": {"a": {"status": "passed"}}, "expected_cases": 2,
              "status": "incomplete_or_failed", "control_comparison": {"passed": True}}
    result = outcome(["a"],report,returncode=1)
    assert result["status"] == "selected_cases_passed"
    assert result["selected_coverage_complete"] and not result["model_complete"]
    report["status"] = "passed"  # A mistaken upstream flag cannot override coverage.
    assert not outcome(["a"],report,returncode=0)["model_complete"]


def test_timeout_and_failed_or_missing_controls_never_pass():
    report = {"cases": {"a": {"status": "passed"}}, "expected_cases": 1,
              "status": "passed", "control_comparison": {"passed": True}}
    assert outcome(["a"],report,returncode=0)["model_complete"]
    assert outcome(["a"],report,timed_out=True)["status"] == "incomplete"
    assert outcome(["a","b"],report,returncode=1)["status"] == "incomplete"
    report["status"] = "running"  # A crash before evidence publication is not a pass.
    assert outcome(["a"],report,returncode=1)["status"] == "incomplete"
    report["status"] = "passed"
    report["control_comparison"]["passed"] = False
    assert outcome(["a"],report,returncode=0)["status"] == "selected_cases_failed"
    del report["control_comparison"]
    assert not outcome(["a"],report,returncode=0)["model_complete"]


def test_zero_candidates_still_require_one_validated_untreated_control():
    assert not outcome([],None)["model_complete"]
    assert outcome([],None,execute_control=True)["status"] == "incomplete"
    report = {"cases": {}, "expected_cases": 0, "status": "passed", "control_comparison": {"passed": True}}
    assert outcome([],report,execute_control=True,returncode=0)["model_complete"]


def test_worker_cannot_silently_expand_a_selection():
    with pytest.raises(ValueError,match="outside"):
        outcome(["a"],{"cases": {"a": {}, "b": {}}},returncode=1)
