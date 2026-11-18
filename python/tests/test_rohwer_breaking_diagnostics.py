import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts import run_rohwer_breaking_diagnostics as runner

INPUTS = runner.ROOT/'results/catalog-breaking-rohwer-diagnostics-20261118'
PLAN_SHA = 'ab0f50d411a929a887fdf5132958502ec11a2af620cd577b8fc40f5994b4b9f0'


def test_complete_real_selection():
    plan = runner.check(INPUTS, PLAN_SHA, check_runtime=False)
    rows = [b for part in plan['partitions'] for b in part['branches']]
    assert len(rows) == len({b['record_id'] for b in rows}) == 750
    assert len(plan['original_failed_cases']) == 123
    assert {len(p['branches']) for p in plan['partitions']} == {23, 24}
    assert plan['failure_kinds'] == {'completed_mismatch': 466, 'incomplete_output': 284}


def test_plan_checksum_required():
    with pytest.raises(ValueError, match='checksum'):
        runner.check(INPUTS, '0'*64, check_runtime=False)


@pytest.mark.parametrize('change', ['drop_branch', 'duplicate_branch', 'wrong_partition',
                                  'omit_source', 'source_hash', 'model_hash', 'requests',
                                  'acceptance', 'case_inventory', 'recovery_claim'])
def test_reject_changed_inventory_even_with_matching_plan_bytes(monkeypatch, change):
    original_read = runner.read
    plan = copy.deepcopy(original_read(INPUTS/'plan.json'))
    if change == 'drop_branch':
        plan['partitions'][0]['branches'].pop()
    elif change == 'duplicate_branch':
        plan['partitions'][0]['branches'][0] = plan['partitions'][1]['branches'][0]
    elif change == 'wrong_partition':
        plan['partitions'][0]['branches'][0]['source_partition'] = 15
    elif change == 'omit_source':
        plan['source_partitions'].pop()
    elif change == 'source_hash':
        plan['source_partitions'][0]['sha256'] = '0'*64
    elif change == 'model_hash':
        plan['model_sha256'] = '0'*64
    elif change == 'requests':
        plan['requests']['rtol'] = 1e-5
    elif change == 'acceptance':
        plan['acceptance']['rtol'] = 1e-2
    elif change == 'case_inventory':
        plan['original_failed_cases'].pop()
    else:
        plan['case_recovery_claimed'] = True
    monkeypatch.setattr(runner, 'read', lambda path: plan if Path(path) == INPUTS/'plan.json'
                        else original_read(path))
    with pytest.raises(ValueError):
        runner.check(INPUTS, PLAN_SHA, check_runtime=False)


def test_changed_runtime_rejected(monkeypatch):
    monkeypatch.setattr(runner, 'runtime', lambda: {})
    with pytest.raises(ValueError, match='sources or package versions'):
        runner.check(INPUTS, PLAN_SHA)


@pytest.mark.parametrize('change', ['duplicate', 'passing', 'wrong_model'])
def test_source_failure_selection_rejects_invalid_records(change):
    branch = {'record_id': 'a', 'sample_count': 221001, 'passed': False}
    source = {'original_report': {'network': 35, 'biomodel_id': runner.MODEL},
              'failed_branches': [branch]}
    if change == 'duplicate':
        source['failed_branches'].append(dict(branch))
    elif change == 'passing':
        branch['passed'] = True
    else:
        source['original_report']['biomodel_id'] = 'BIOMD0000000035'
    with pytest.raises(ValueError):
        runner.assignments([source])


@pytest.mark.parametrize('outcome', ['confirmed', 'mismatch', 'timeout', 'nonzero', 'audit_error'])
def test_worker_retains_all_terminal_outcomes(tmp_path, monkeypatch, outcome):
    from scripts import audit_scipy_breaking
    row = {'record_id': 'a'*64, 'source_partition': 0, 'sample_count': 221001}
    plan = {'partitions': [{'branches': [row]}]}
    monkeypatch.setattr(runner, 'runtime', lambda: {})
    monkeypatch.setattr(runner.subprocess, 'check_output', lambda *a, **k: 'f'*40)
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '1')

    def run(command, **kwargs):
        assert command[command.index('--branch')+1] == row['record_id']
        assert command[command.index('--reference-rtol')+1] == '1e-13'
        directory = Path(command[command.index('--output')+1])
        directory.mkdir()
        (directory/'report.json').write_text('{}')
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        return SimpleNamespace(returncode=3 if outcome == 'nonzero' else 0)

    def audit(directory):
        if outcome == 'audit_error':
            raise ValueError('Saved comparison changed')
        return {'all_selected_branches_confirmed': outcome == 'confirmed'}

    monkeypatch.setattr(runner.subprocess, 'run', run)
    monkeypatch.setattr(audit_scipy_breaking, 'audit', audit)
    output = tmp_path/'result'
    code = runner.compute(INPUTS, plan, 0, output, 30)
    result = json.loads((output/'execution.json').read_text())
    assert result['run_id'] == '123' and result['run_attempt'] == '1'
    assert result['selected_branches'] == [row]
    assert result['case_recovery_claimed'] is False
    assert (output/row['record_id']/'report.json').exists()
    assert code == (0 if outcome == 'confirmed' else 2)
    expected = {'confirmed': 'confirmed', 'mismatch': 'numerical_failure', 'timeout': 'time_limit',
                'nonzero': 'execution_or_audit_failure', 'audit_error': 'execution_or_audit_failure'}
    assert result['branches'][0]['status'] == expected[outcome]
    assert result['status'] == ('completed' if outcome in ('confirmed', 'mismatch') else 'incomplete')


def test_worker_never_overwrites_existing_evidence(tmp_path):
    with pytest.raises(ValueError, match='new output'):
        runner.compute(INPUTS, {}, 0, tmp_path, 30)
