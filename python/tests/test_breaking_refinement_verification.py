"""A refinement gate retains protocols and cannot promote incomplete evidence."""

from copy import deepcopy
import json

import pytest

from scripts import verify_breaking_refinement as verifier


@pytest.fixture
def evidence():
    directory = verifier.ROOT/'results/catalog-breaking-leloup12-refinement'
    captured = json.loads((directory/'source-evidence.json').read_text())
    original = captured['failed_branches'][0]
    record = json.loads((directory/(original['record_id']+'.json')).read_text())
    observables = list(next(iter(record['comparisons'].values()))['per_observable_max_scaled_error'])
    return record, original, observables


def test_published_complete_branch_preserves_all_observations(evidence):
    result = verifier.verify_branch(*evidence)
    assert result['recorded_refinement_confirmed'] is True
    assert result['completed_integrations'] == 6 and result['samples'] == 221001


@pytest.mark.parametrize('corruption', ['reset', 'request', 'samples', 'observable',
                                       'comparison', 'window', 'nonfinite', 'original_failure'])
def test_changed_or_missing_scientific_evidence_is_rejected(evidence, corruption):
    record, original, observables = deepcopy(evidence)
    key = next(iter(verifier.REQUIRED))
    if corruption == 'reset':
        record['specification']['reset_trains'][0]['start'] += .1
    elif corruption == 'request':
        record['integrations']['copasi_tight']['request']['atol'] *= 10
    elif corruption == 'samples':
        record['integrations']['copasi_tighter']['samples'] -= 1
    elif corruption == 'observable':
        del record['comparisons'][key]['per_observable_max_scaled_error'][observables[0]]
    elif corruption == 'comparison':
        del record['comparisons'][key]
    elif corruption == 'window':
        del record['windows']['roadrunner_tighter']
    elif corruption == 'nonfinite':
        record['comparisons'][key]['per_observable_max_scaled_error'][observables[0]] = float('nan')
    else:
        record['original_error'] = 'replaced source failure'
    with pytest.raises(ValueError):
        verifier.verify_branch(record, original, observables)


def test_failed_refinement_cannot_be_overridden_by_success_flag(evidence):
    record, original, observables = deepcopy(evidence)
    comparison = record['comparisons'][next(iter(verifier.REQUIRED))]
    comparison['per_observable_max_scaled_error'][observables[0]] = 2.
    comparison.update(max_scaled_error=2., passed=False)
    with pytest.raises(ValueError, match='outcome contradicts'):
        verifier.verify_branch(record, original, observables)
    record['refinement_confirmed'] = False
    assert verifier.verify_branch(record, original, observables)['recorded_refinement_confirmed'] is False


def test_original_solver_failure_does_not_erase_valid_refinements(evidence):
    record, original, observables = deepcopy(evidence)
    label = 'copasi_original'
    record['integrations'][label] = {'completed': False, 'error': 'original request failed',
                                   'request': original['specification']['integration_settings']['copasi']}
    del record['windows'][label]
    record['comparisons'] = {k: v for k, v in record['comparisons'].items() if label not in k}
    result = verifier.verify_branch(record, original, observables)
    assert result['recorded_refinement_confirmed'] is True and result['completed_integrations'] == 5


def test_missing_refined_trajectory_cannot_count_as_confirmed(evidence):
    record, original, observables = deepcopy(evidence)
    label = 'copasi_tighter'
    record['integrations'][label].update(completed=False, error='refined request failed')
    del record['windows'][label]
    record['comparisons'] = {k: v for k, v in record['comparisons'].items() if label not in k}
    with pytest.raises(ValueError, match='outcome contradicts'):
        verifier.verify_branch(record, original, observables)
    record['refinement_confirmed'] = False
    assert verifier.verify_branch(record, original, observables)['recorded_refinement_confirmed'] is False
