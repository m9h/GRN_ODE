"""The transfer batch must never change the scientific selection."""
import pytest
from scripts import preserve_ciliberto_archives as courier


def test_complete_source_scope_and_all_177_archive_identities():
    result = courier.validate()
    assert result['archives'] == 177 and result['bytes'] == 434442559593
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
