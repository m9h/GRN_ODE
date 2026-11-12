"""Different literal search paths must not masquerade as model disagreement."""

from copy import deepcopy

import pytest

from grn_memory.breaking_scores import controlled_break, matlab_break_direction
from scripts.compare_breaking_runs import compare_cases


def score(before, during):
    result = controlled_break({key: (0., 0.) for key in ("none", "history", "breaker", "history_breaker")})
    result["matlab"] = {"pre_mean": before, "cue_mean": during, "last_code": 1,
                       "break_direction": matlab_break_direction(before, during, 1)}
    return result


def case(value):
    return {"a": {"trials": {"first": {"breakers": ["B"], "responses": ["Y"],
                                      "scores": {"engine": {"Y": value}}}}}}


def test_sign_of_unresolved_residue_changes_raw_label_only():
    a = case(score(-2.4812379183449456e-38, -1.1264802130812147e-42))
    b = case(score(6.728249100934178e-39, 3.054620205867503e-43))
    result = compare_cases(a, b, ["engine"])
    assert result["totals"]["raw_reversal_label_differences"] == 1
    assert result["totals"]["raw_differences_below_absolute_floor"] == 1
    assert result["totals"]["controlled_label_differences"] == 0
    assert result["controlled_agreement_on_shared_assessments"]
    assert not result["whole_run_equivalence_claimed"]


def test_trials_unique_to_one_run_are_retained_without_inventing_agreement():
    a = case(score(0., 0.)); b = deepcopy(a)
    a["a"]["trials"]["second"] = deepcopy(a["a"]["trials"]["first"])
    a["a"]["trials"]["second"]["breakers"] = ["B", "B"]
    result = compare_cases(a, b, ["engine"])
    assert result["totals"]["left_only_trials"] == result["totals"]["path_differing_cases"] == 1
    assert result["totals"]["shared_trials"] == result["totals"]["shared_response_engine_assessments"] == 1
    assert "second" in result["path_differences"][0]["left"]


def test_changed_controlled_direction_is_not_hidden_by_same_category():
    a = case(score(0., 0.)); b = deepcopy(a)
    b["a"]["trials"]["first"]["scores"]["engine"]["Y"]["cue_effects"]["none"]["resolved_direction"] = 1
    result = compare_cases(a, b, ["engine"])
    assert result["totals"]["controlled_label_differences"] == 1
    assert not result["controlled_agreement_on_shared_assessments"]


def test_missing_cases_or_engine_scores_are_rejected():
    a = case(score(0., 0.))
    with pytest.raises(ValueError, match="case inventories"):
        compare_cases(a, {}, ["engine"])
    b = deepcopy(a); b["a"]["trials"]["first"]["scores"] = {}
    with pytest.raises(ValueError, match="engine score inventories"):
        compare_cases(a, b, ["engine"])


def test_same_trial_name_with_different_interventions_is_rejected():
    a = case(score(0., 0.)); b = deepcopy(a)
    b["a"]["trials"]["first"]["breakers"] = ["C"]
    with pytest.raises(ValueError, match="different interventions"):
        compare_cases(a, b, ["engine"])


def test_empty_inventory_does_not_claim_observed_label_agreement():
    result = compare_cases({}, {}, ["engine"])
    assert result["totals"]["cases"] == 0
    assert result["controlled_agreement_on_shared_assessments"] is None


def test_missing_response_cannot_reduce_the_comparison_inventory():
    a = case(score(0., 0.)); b = deepcopy(a)
    b["a"]["trials"]["first"]["scores"]["engine"] = {}
    with pytest.raises(ValueError, match="declared response score"):
        compare_cases(a, b, ["engine"])
