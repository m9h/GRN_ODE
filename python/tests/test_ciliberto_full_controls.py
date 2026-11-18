"""Full-case input scope and source-provenance checks; no ODE integration."""

from copy import deepcopy
import gzip

import pytest

from scripts import prepare_ciliberto_full_controls as adapter


@pytest.fixture(scope='module')
def real():
    source = adapter.read(adapter.SOURCE / 'inventory.json')
    summaries = adapter.read(adapter.ORIGINAL / 'audit.json')['case_summaries']
    reference = adapter.read(adapter.ROOT / 'results/catalog-repeated' / (adapter.MODEL + '.json'))
    config = adapter.read(adapter.ORIGINAL / 'shard-0' / (adapter.MODEL + '.json'))['configuration']
    return source, summaries, reference, config


def test_every_failed_case_and_generated_control_has_explicit_origin(real):
    inventory = adapter.reconstruct(*real)
    assert inventory['selected_cases'] == 74 and inventory['expected_model_cases'] == 622
    assert len(inventory['branches']) == 7334
    assert inventory['original_observed_branch_specifications'] == 7134
    generated = set(inventory['generated_potential_branch_ids'])
    assert len(generated) == 200
    assert generated.isdisjoint(real[0]['original_occurrences'])
    assert all(inventory['branch_origins'][bid] == {
        'kind': 'generated_potential', 'original_record_available': False} for bid in generated)
    assert {key: len(ids) for key, ids in inventory['missing_original_controls_by_case'].items() if ids} == {
        'Kin_a__up--PCdk2_CycE__up': 92, 'PCdk2_CycE__up--Kin_a__up': 92,
        'PCdk2_CycErem__up--Kin_a__up': 8, 'Xic_PCdk2_CycE__up--Deg_a__up': 8}
    assert inventory['conditional_search_must_be_recomputed']
    assert not inventory['case_recovery_claimed'] and not inventory['full_model_coverage_claimed']


def test_published_two_case_controls_are_exactly_preserved(real):
    inventory = adapter.reconstruct(*real)
    old = adapter.read(adapter.ROOT / 'results/catalog-breaking-ciliberto-case-recovery-20261118/inventory.json')
    assert len(old['branches']) == 215
    assert {bid: inventory['branches'][bid] for bid in old['branches']} == old['branches']
    assert inventory['full_untreated_control'] == old['full_untreated_control']
    for key, case in old['cases'].items():
        assert {field: inventory['cases'][key][field] for field in case} == case


@pytest.mark.parametrize('change', ['drop_control', 'change_stop', 'change_reset', 'drop_case',
                                   'invent_original', 'remove_occurrence', 'duplicate_occurrence',
                                   'change_missing_partition', 'baseline_without_source'])
def test_reconstructed_scope_cannot_be_relaxed(real, change):
    source, summaries, reference, config = deepcopy(real)
    bid = next(iter(source['branches']))
    observed = next(iter(source['original_occurrences']))
    generated = next(iter(source['branches'].keys() - source['original_occurrences'].keys()))
    if change == 'drop_control': del source['branches'][generated]
    elif change == 'change_stop': source['branches'][bid]['stop'] -= 400
    elif change == 'change_reset':
        key = next(k for k, spec in source['branches'].items() if spec['reset_trains'])
        source['branches'][key]['reset_trains'][0]['start'] += .01
    elif change == 'drop_case': source['cases'].pop(next(iter(source['cases'])))
    elif change == 'invent_original': source['original_occurrences'][generated] = deepcopy(source['original_occurrences'][observed])
    elif change == 'remove_occurrence': del source['original_occurrences'][observed]
    elif change == 'duplicate_occurrence': source['original_occurrences'][observed] *= 2
    elif change == 'change_missing_partition':
        key = next(k for k, value in source['potential_branches_absent_from_original_case_partition'].items() if value)
        source['potential_branches_absent_from_original_case_partition'][key].pop()
    elif change == 'baseline_without_source': del source['original_occurrences'][source['full_untreated_control']]
    with pytest.raises(ValueError):
        adapter.reconstruct(source, summaries, reference, config)


def original_record_fixture(real):
    source = real[0]
    for part in source['source_partitions']:
        captured = adapter.read(adapter.SOURCE / part['file'])
        if captured['failed_branches']:
            record = deepcopy(captured['failed_branches'][0])
            bid = record['record_id']
            inventory = {'branches': {bid: source['branches'][bid]},
                         'branch_origins': {bid: {'occurrences': source['original_occurrences'][bid]}}}
            info = adapter.inspect_model(adapter.ROOT / 'models' / (adapter.MODEL + '.xml'))
            return inventory, part['index'], {bid: record}, captured['original_report'], info['observables']
    raise AssertionError('No original failed record')


def test_original_failure_stays_auditable_and_failed(real):
    inventory, index, records, report, names = original_record_fixture(real)
    assert not next(iter(records.values()))['passed']
    adapter.verify_records(inventory, index, records, report, names)


@pytest.mark.parametrize('change', ['record_bytes', 'record_id', 'missing', 'invented'])
def test_original_record_identity_is_not_interchangeable(real, change):
    inventory, index, records, report, names = original_record_fixture(real)
    bid = next(iter(records))
    if change == 'record_bytes': records[bid]['passed'] = True
    elif change == 'record_id': records[bid]['record_id'] = '0' * 64
    elif change == 'missing': records.clear()
    elif change == 'invented': records['f' * 64] = deepcopy(records[bid])
    with pytest.raises(ValueError):
        adapter.verify_records(inventory, index, records, report, names)


def test_record_transport_is_deterministic_and_preserves_original_records(real, tmp_path):
    records = original_record_fixture(real)[2]
    first, second = tmp_path / 'first.gz', tmp_path / 'second.gz'
    adapter.write_records(first, records)
    adapter.write_records(second, records)
    assert first.read_bytes() == second.read_bytes()
    assert adapter.read_records(first) == records


def test_duplicate_original_record_is_rejected(tmp_path):
    path = tmp_path / 'duplicate.gz'
    with gzip.open(path, 'wt') as stream:
        stream.write('{"record_id": "same"}\n' * 2)
    with pytest.raises(ValueError, match='Duplicate'):
        adapter.read_records(path)


def test_changed_manifest_is_rejected_before_use(tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{}\n')
    expected = adapter.digest(manifest)
    manifest.write_text('{"changed":true}\n')
    with pytest.raises(ValueError, match='Pinned full-control manifest'):
        adapter.validate(tmp_path, expected)


def test_real_input_model_and_full_grid_are_preserved():
    inventory, path, info, grid = adapter.prepare_inventory()
    assert path.name == 'BIOMD0000000697.xml'
    assert len(info['observables']) == 20
    assert len(grid) == 221001 and grid[0] == 0 and grid[-1] == 2210
    assert len(inventory['branches']) == 7334
    assert inventory['acceptance'] == {'rtol': 2e-5, 'atol': 1e-7}
    assert inventory['requests'] == adapter.read(adapter.SOURCE / 'inventory.json')['requests']
