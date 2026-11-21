"""Exercise preservation and scheduling using full-grid synthetic evidence."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess

import pytest

from scripts import continue_rohwer_first as c
from test_rohwer_breaking_collection import branch, synthetic, refresh, interrupt


def test_all_original_scope_and_api_bindings():
    plan, requirements, selection, artifacts = c.check_bindings(check_runtime=False)
    assert len(selection['selected']) == len(artifacts['artifacts']) == 32
    assert sum(len(p['branches']) for p in plan['partitions']) == 750
    assert sum(len(p['preserve_complete_branch_ids']) for p in requirements['partitions']) == 166
    assert sum(len(p['resume_partial_branch_ids']) for p in requirements['partitions']) == 32
    assert sum(len(p['unattempted_branch_ids']) for p in requirements['partitions']) == 552


def test_changed_pinned_parent_rejected(tmp_path):
    bindings = tmp_path/'bindings'
    shutil.copytree(c.BINDINGS, bindings)
    with (bindings/'continuation-requirements.json').open('a') as stream:
        stream.write(' ')
    with pytest.raises(ValueError, match='Pinned parent'):
        c.check_bindings(bindings, check_runtime=False)


def setup_parent(branch, *, partial=False, terminal='confirmed', unattempted=False):
    directory, row, entry, inputs, plan = branch
    bid = row['record_id']
    if terminal == 'failure':
        record = c.read(directory/(bid+'.json'))
        saved = record['traces'].pop('scipy_refined')
        (directory/saved['file']).unlink()
        record['integrations']['scipy_refined'].update(completed=False, error='Synthetic solver failure')
        record['status'] = 'incomplete'
        refresh(branch, record, recompute=True)
    elif terminal == 'mismatch':
        import numpy as np
        record = c.read(directory/(bid+'.json'))
        saved = record['traces']['scipy_refined']
        path = directory/saved['file']
        with np.load(path, allow_pickle=False) as arrays:
            data = {k: arrays[k].copy() for k in arrays.files}
        data['values'][-1, 0] += 1
        np.savez_compressed(path, **data)
        saved['sha256'] = c.digest(path)
        record['status'] = 'mismatch'
        refresh(branch, record, recompute=True)
    if partial:
        interrupt(branch)
        record = c.read(directory/(bid+'.json'))
        saved = record['traces'].pop('scipy_refined')
        (directory/saved['file']).unlink()
        record['integrations']['scipy_refined'] = {'completed': False,
            'request': c.read(directory/'report.json')['requests']['scipy_refined']}
        c.write(directory/(bid+'.json'), record)
    parent = directory.parent/'parent'
    parent.mkdir()
    directory.rename(parent/bid)
    rows = [row]
    if unattempted:
        rows += [deepcopy(plan['partitions'][0]['branches'][1])]
    plan['partitions'][0]['branches'] = rows
    c.write(parent/'execution.json', {'branches': [entry]})
    hashes = {p.relative_to(parent).as_posix(): c.digest(p) for p in parent.rglob('*') if p.is_file()}
    part = {'index': 0, 'parent_job_id': 123, 'parent_artifact_id': 456,
            'parent_archive_sha256': 'sha256:'+'a'*64,
            'parent_execution_sha256': hashes['execution.json'], 'parent_evidence_sha256': hashes,
            'fixed_branch_ids': [b['record_id'] for b in rows],
            'preserve_complete_branch_ids': [] if partial else [bid],
            'resume_partial_branch_ids': [bid] if partial else [],
            'unattempted_branch_ids': [b['record_id'] for b in rows[1:]]}
    requirements = {'partitions': [part]}
    output = parent.parent/'continued'
    c.initialize(parent, output, 0, plan, requirements)
    return output, plan, requirements, inputs


@pytest.mark.parametrize('terminal,status,arrays', [('confirmed', 'diagnostics_confirmed', 4),
    ('mismatch', 'complete_with_numerical_failures', 4), ('failure', 'complete_with_numerical_failures', 3)])
def test_terminal_diagnostics_are_never_reexecuted(branch, monkeypatch, terminal, status, arrays):
    output, plan, requirements, inputs = setup_parent(branch, terminal=terminal)
    def forbidden(*args, **kwargs):
        raise AssertionError('Terminal diagnostic must not be run again')
    monkeypatch.setattr(c.subprocess, 'run', forbidden)
    assert c.compute(output, 0, plan, requirements, 10, inputs) == (0 if terminal == 'confirmed' else 2)
    result = c.audit(output, 0, plan, requirements, inputs)
    assert result['status'] == status
    assert result['parent_arrays_preserved'] == arrays
    assert result['preserved_terminal_diagnostics'] == 1
    assert c.read(output/'execution.json')['attempted_now'] == []


def test_new_work_precedes_partial_without_omitting_either(branch, monkeypatch):
    output, plan, requirements, inputs = setup_parent(branch, partial=True, unattempted=True)
    part = requirements['partitions'][0]
    calls = []
    def timed_out(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    monkeypatch.setattr(c.subprocess, 'run', timed_out)
    assert c.compute(output, 0, plan, requirements, 10, inputs) == 2
    assert [cmd[cmd.index('--branch')+1] for cmd in calls] == part['unattempted_branch_ids']+part['resume_partial_branch_ids']
    assert '--resume' not in calls[0] and '--resume' in calls[1]
    for cmd in calls:
        assert cmd[1] == str(c.ROOT/'scripts/diagnose_scipy_breaking.py')
        for key, value in c.producer.REQUESTS.items():
            assert cmd[cmd.index('--'+key.replace('_', '-'))+1] == str(value)
    result = c.audit(output, 0, plan, requirements, inputs)
    assert result['status'] == 'incomplete' and result['parent_arrays_preserved'] == 3
    assert not result['case_recovery_claimed']


@pytest.mark.parametrize('change', ['array', 'trace_metadata', 'request_metadata', 'lineage', 'scope',
                                    'omission', 'terminal_reexecution', 'source', 'run', 'complete_claim'])
def test_evidence_changes_are_rejected(branch, change):
    output, plan, requirements, inputs = setup_parent(branch, partial=True, unattempted=True)
    bid = requirements['partitions'][0]['resume_partial_branch_ids'][0]
    record_path = output/bid/(bid+'.json')
    record = c.read(record_path)
    execution = c.read(output/'execution.json')
    kwargs = {}
    if change == 'array':
        with (output/bid/record['traces']['roadrunner']['file']).open('ab') as stream: stream.write(b'changed')
    elif change == 'trace_metadata':
        record['traces']['roadrunner']['sha256'] = '0'*64
        c.write(record_path, record)
    elif change == 'request_metadata':
        record['integrations']['roadrunner']['seconds'] = 999
        c.write(record_path, record)
    elif change == 'lineage':
        with (output/'lineage'/(bid+'.json')).open('a') as stream: stream.write(' ')
    elif change == 'scope': execution['selected_branches'].pop()
    elif change == 'omission': execution['work_order'].pop()
    elif change == 'terminal_reexecution': execution['preserved_terminal_ids'].append(bid)
    elif change == 'source': execution['runner_sha256'] = '0'*64
    elif change == 'run': kwargs = {'run_id': '999'}
    else: execution['status'] = 'completed'
    c.write(output/'execution.json', execution)
    with pytest.raises(ValueError):
        c.audit(output, 0, plan, requirements, inputs, **kwargs)


def test_second_compute_call_cannot_silently_restart(branch, monkeypatch):
    output, plan, requirements, inputs = setup_parent(branch)
    assert c.compute(output, 0, plan, requirements, 10, inputs) == 0
    with pytest.raises(ValueError, match='do not restart'):
        c.compute(output, 0, plan, requirements, 10, inputs)


@pytest.mark.parametrize('last_request_passes', [True, False])
def test_partial_continuation_finishes_without_changing_completed_requests(branch, synthetic, monkeypatch,
                                                                         last_request_passes):
    output, plan, requirements, inputs = setup_parent(branch, partial=True)
    bid = requirements['partitions'][0]['resume_partial_branch_ids'][0]
    directory = output/bid
    before = c.read(directory/(bid+'.json'))
    def finish_request(command, **kwargs):
        assert '--resume' in command
        record = c.read(directory/(bid+'.json'))
        report = c.read(directory/'report.json')
        if last_request_passes:
            old = c.read(synthetic[0]/(bid+'.json'))
            saved = old['traces']['scipy_refined']
            shutil.copyfile(synthetic[0]/saved['file'], directory/saved['file'])
            record['traces']['scipy_refined'] = saved
            record['integrations']['scipy_refined'] = old['integrations']['scipy_refined']
        else:
            record['integrations']['scipy_refined'].update(error='Synthetic completed failed attempt')
        from test_rohwer_breaking_collection import comparisons
        record['comparisons'] = comparisons(directory, record)
        record['status'] = 'confirmed' if last_request_passes else 'incomplete'
        c.write(directory/(bid+'.json'), record)
        report.update(status='completed', confirmed_branches=int(last_request_passes),
                      branches=[{'record_id': bid, 'file': bid+'.json',
                                 'sha256': c.digest(directory/(bid+'.json')), 'status': record['status']}])
        c.write(directory/'report.json', report)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(c.subprocess, 'run', finish_request)
    assert c.compute(output, 0, plan, requirements, 30, inputs) == (0 if last_request_passes else 2)
    checked = c.audit(output, 0, plan, requirements, inputs)
    assert checked['complete_selected_diagnostics'] and checked['parent_arrays_preserved'] == 3
    after = c.read(directory/(bid+'.json'))
    for label in before['traces']:
        assert after['traces'][label] == before['traces'][label]
        assert after['integrations'][label] == before['integrations'][label]


def test_restore_rejects_wrong_original_zip_before_extraction(tmp_path):
    plan, requirements, selection, artifacts = c.check_bindings(check_runtime=False)
    archive = tmp_path/'wrong.zip'
    archive.write_bytes(b'wrong artifact')
    with pytest.raises(ValueError, match='Original ZIP differs'):
        c.verify_parent(archive, tmp_path/'evidence', 0, plan, requirements, selection, artifacts)
    assert not (tmp_path/'evidence').exists()


def test_workflow_only_dispatches_fixed_scope_after_validation():
    workflow = (c.ROOT.parent/'.github/workflows/rohwer-first-continuation.yml').read_text()
    assert "inputs.operation == 'compute'" in workflow
    assert 'needs: validation' in workflow
    assert 'index: ['+', '.join(map(str, range(32)))+']' in workflow
    assert 'fetch-depth: 0' in workflow
    assert 'gh api' in workflow and '--archive parent.zip' in workflow
    assert 'timeout-minutes: 360' in workflow and '--budget 19200' in workflow
    assert 'if: ${{ always() }}' in workflow and 'retention-days: 90' in workflow
