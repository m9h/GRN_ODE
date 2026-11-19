"""Exact score-rule equivalence and full Marhl scope; synthetic cubes only."""
from copy import deepcopy
import pytest

from grn_memory import marhl_cases as cases
from grn_memory.scipy_breaking_recovery import potential_trials
from test_scipy_breaking_case_audit import cube as original_cube
from test_marhl_collection import api


@pytest.fixture
def cube(original_cube):
    plan, reference, config, branches, roles = deepcopy(original_cube)
    for branch in branches.values():
        branch['windows'] = {cases.LABELS[label]: windows for label, windows in branch['windows'].items()}
    return plan, reference, config, branches, roles


def evaluate(cube, baseline=True):
    return cases.evaluate_case(*cube[:4], baseline)


def set_mean(branch, label, window, value):
    branch['windows'][label][window]['R'] = {'minimum': value, 'mean': value, 'maximum': value}


def stop_after_first(cube):
    branch = cube[3][cube[4]['first']['history_breaker_cue']]
    for label in cases.LABELS.values():
        set_mean(branch, label, 'cue_1', .5)


def test_exact_existing_case_mathematics_with_explicit_precision_labels(original_cube, cube):
    old = cases.scores.evaluate_case(*original_cube[:4], True)
    result = evaluate(cube)
    assert result == cases.rename(old)
    assert result['passed'] and result['conditional_paths_agree']
    assert result['primary_search']['engines'] == ['taylor128', 'mpmath128']
    assert result['refined_search']['engines'] == ['taylor192', 'mpmath192']
    assert set(result['primary_search']['trials']) == {'first', 'second', 'third__C__up', 'third__D__up'}
    assert all(set(t['scores']) == set(cases.LABELS.values()) for t in result['primary_search']['trials'].values())


def test_all_potential_controls_required_even_if_search_stops(cube):
    stop_after_first(cube)
    assert evaluate(cube)['passed']
    bid = cube[4]['third__C__up']['history_breaker_cue']
    cube[3][bid]['status'] = 'mismatch'
    result = evaluate(cube)
    assert result['primary_search']['passed'] and not result['passed']
    assert not result['all_original_and_potential_controls_confirmed']
    del cube[3][bid]
    with pytest.raises(ValueError, match='possible conditional control is missing'):
        evaluate(cube)


def test_missing_precision_cannot_resolve_a_conditional_decision(cube):
    del cube[3][cube[4]['first']['history_breaker_cue']]['windows']['mpmath192']
    result = evaluate(cube)
    assert result['primary_search']['complete_conditional_search']
    assert result['refined_search']['unresolved_conditional_decisions'] == ['first']
    assert not result['passed']


def test_baseline_and_source_eligibility_are_required(cube):
    assert not evaluate(cube, False)['passed']
    cube[0]['responses']['R']['copasi']['last_code'] = 2
    with pytest.raises(ValueError, match='eligibility differs'):
        evaluate(cube)


def test_controlled_threshold_disagreement_blocks_promotion(cube):
    branch = cube[3][cube[4]['first']['history_cue']]
    threshold = 8.04e-5/(1-2e-5)
    for label in cases.LABELS.values():
        set_mean(branch, label, 'cue_1', 1+threshold+(1e-9 if label == 'mpmath192' else -1e-9))
    result = evaluate(cube)
    assert result['primary_search']['trials']['first']['controlled_classification_disagreements'] == ['R']
    assert not result['passed']


def test_literal_zero_boundary_paths_remain_visible(cube):
    for branch in cube[3].values():
        for label in cases.LABELS.values():
            for window in branch['windows'][label]:
                set_mean(branch, label, window, 0.)
    for name, breakers in potential_trials(cube[0], cube[1]).items():
        branch = cube[3][cube[4][name]['history_breaker_cue']]
        for label in ('taylor128', 'mpmath128'):
            set_mean(branch, label, f'cue_{len(breakers)}', 1e-30)
    result = evaluate(cube)
    # Preserve the established rule: controlled classifications may agree even
    # when literal near-zero MATLAB comparisons choose different search paths.
    assert result['passed'] and not result['conditional_paths_agree']
    assert len(result['primary_search']['trials']) == 4 and len(result['refined_search']['trials']) == 1


def test_real_complete_scope_and_original_case_records_reproduce():
    plan, inventory, reference, config, originals, records, validation = cases.original_context()
    assert plan['task_count'] == 1520 and len(plan['branches']) == 380
    assert len(inventory['cases']) == len(originals) == 12
    assert len(inventory['generated_potential_branch_ids']) == 88
    assert len(records) == 4 and validation['numerical_integrations_performed'] == 0
    branches = {bid: {'status': 'pending', 'windows': {}} for bid in plan['branches']}
    baseline, results = cases.replay(inventory, branches, reference, config, originals)
    assert not baseline and len(results) == 12 and not any(r['passed'] for r in results.values())
    assert all(r['primary_search']['unresolved_conditional_decisions'] == ['first'] for r in results.values())
    assert all(r['original_path'] for r in results.values())


def test_full_audit_reauthenticates_all_original_scope_without_false_recovery(api, tmp_path):
    result = cases.audit(api[2], api[0], tmp_path/'archives', tmp_path/'audit')
    assert result['required_tasks'] == 1520 and result['required_branches'] == 380
    assert result['required_selected_cases'] == len(result['cases']) == 12
    assert result['original_model_cases'] == 38 and result['original_passing_cases'] == 26
    assert result['historical_passing_cases_not_rerun'] == 26
    assert result['selected_cases_passed'] == 0 and not result['selected_case_validation_passed']
    assert not result['complete_selected_array_coverage'] and not result['full_model_coverage_claimed']
    assert result['numerical_integrations_performed'] == 0
