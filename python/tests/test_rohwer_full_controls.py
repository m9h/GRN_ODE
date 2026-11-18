"""Scope and provenance checks; no new ODE trajectories are computed."""

from copy import deepcopy
import gzip
import json

import pytest

from scripts import prepare_rohwer_full_controls as full
from test_scipy_breaking_case_audit import cube


@pytest.fixture(scope='module')
def context():
    return full.prepare_scope()


def test_complete_scope_keeps_all_123_cases_and_11674_branches(context):
    scope, _, _, info, grid = context
    assert len(scope['cases']) == scope['selected_cases'] == 123
    assert len(scope['branches']) == scope['expected_branches'] == 11674
    assert len(scope['queued_diagnostics']) == 750 and len(scope['later_control_ids']) == 10924
    assert not (set(scope['queued_diagnostics']) & set(scope['later_control_ids']))
    assert set(scope['queued_diagnostics']) | set(scope['later_control_ids']) == set(scope['branches'])
    assert len(grid) == 221001 and len(info['observables']) == 17
    assert scope['original_model_cases'] == 260 and scope['original_passing_cases'] == 137
    assert not scope['case_recovery_claimed'] and not scope['full_model_coverage_claimed']


def test_baseline_is_required_at_full_horizon(context):
    scope = context[0]
    bid = scope['full_untreated_control']
    assert scope['branches'][bid]['reset_trains'] == []
    assert scope['branches'][bid]['stop'] == 2210.
    assert bid in scope['later_control_ids']


def test_per_case_integration_override_survives_compilation(cube):
    plan, reference, config, *_ = cube
    config['case_integration_overrides'][plan['ucs']] = {'copasi': {'rtol': 1e-7, 'atol': 1e-9}}
    cases, specs, baseline = full.compile_cases({'case': plan}, {'case': {'status': 'failed'}}, reference, config)
    for trial in cases['case']['potential_trials'].values():
        for bid in trial['branches'].values():
            assert specs[bid]['integration_settings']['copasi'] == {'rtol': 1e-7, 'atol': 1e-9}
    assert specs[baseline]['integration_settings'] == config['integration_settings']


def test_every_potential_trial_keeps_eight_matched_controls(context):
    cases = context[0]['cases']
    roles = {name + suffix for name in ('none', 'history', 'breaker', 'history_breaker')
             for suffix in ('_cue', '_sham')}
    for case in cases.values():
        assert {'first', 'second'} <= case['potential_trials'].keys()
        assert any(name.startswith('third__') for name in case['potential_trials'])
        assert all(set(trial['branches']) == roles for trial in case['potential_trials'].values())


def test_source_eligibility_cannot_be_reassigned(cube):
    plan, reference, config, *_ = cube
    plan['responses']['R']['copasi']['last_code'] = 2
    with pytest.raises(ValueError, match='eligibility differs'):
        full.compile_cases({'case': plan}, {'case': {'status': 'failed'}}, reference, config)


def test_compiler_keeps_all_potential_stages_without_a_new_search_outcome(cube):
    plan, reference, config, *_ = cube
    cases, specs, baseline = full.compile_cases({'case': plan}, {'case': {'status': 'failed'}}, reference, config)
    assert set(cases['case']['potential_trials']) == {'first', 'second', 'third__C__up', 'third__D__up'}
    assert baseline in specs and specs[baseline]['stop'] == 2210.


def test_original_failed_records_are_verified_and_remain_failures(context):
    scope, sources, _, info, _ = context
    index = next(i for i, row in enumerate(sources) if row['failed_branches'])
    records = {row['record_id']: row for row in sources[index]['failed_branches']}
    result = full.check_records(index, records, scope, sources[index], info['observables'])
    assert set(result) == set(records) and all(not row['passed'] for row in result.values())
    assert all(row['partition'] == index and row['record_fingerprint'] == full.fingerprint(records[bid])
               for bid, row in result.items())


@pytest.mark.parametrize('change', ['drop', 'claim_pass', 'change_spec', 'unrelated'])
def test_original_record_capture_cannot_change(context, change):
    scope, sources, _, info, _ = context
    index = next(i for i, row in enumerate(sources) if row['failed_branches'])
    records = {row['record_id']: deepcopy(row) for row in sources[index]['failed_branches']}
    bid = next(iter(records))
    if change == 'drop': records.pop(bid)
    elif change == 'claim_pass': records[bid]['passed'] = True
    elif change == 'change_spec': records[bid]['specification']['stop'] = 10.
    else: records['unrelated'] = records[bid]
    with pytest.raises(ValueError):
        full.check_records(index, records, scope, sources[index], info['observables'])


def test_origins_distinguish_generated_controls_without_inventing_results(context):
    scope = context[0]
    bid = next(iter(scope['branches']))
    synthetic_occurrence = {'partition': 0, 'passed': False, 'record_fingerprint': 'a' * 64}
    result = full.add_origins(scope, {bid: [synthetic_occurrence]})
    assert result['branch_origins'][bid] == {'kind': 'observed_original', 'occurrences': [synthetic_occurrence]}
    generated = result['generated_potential_branch_ids'][0]
    assert result['branch_origins'][generated] == {'kind': 'generated_potential', 'original_record_available': False}
    assert 'passed' not in result['branch_origins'][generated]
    assert len(result['branches']) == 11674 and len(result['cases']) == 123


@pytest.mark.parametrize('change', ['duplicate_partition', 'outside_partition', 'not_bool', 'outside_scope'])
def test_invalid_original_occurrences_rejected(context, change):
    scope = context[0]
    bid = next(iter(scope['branches']))
    row = {'partition': 0, 'passed': False, 'record_fingerprint': 'a' * 64}
    occurrences = {bid: [row]}
    if change == 'duplicate_partition': occurrences[bid].append(deepcopy(row))
    elif change == 'outside_partition': row['partition'] = 16
    elif change == 'not_bool': row['passed'] = 'false'
    else: occurrences['unrelated'] = occurrences.pop(bid)
    with pytest.raises(ValueError): full.add_origins(scope, occurrences)


def test_deterministic_record_archive_and_duplicate_rejection(tmp_path):
    records = {'a': {'record_id': 'a', 'passed': False}, 'b': {'record_id': 'b', 'passed': True}}
    full.write_records(tmp_path / 'first.gz', records)
    full.write_records(tmp_path / 'second.gz', dict(reversed(list(records.items()))))
    assert (tmp_path / 'first.gz').read_bytes() == (tmp_path / 'second.gz').read_bytes()
    assert full.read_records(tmp_path / 'first.gz') == records
    with gzip.open(tmp_path / 'duplicate.gz', 'wt') as stream:
        stream.write((json.dumps(records['a']) + '\n') * 2)
    with pytest.raises(ValueError, match='Duplicate'):
        full.read_records(tmp_path / 'duplicate.gz')


@pytest.mark.parametrize('change', ['manifest_hash', 'case_scope', 'diagnostic_scope', 'control_scope', 'claims', 'file_inventory'])
def test_manifest_cannot_shrink_or_claim_recovery(tmp_path, change):
    manifest = {'schema_version': 1, 'model_id': full.source.MODEL, 'diagnostic_plan_sha256': full.PLAN_SHA,
        'expected_branches': 11674, 'selected_cases': 123, 'queued_diagnostic_branches': 750,
        'later_control_branches': 10924, 'original_whole_model_audit_reproduced': True,
        'numerical_integrations_performed': 0, 'case_recovery_claimed': False, 'full_model_coverage_claimed': False,
        'files': {}}
    if change == 'case_scope': manifest['selected_cases'] = 122
    elif change == 'diagnostic_scope': manifest['queued_diagnostic_branches'] = 749
    elif change == 'control_scope': manifest['later_control_branches'] = 10923
    elif change == 'claims': manifest['case_recovery_claimed'] = True
    full.write(tmp_path / 'manifest.json', manifest)
    with pytest.raises(ValueError):
        full.validate(tmp_path, 'wrong' if change == 'manifest_hash' else full.digest(tmp_path / 'manifest.json'))


def test_existing_capture_is_not_overwritten(tmp_path):
    with pytest.raises(ValueError, match='new full-control'):
        full.capture(tmp_path, tmp_path)
