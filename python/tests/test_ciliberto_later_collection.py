"""Fixed-run transport and interruption checks with synthetic full-grid arrays."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from scripts import collect_ciliberto_later_controls as collector
from test_ciliberto_later_controls import context, synthetic, save


def api_fixture():
    run = {**collector.RUN, 'event': 'workflow_dispatch'}
    gate = {'id': collector.GATE, 'name': 'validation', 'run_id': run['id'], 'run_attempt': 1,
            'head_sha': run['head_sha'], 'status': 'completed', 'conclusion': 'success'}
    jobs = [gate] + [{**gate, 'id': 140000000000 + i, 'name': f'ciliberto-later-controls-{i}',
                     'status': 'queued', 'conclusion': None} for i in range(256)]
    return run, {'total_count': 257, 'jobs': jobs}


def test_all_256_jobs_and_6859_controls_bound_once(context):
    run, jobs = api_fixture()
    result = collector.bind_selection(context[0], run, jobs)
    assert len(result['selected']) == 256
    assert sum(len(row['branches']) for row in result['selected']) == 6859
    assert result['required_full_branches'] == 7334 and result['required_full_cases'] == 74
    assert not result['case_recovery_claimed'] and result['full_case_audit_required']


@pytest.mark.parametrize('change', ['first_page_only', 'queued_gate', 'failed_gate', 'wrong_gate',
                                   'missing_job', 'duplicate_id', 'wrong_name', 'attempt', 'source'])
def test_incomplete_pages_or_changed_job_identity_rejected(context, change):
    run, jobs = api_fixture()
    if change == 'first_page_only': jobs['jobs'] = jobs['jobs'][:100]
    elif change == 'queued_gate': jobs['jobs'][0].update(status='queued', conclusion=None)
    elif change == 'failed_gate': jobs['jobs'][0]['conclusion'] = 'failure'
    elif change == 'wrong_gate': jobs['jobs'][0]['id'] += 1
    elif change == 'missing_job': jobs['jobs'].pop(); jobs['total_count'] -= 1
    elif change == 'duplicate_id': jobs['jobs'][-1]['id'] = jobs['jobs'][-2]['id']
    elif change == 'wrong_name': jobs['jobs'][-1]['name'] = 'different'
    elif change == 'attempt': jobs['jobs'][-1]['run_attempt'] = 2
    elif change == 'source': run['head_sha'] = 'different'
    with pytest.raises(ValueError):
        collector.bind_selection(context[0], run, jobs)


@pytest.mark.parametrize('change', ['remove_branch', 'origin', 'job', 'artifact', 'plan', 'full_scope', 'claim'])
def test_fixed_selection_cannot_shrink_or_change(context, change):
    selection = collector.bind_selection(context[0], *api_fixture())
    if change == 'remove_branch': selection['selected'][0]['branches'].pop()
    elif change == 'origin': selection['selected'][0]['branches'][0]['origin'] = 'invented'
    elif change == 'job': selection['selected'][0]['job_id'] = collector.GATE
    elif change == 'artifact': selection['selected'][0]['artifact_name'] = 'wrong'
    elif change == 'plan': selection['plan_sha256'] = 'wrong'
    elif change == 'full_scope': selection['required_full_branches'] = 6859
    elif change == 'claim': selection['case_recovery_claimed'] = True
    with pytest.raises(ValueError):
        collector.validate_selection(selection, context[0])


@pytest.fixture
def branch(synthetic, context, tmp_path):
    directory = tmp_path / 'branch'
    shutil.copytree(synthetic, directory)
    report = collector.read(directory / 'report.json')
    report.update(source_revision=collector.RUN['head_sha'], run_id=str(collector.RUN['id']),
                  run_attempt='1', plan_sha256=collector.PLAN_SHA)
    collector.write(directory / 'report.json', report)
    bid = report['record_id']
    row = next(row for part in context[0]['partitions'] for row in part['branches'] if row['record_id'] == bid)
    entry = {**row, 'status': 'time_limit', 'error': 'Synthetic wrapper interruption'}
    return directory, row, entry


def verify(branch, context):
    return collector.verify_branch(*branch, context)


def test_complete_child_survives_wrapper_interruption(branch, context):
    result = verify(branch, context)
    assert result['complete_diagnostic'] and result['verified_arrays'] == 4
    assert result['producer_outcome']['status'] == 'time_limit'
    assert result['status'] == 'confirmed'


def interrupt(branch, context, *, orphan=False, terminal_record=False):
    directory, row, entry = branch
    report = collector.read(directory / 'report.json')
    record = collector.read(directory / (row['record_id'] + '.json'))
    if not terminal_record:
        record['integrations'].pop('scipy_refined')
        record['traces'].pop('scipy_refined')
        record.update(status='running', comparisons={})
        if not orphan:
            (directory / (row['record_id'] + '-scipy_refined.npz')).unlink()
    save(directory, report, record, context)
    report.update(status='running', branch=None)
    collector.write(directory / 'report.json', report)


def test_partial_arrays_verified_but_diagnostic_remains_incomplete(branch, context):
    interrupt(branch, context)
    result = verify(branch, context)
    assert not result['complete_diagnostic'] and result['verified_arrays'] == 3
    assert len(result['comparisons']) == 3 and result['status'] == 'interrupted'


def test_orphan_array_remains_unverified(branch, context):
    interrupt(branch, context, orphan=True)
    result = verify(branch, context)
    assert result['verified_arrays'] == 3 and len(result['unverified_arrays']) == 1
    assert not result['complete_diagnostic']


def test_complete_record_without_terminal_report_is_not_promoted(branch, context):
    interrupt(branch, context, terminal_record=True)
    result = verify(branch, context)
    assert result['verified_arrays'] == 4 and not result['complete_diagnostic']
    assert len(result['comparisons']) == 6


@pytest.mark.parametrize('change', ['source', 'attempt', 'plan', 'branch', 'request', 'resets', 'claimed_complete'])
def test_partial_evidence_identity_and_reset_checks(branch, context, change):
    interrupt(branch, context)
    directory, row, entry = branch
    report = collector.read(directory / 'report.json')
    record = collector.read(directory / (row['record_id'] + '.json'))
    if change == 'source': report['source_revision'] = 'wrong'
    elif change == 'attempt': report['run_attempt'] = '2'
    elif change == 'plan': report['plan_sha256'] = 'wrong'
    elif change == 'branch': record['record_id'] = 'wrong'
    elif change == 'request': record['integrations']['scipy']['request'] = {'rtol': 1.}
    elif change == 'resets': record['integrations']['scipy']['performed_resets'] -= 1
    elif change == 'claimed_complete': entry['status'] = 'confirmed'
    collector.write(directory / 'report.json', report)
    collector.write(directory / (row['record_id'] + '.json'), record)
    with pytest.raises(ValueError):
        verify(branch, context)


def test_truncated_temporary_checkpoint_is_never_parsed(branch, context):
    interrupt(branch, context)
    (branch[0] / (branch[1]['record_id'] + '.tmp')).write_bytes(b'{unfinished')
    result = verify(branch, context)
    assert result['unverified_checkpoint_files'] == [branch[1]['record_id'] + '.tmp']
    assert not result['complete_diagnostic']


def partition_fixture(branch, context, tmp_path):
    directory, branch_row, entry = branch
    plan = context[0]
    part = next(p for p in plan['partitions'] if branch_row in p['branches'])
    run, jobs = api_fixture()
    selection = collector.bind_selection(plan, run, jobs)
    row = selection['selected'][part['index']]
    root = tmp_path / 'partition'
    root.mkdir()
    shutil.copytree(directory, root / branch_row['record_id'])
    prefix = []
    for selected in row['branches']:
        if selected == branch_row:
            prefix.append(entry)
            break
        prefix.append({**selected, 'status': 'execution_or_audit_failure', 'error': 'Synthetic early child failure'})
    validation = {'complete_input_scope_verified': True, 'synthetic_test_fixture': True}
    collector.write(root / 'input-validation.json', validation)
    execution = {'model_id': plan['model_id'], 'plan_sha256': collector.PLAN_SHA,
        'partition_index': row['index'], 'selected_branches': row['branches'], 'expected_branches': len(row['branches']),
        'metadata': collector.producer.metadata_for(plan), 'source_revision': collector.RUN['head_sha'],
        'wrapper_sha256': collector.digest(collector.ROOT / 'scripts/run_ciliberto_later_controls.py'),
        'run_id': str(collector.RUN['id']), 'run_attempt': '1',
        'input_validation_sha256': collector.digest(root / 'input-validation.json'),
        'case_recovery_claimed': False, 'full_model_coverage_claimed': False, 'full_case_audit_required': True,
        'branches': prefix, 'status': 'incomplete', 'confirmed_branches': 0}
    collector.write(root / 'execution.json', execution)
    return root, row, execution, validation, selection, run, jobs


def test_partition_preserves_every_unattempted_control(branch, context, tmp_path):
    root, row, execution, validation, *_ = partition_fixture(branch, context, tmp_path)
    result = collector.verify_partition(root, row, context, execution['wrapper_sha256'], validation)
    assert len(result['branches']) == len(row['branches'])
    assert not result['complete_selected_diagnostics']
    assert sum(b['verified_arrays'] for b in result['branches']) == 4


def test_missing_initial_execution_checkpoint_cannot_create_completion(context, tmp_path):
    selection = collector.bind_selection(context[0], *api_fixture())
    (tmp_path / 'execution.json.tmp').write_bytes(b'partial')
    result = collector.verify_partition(tmp_path, selection['selected'][0], context, 'unused', {})
    assert result['producer_status'] == 'no_execution_checkpoint'
    assert result['unverified_checkpoint_files'] == ['execution.json.tmp']
    assert not result['complete_selected_diagnostics'] and all(b['status'] == 'not_started' for b in result['branches'])


@pytest.mark.parametrize('change', ['prefix', 'scope', 'source', 'validation', 'count', 'stop'])
def test_partition_lineage_and_aggregate_cannot_change(branch, context, tmp_path, change):
    root, row, execution, validation, *_ = partition_fixture(branch, context, tmp_path)
    if change == 'prefix': execution['branches'][-1]['sample_count'] -= 1
    elif change == 'scope': execution['full_case_audit_required'] = False
    elif change == 'source': execution['source_revision'] = 'wrong'
    elif change == 'validation': execution['input_validation_sha256'] = 'wrong'
    elif change == 'count': execution['confirmed_branches'] = 100
    elif change == 'stop': execution['stop_reason'] = 'success'
    collector.write(root / 'execution.json', execution)
    with pytest.raises(ValueError):
        collector.verify_partition(root, row, context, execution['wrapper_sha256'], validation)


def test_collect_failed_job_and_detect_changed_cached_evidence(branch, context, tmp_path, monkeypatch):
    root, row, execution, validation, selection, run, jobs = partition_fixture(branch, context, tmp_path)
    job = next(j for j in jobs['jobs'] if j['id'] == row['job_id'])
    job.update(status='completed', conclusion='timed_out', started_at='2026-11-18T23:00:00Z', completed_at='2026-11-19T05:00:00Z')
    archives = tmp_path / 'archives'
    archives.mkdir()
    archive = archives / 'artifact-1.zip'
    with zipfile.ZipFile(archive, 'w') as stream:
        for path in root.rglob('*'):
            if path.is_file(): stream.write(path, path.relative_to(root))
    artifact = {'id': 1, 'name': row['artifact_name'], 'expired': False, 'workflow_run': {
        'id': run['id'], 'head_sha': run['head_sha']}, 'created_at': '2026-11-19T04:59:00Z',
        'digest': 'sha256:' + collector.digest(archive), 'size_in_bytes': archive.stat().st_size}
    snapshots = tmp_path / 'api'
    snapshots.mkdir()
    for name, value in [('run', run), ('jobs', jobs), ('artifacts', {'total_count': 1, 'artifacts': [artifact]})]:
        collector.write(snapshots / (name + '.json'), value)
    selection_path = tmp_path / 'selection.json'
    collector.write(selection_path, selection)
    monkeypatch.setattr(collector.producer, 'load_plan', lambda *a: context)
    monkeypatch.setattr(collector.producer.inputs, 'validate', lambda *a: validation)
    output = tmp_path / 'collected'
    args = (tmp_path / 'plan', tmp_path / 'inputs', selection_path, snapshots, archives, output)
    result = collector.collect(*args)
    assert result['status'] == 'incomplete' and not result['collection_errors']
    assert result['verified_arrays'] == 4 and len(result['pending_indices']) == 255
    assert result['partitions'][0]['job_conclusion'] == 'timed_out'
    assert result['run'] == collector.RUN and result['plan_sha256'] == collector.PLAN_SHA
    assert result['collector_script_sha256'] == collector.digest(Path(collector.__file__))
    assert result['transport_script_sha256'] == collector.digest(collector.ROOT / 'scripts/collect_ciliberto_full_diagnostics.py')
    preserved = Path(result['preserved_api_snapshots']['directory'])
    assert {p.name for p in preserved.iterdir()} == {'selection.json', 'run.json', 'jobs.json', 'artifacts.json'}
    original = (preserved / 'jobs.json').read_bytes()
    collector.write(snapshots / 'jobs.json', {**jobs, 'extra_snapshot_information': True})
    assert (preserved / 'jobs.json').read_bytes() == original
    evidence = Path(result['partitions'][0]['evidence'])
    (evidence / 'execution.json').write_text('{}')
    failed = collector.collect(*args)
    assert failed['status'] == 'verification_failed' and failed['collection_errors']
    assert not failed['complete_selected_diagnostics']


def test_all_pending_jobs_never_claim_completion(context, tmp_path, monkeypatch):
    run, jobs = api_fixture()
    selection = collector.bind_selection(context[0], run, jobs)
    collector.write(tmp_path / 'selection.json', selection)
    for name, value in [('run', run), ('jobs', jobs), ('artifacts', {'total_count': 0, 'artifacts': []})]:
        collector.write(tmp_path / (name + '.json'), value)
    monkeypatch.setattr(collector.producer, 'load_plan', lambda *a: context)
    monkeypatch.setattr(collector.producer.inputs, 'validate', lambda *a: {})
    result = collector.collect(tmp_path / 'plan', tmp_path, tmp_path / 'selection.json', tmp_path, tmp_path, tmp_path / 'output')
    assert len(result['pending_indices']) == 256 and result['verified_arrays'] == 0
    assert not result['complete_selected_diagnostics'] and not result['all_6859_controls_confirmed']
