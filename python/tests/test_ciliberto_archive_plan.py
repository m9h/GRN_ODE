"""The transfer batch must never change the scientific selection."""
from copy import deepcopy
import pytest
from scripts import preserve_ciliberto_archives as courier


def test_complete_source_scope_and_all_198_archive_identities():
    result = courier.validate()
    assert result['archives'] == 198 and result['bytes'] == 486059082836
    assert result['full_scientific_partitions'] == 256
    assert result['full_scientific_branches'] == 7334
    assert result['numerical_integrations_performed'] == 0


def test_transfer_pilot_retains_full_required_inventory():
    rows = courier.selected_rows([0])
    assert [r['index'] for r in rows] == [0]
    assert rows[0]['artifact']['id'] == 14517099024
    assert len(courier.load_plan()['selected']) == 256
    assert courier.load_plan()['required_cases'] == 74


@pytest.mark.parametrize('indices', [[], [0, 0], [True], [-1], [256], ['0'], [43], {}])
def test_invalid_or_missing_archive_cannot_be_dispatched(indices):
    with pytest.raises(ValueError):
        courier.selected_rows(indices)


@pytest.mark.parametrize('field,value', [
    ('id', 1), ('size_in_bytes', 1), ('digest', 'sha256:' + '0' * 64),
    ('name', 'different-original-output'), ('created_at', '2026-01-01T00:00:00Z'),
    ('workflow_run', {'id': 1}),
])
def test_refresh_cannot_replace_an_earlier_original_archive(field, value):
    plan = deepcopy(courier.load_plan())
    plan['selected'][0]['artifact'][field] = value
    with pytest.raises(ValueError, match='Previously captured archive identity changed'):
        courier.validate_capture_ancestry(plan)


def test_refresh_cannot_drop_earlier_archive_or_scientific_partition():
    plan = deepcopy(courier.load_plan())
    plan['selected'][0]['artifact'] = None
    with pytest.raises(ValueError, match='Previously captured archive omitted'):
        courier.validate_capture_ancestry(plan)
    plan = deepcopy(courier.load_plan())
    plan['selected'].pop()
    with pytest.raises(ValueError, match='All original partitions'):
        courier.validate_capture_ancestry(plan)


def test_newly_available_partition194_keeps_the_original_route():
    row = courier.selected_rows([194])[0]
    assert row['artifact']['id'] == 15156719852
    assert row['release_tag'] == 'kinetics-ciliberto-archives-20261126-g06'
