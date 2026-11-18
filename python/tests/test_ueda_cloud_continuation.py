import json
from pathlib import Path
import shutil

import pytest

from scripts.continue_ueda_cases import digest, load_inputs, selected
from scripts.prepare_ueda_continuation import select_remaining

INPUTS = Path(__file__).resolve().parents[1] / 'results/catalog-breaking-ueda-continuation-20261118'


def test_every_original_branch_is_accounted_for_once():
    plan, report, inventory, *_ = load_inputs(INPUTS, digest(INPUTS/'continuation-plan.json'))
    parts = [selected(plan, i) for i in range(plan['shard_count'])]
    computed = [bid for part in parts for bid in part]
    assert len(computed) == len(set(computed))
    assert sorted(computed) == plan['selected_branch_ids']
    assert set(computed).isdisjoint(plan['preserved_complete_branch_ids'])
    assert set(computed).isdisjoint(plan['imported_branch_ids'])
    assert set(computed) | set(plan['preserved_complete_branch_ids']) | set(plan['imported_branch_ids']) == set(inventory['branches'])
    assert len(inventory['branches']) == 323
    assert len(inventory['cases']) == 4
    assert plan['requests'] == report['requests']


@pytest.mark.parametrize('index', [-1, 32, 0.0, True])
def test_rejects_invalid_partition(index):
    plan = json.loads((INPUTS/'continuation-plan.json').read_text())
    with pytest.raises(Exception, match='Invalid fixed partition'):
        selected(plan, index)


@pytest.mark.parametrize('mutation', ['omit_branch', 'loosen_tolerance', 'omit_import'])
def test_changed_plan_cannot_hide_missing_evidence_or_change_numerics(tmp_path, mutation):
    copied = tmp_path/'inputs'
    shutil.copytree(INPUTS, copied)
    path = copied/'continuation-plan.json'
    plan = json.loads(path.read_text())
    if mutation == 'omit_branch':
        plan['selected_branch_ids'].pop()
    elif mutation == 'loosen_tolerance':
        plan['acceptance']['rtol'] *= 10
    else:
        plan['imported_branch_ids'].pop()
    path.write_text(json.dumps(plan))
    with pytest.raises(Exception, match='must be selected|settings differ'):
        load_inputs(copied, digest(path))


def test_missing_original_control_rejected_even_with_new_plan_digest(tmp_path):
    copied = tmp_path/'inputs'
    shutil.copytree(INPUTS, copied)
    path = copied/'original-case-plan.json'
    value = json.loads(path.read_text())
    value['cases'].pop(next(iter(value['cases'])))
    path.write_text(json.dumps(value))
    with pytest.raises(Exception):
        load_inputs(copied, digest(copied/'continuation-plan.json'))


def test_selection_preserves_all_available_evidence_regardless_of_outcome():
    inventory = {'branches': {'passing': {}, 'mismatching': {}, 'absent': {}, 'published': {}}}
    assert select_remaining(inventory, ['passing', 'mismatching'], ['published']) == ['absent']
    with pytest.raises(Exception, match='outside original inventory'):
        select_remaining(inventory, ['unrelated'], [])
    with pytest.raises(Exception, match='Duplicate'):
        select_remaining(inventory, ['passing', 'passing'], [])
