"""Real Marhl scope regressions; no numerical integrations or convergence claims."""

from collections import Counter
from copy import deepcopy
import json

import numpy as np
import pytest

from scripts import prepare_marhl_full_controls as producer
from grn_memory.catalog_breaking import candidate_plans
from grn_memory.catalog_runner import fingerprint
from grn_memory.native_protocols import ResetTrain, sample_times


@pytest.fixture(scope='module')
def inventory():
    return producer.build()


def test_every_original_failed_case_including_linux_only_failure_is_retained(inventory):
    assert inventory['original_model_cases'] == 38
    assert inventory['original_passing_cases'] == 26
    assert len(inventory['cases']) == 12
    assert 'CaM__up--CaPr__up' in inventory['cases']
    assert all(c['original_summary']['status'] != 'passed' for c in inventory['cases'].values())
    assert inventory['original_audit_reproduced'] is True
    assert inventory['case_recovery_claimed'] is inventory['full_model_coverage_claimed'] is False
    assert inventory['numerical_integrations_performed'] == inventory['raw_trajectory_arrays_verified'] == 0


def test_full_scope_includes_unreached_trials_and_untreated_baseline(inventory):
    assert len(inventory['branches']) == inventory['expected_branches'] == 380
    assert len(inventory['diagnostic_branch_ids']) == 29
    assert len(inventory['other_required_branch_ids']) == 351
    assert set(inventory['diagnostic_branch_ids']).isdisjoint(inventory['other_required_branch_ids'])
    assert set(inventory['diagnostic_branch_ids']) | set(inventory['other_required_branch_ids']) == set(inventory['branches'])
    assert Counter(len(c['potential_trials']) for c in inventory['cases'].values()) == {6: 7, 8: 5}
    baseline = inventory['full_untreated_control']
    assert inventory['branches'][baseline]['reset_trains'] == []
    assert inventory['branches'][baseline]['stop'] == 2210.
    assert baseline in inventory['other_required_branch_ids']
    assert inventory['branch_observations'][baseline]['samples'] == 221001


def test_missing_controls_are_explicit_and_have_no_fabricated_original_records(inventory):
    missing = {k: len(c['missing_original_partition_branches']) for k, c in inventory['cases'].items()
               if c['missing_original_partition_branches']}
    assert missing == {'CaER__down--CaM__down': 20, 'CaER__up--CaM__down': 20,
                       'CaM__down--Pr__down': 20, 'CaM__up--Ca_cyt__down': 8,
                       'Ca_cyt__up--CaM__down': 20}
    assert len(inventory['generated_potential_branch_ids']) == 88
    assert inventory['original_observed_branch_specifications'] == 292
    assert inventory['original_selected_branch_records'] == 346
    for bid in inventory['generated_potential_branch_ids']:
        assert inventory['branch_origins'][bid] == {'kind': 'generated_potential', 'original_record_available': False}


def test_shared_failed_control_retains_both_original_partition_records(inventory):
    rows = inventory['original_failed_branch_records']
    assert len(rows) == 30
    counts = Counter(row['branch_id'] for row in rows)
    assert sorted(counts.values()) == [1] * 28 + [2]
    bid = next(b for b, count in counts.items() if count == 2)
    assert bid == '52c4262d15793b942c2161f29cd82d6a4d4ffc61ec63e4175ff79f1e28ef3f8d'
    assert [row['partition'] for row in rows if row['branch_id'] == bid] == [0, 3]
    assert {r['partition'] for r in inventory['branch_origins'][bid]['occurrences'] if not r['passed']} == {0, 3}


def test_later_sham_arms_keep_earlier_rechallenges(inventory):
    for case in inventory['cases'].values():
        for name, trial in case['potential_trials'].items():
            assert len(trial['branches']) == 8
            if name.startswith('third__'):
                spec = inventory['branches'][trial['branches']['none_sham']]
                assert spec['stop'] == 2210.
                assert [t['start'] for t in spec['reset_trains']] == [1210., 1610.]
                assert all(t['include_start'] is False and t['include_stop'] is False for t in spec['reset_trains'])


def test_original_full_grid_and_reset_counts_are_preserved(inventory):
    assert inventory['horizon_counts'] == {'1410.0': 59, '1810.0': 68, '2210.0': 253}
    assert inventory['observables'] == ['Ca_cyt', 'CaER', 'CaM', 'CaPr', 'Pr']
    for bid, spec in inventory['branches'].items():
        row = inventory['branch_observations'][bid]
        assert bid == fingerprint(spec)
        assert row['samples'] == round(spec['stop'] / .01) + 1
        assert row['reset_counts'] == [len(ResetTrain(**t).indices()) if t['values'] else 0 for t in spec['reset_trains']]
    # Actual displaced reset observations are required, even for no-reset arms.
    baseline = inventory['full_untreated_control']
    from grn_memory.catalog_repeated import pulse_schedule, trains_for
    possible = trains_for(pulse_schedule(), {}) + [ResetTrain(t, t + 100., {})
                for t in (1010., 1210., 1410., 1610., 1810., 2010.)]
    grid = sample_times(2210., .01, possible, post_reset_offset=1e-5)
    import hashlib
    assert inventory['branch_observations'][baseline]['sample_grid_sha256'] == hashlib.sha256(grid.tobytes()).hexdigest()
    assert not np.array_equal(grid, np.arange(221001) * .01)


def source_inputs():
    reference = producer.read(producer.ROOT / 'results/catalog-repeated' / (producer.MODEL + '.json'))
    plans = candidate_plans(reference)
    summaries = producer.read(producer.SOURCE / 'audit.json')['case_summaries']
    config = producer.read(producer.SOURCE / 'shard-0' / (producer.MODEL + '.json'))['configuration']
    return plans, summaries, reference, config


def test_conflicting_original_eligibility_is_rejected():
    plans, summaries, reference, config = source_inputs()
    plan = plans[next(k for k, v in summaries.items() if v['status'] != 'passed')]
    row = next(iter(plan['responses'].values()))
    row['copasi']['eligible'] = not row['roadrunner']['eligible']
    with pytest.raises(ValueError, match='eligibility differs'):
        producer.compile_scope(plans, summaries, reference, config)


def test_case_specific_original_requests_are_part_of_branch_identity():
    plans, summaries, reference, config = source_inputs()
    key = 'CaM__up--Pr__up'
    setting = {'rtol': 1e-9, 'atol': 1e-11}
    config['case_integration_overrides'][plans[key]['ucs']] = {'copasi': setting}
    cases, branches, baseline = producer.compile_scope(plans, summaries, reference, config)
    for trial in cases[key]['potential_trials'].values():
        for bid in trial['branches'].values():
            assert branches[bid]['integration_settings']['copasi'] == setting
    assert branches[baseline]['integration_settings'] == config['integration_settings']


@pytest.mark.parametrize('change', ['drop_control', 'drop_case', 'drop_third_trial', 'reset', 'horizon',
                                   'original_record', 'generated_origin', 'sample_grid', 'recover_case', 'omit_failure'])
def test_tampered_complete_inventory_is_rejected(tmp_path, monkeypatch, inventory, change):
    altered = deepcopy(inventory)
    case = altered['cases'][next(iter(altered['cases']))]
    if change == 'drop_control':
        del altered['branches'][altered['generated_potential_branch_ids'][0]]
    elif change == 'drop_case':
        del altered['cases'][next(iter(altered['cases']))]
    elif change == 'drop_third_trial':
        del case['potential_trials'][next(k for k in case['potential_trials'] if k.startswith('third__'))]
    elif change == 'reset':
        next(b for b in altered['branches'].values() if b['reset_trains'])['reset_trains'][0]['start'] += .1
    elif change == 'horizon':
        altered['branches'][altered['full_untreated_control']]['stop'] = 300.
    elif change == 'original_record':
        altered['original_failed_branch_records'].pop()
    elif change == 'generated_origin':
        altered['branch_origins'][altered['generated_potential_branch_ids'][0]] = {'kind': 'observed_original'}
    elif change == 'sample_grid':
        altered['branch_observations'][altered['full_untreated_control']]['sample_grid_sha256'] = '0' * 64
    elif change == 'recover_case':
        altered['case_recovery_claimed'] = True
    else:
        altered['diagnostic_branch_ids'].pop()
    path = tmp_path / 'inventory.json'
    path.write_text(json.dumps(altered))
    monkeypatch.setattr(producer, 'build', lambda: deepcopy(inventory))
    with pytest.raises(ValueError, match='Complete inventory does not reproduce'):
        producer.check(path)


def test_capture_never_overwrites_an_existing_inventory(tmp_path, monkeypatch):
    path = tmp_path / 'existing.json'
    path.write_text('original')
    monkeypatch.setattr(producer, 'build', lambda: pytest.fail('Must refuse before reading inputs'))
    with pytest.raises(ValueError, match='new inventory path'):
        producer.capture(path)
    assert path.read_text() == 'original'


def test_symlink_output_is_rejected_even_if_target_is_absent(tmp_path):
    path = tmp_path / 'link.json'
    path.symlink_to(tmp_path / 'missing')
    with pytest.raises(ValueError, match='new inventory path'):
        producer.capture(path)


@pytest.mark.parametrize('relative', ['results/catalog-breaking-linux-30/audit.json',
                                     'results/catalog-breaking-linux-30/shard-0/BIOMD0000000039.json',
                                     'models/BIOMD0000000039.xml', 'grn_memory/catalog_breaking.py'])
def test_changed_original_inputs_are_rejected(tmp_path, monkeypatch, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text('changed')
    monkeypatch.setattr(producer, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='Pinned source differs'):
        producer.pin(path, {})


def test_genuine_capture_and_fresh_check_are_identical(tmp_path):
    path = tmp_path / 'inventory.json'
    assert producer.capture(path) == producer.check(path)
