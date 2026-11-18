"""Fixed-run transport and interruption checks with synthetic full-grid arrays."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from scripts import collect_rohwer_later_controls as collector
from test_rohwer_later_controls import context, synthetic, save


def api_fixture():
    runs, snapshots = [], []
    for batch in range(2):
        run = {**collector.RUNS[batch], 'event': 'workflow_dispatch'}
        gate = {'id': collector.GATES[batch], 'name': 'validation', 'run_id': run['id'], 'run_attempt': 1,
                'head_sha': run['head_sha'], 'status': 'completed', 'conclusion': 'success'}
        jobs = [gate] + [{**gate, 'id': 140000000000 + i,
                         'name': f'rohwer-later-controls-batch-{batch}-partition-{i}',
                         'status': 'queued', 'conclusion': None} for i in range(batch*256, (batch+1)*256)]
        runs.append(run)
        snapshots.append({'total_count': 257, 'jobs': jobs})
    return runs, snapshots


def snapshots_for(directory, runs, jobs, artifacts=None):
    for batch in range(2):
        target = directory / f'batch-{batch}'
        target.mkdir(parents=True, exist_ok=True)
        for name, value in [('run', runs[batch]), ('jobs', jobs[batch]),
                            ('artifacts', (artifacts or {}).get(batch, {'total_count': 0, 'artifacts': []}))]:
            collector.write(target / (name + '.json'), value)


def test_both_batches_all_512_jobs_and_10924_controls_bound_once(context):
    runs, jobs = api_fixture()
    result = collector.bind_selection(context[0], runs, jobs)
    assert len(result['selected']) == 512 and result['runs'] == collector.RUNS
    assert sum(len(row['branches']) for row in result['selected']) == 10924
    assert result['required_full_branches'] == 11674 and result['required_full_cases'] == 123
    assert [sum(len(row['branches']) for row in result['selected'] if row['batch_index'] == b)
            for b in range(2)] == [5548, 5376]
    assert not result['case_recovery_claimed'] and result['full_case_audit_required']


@pytest.mark.parametrize('batch', [0, 1])
@pytest.mark.parametrize('change', ['first_page_only', 'queued_gate', 'failed_gate', 'wrong_gate',
                                   'missing_job', 'duplicate_id', 'wrong_name', 'attempt', 'source', 'wrong_run'])
def test_incomplete_pages_or_changed_job_identity_rejected(context, batch, change):
    runs, snapshots = api_fixture()
    run, jobs = runs[batch], snapshots[batch]
    if change == 'first_page_only': jobs['jobs'] = jobs['jobs'][:100]
    elif change == 'queued_gate': jobs['jobs'][0].update(status='queued', conclusion=None)
    elif change == 'failed_gate': jobs['jobs'][0]['conclusion'] = 'failure'
    elif change == 'wrong_gate': jobs['jobs'][0]['id'] += 1
    elif change == 'missing_job': jobs['jobs'].pop(); jobs['total_count'] -= 1
    elif change == 'duplicate_id': jobs['jobs'][-1]['id'] = jobs['jobs'][-2]['id']
    elif change == 'wrong_name': jobs['jobs'][-1]['name'] = 'different'
    elif change == 'attempt': jobs['jobs'][-1]['run_attempt'] = 2
    elif change == 'source': run['head_sha'] = 'different'
    elif change == 'wrong_run': jobs['jobs'][-1]['run_id'] = runs[1-batch]['id']
    with pytest.raises(ValueError):
        collector.bind_selection(context[0], runs, snapshots)


@pytest.mark.parametrize('change', ['missing_batch', 'swapped_runs', 'swapped_jobs', 'duplicate_cross_batch_id'])
def test_batches_cannot_be_omitted_swapped_or_share_jobs(context, change):
    runs, jobs = api_fixture()
    if change == 'missing_batch': runs.pop(); jobs.pop()
    elif change == 'swapped_runs': runs.reverse()
    elif change == 'swapped_jobs': jobs.reverse()
    elif change == 'duplicate_cross_batch_id': jobs[1]['jobs'][-1]['id'] = jobs[0]['jobs'][-1]['id']
    with pytest.raises(ValueError):
        collector.bind_selection(context[0], runs, jobs)


@pytest.mark.parametrize('change', ['remove_branch', 'origin', 'job', 'artifact', 'plan', 'full_scope', 'claim', 'batch', 'run', 'partition_bool'])
def test_fixed_selection_cannot_shrink_or_change(context, change):
    selection = collector.bind_selection(context[0], *api_fixture())
    if change == 'remove_branch': selection['selected'][0]['branches'].pop()
    elif change == 'origin': selection['selected'][0]['branches'][0]['origin'] = 'invented'
    elif change == 'job': selection['selected'][0]['job_id'] = collector.GATES[0]
    elif change == 'artifact': selection['selected'][0]['artifact_name'] = 'wrong'
    elif change == 'plan': selection['plan_sha256'] = 'wrong'
    elif change == 'full_scope': selection['required_full_branches'] = 10924
    elif change == 'claim': selection['case_recovery_claimed'] = True
    elif change == 'batch': selection['selected'][0]['batch_index'] = 1
    elif change == 'run': selection['selected'][0]['run_id'] = collector.RUNS[1]['id']
    elif change == 'partition_bool': selection['selected'][0]['index'] = False
    with pytest.raises(ValueError):
        collector.validate_selection(selection, context[0])


@pytest.fixture
def branch(synthetic, context, tmp_path):
    directory = tmp_path / 'branch'
    shutil.copytree(synthetic, directory)
    report = collector.read(directory / 'report.json')
    run = collector.RUNS[report['batch_index']]
    report.update(source_revision=run['head_sha'], run_id=str(run['id']),
                  run_attempt='1', plan_sha256=collector.PLAN_SHA)
    collector.write(directory / 'report.json', report)
    bid = report['record_id']
    row = next(row for part in context[0]['partitions'] for row in part['branches'] if row['record_id'] == bid)
    entry = {**row, 'status': 'time_limit', 'error': 'Synthetic wrapper interruption'}
    return directory, row, entry


def verify(branch, context):
    partition = next(p for p in context[0]['partitions'] if branch[1] in p['branches'])
    return collector.verify_branch(*branch, context, partition)


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


@pytest.mark.parametrize('change', ['source', 'attempt', 'plan', 'branch', 'request', 'resets', 'claimed_complete', 'batch', 'partition', 'other_run'])
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
    elif change == 'batch': report['batch_index'] = 1 - report['batch_index']
    elif change == 'partition': report['partition_index'] += 1
    elif change == 'other_run': report['run_id'] = str(collector.RUNS[1 - report['batch_index']]['id'])
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
    runs, jobs = api_fixture()
    selection = collector.bind_selection(plan, runs, jobs)
    row = selection['selected'][part['index']]
    run = runs[row['batch_index']]
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
        'batch_index': row['batch_index'], 'partition_index': row['index'], 'selected_branches': row['branches'], 'expected_branches': len(row['branches']),
        'metadata': collector.producer.metadata_for(plan), 'source_revision': run['head_sha'],
        'wrapper_sha256': collector.digest(collector.ROOT / 'scripts/run_rohwer_later_controls.py'),
        'run_id': str(run['id']), 'run_attempt': '1',
        'input_validation_sha256': collector.digest(root / 'input-validation.json'),
        'case_recovery_claimed': False, 'full_model_coverage_claimed': False, 'full_case_audit_required': True,
        'branches': prefix, 'status': 'incomplete', 'confirmed_branches': 0}
    collector.write(root / 'execution.json', execution)
    return root, row, execution, validation, selection, runs, jobs


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


@pytest.mark.parametrize('change', ['prefix', 'scope', 'source', 'validation', 'count', 'stop', 'batch', 'run'])
def test_partition_lineage_and_aggregate_cannot_change(branch, context, tmp_path, change):
    root, row, execution, validation, *_ = partition_fixture(branch, context, tmp_path)
    if change == 'prefix': execution['branches'][-1]['sample_count'] -= 1
    elif change == 'scope': execution['full_case_audit_required'] = False
    elif change == 'source': execution['source_revision'] = 'wrong'
    elif change == 'validation': execution['input_validation_sha256'] = 'wrong'
    elif change == 'count': execution['confirmed_branches'] = 100
    elif change == 'stop': execution['stop_reason'] = 'success'
    elif change == 'batch': execution['batch_index'] = 1 - row['batch_index']
    elif change == 'run': execution['run_id'] = str(collector.RUNS[1 - row['batch_index']]['id'])
    collector.write(root / 'execution.json', execution)
    with pytest.raises(ValueError):
        collector.verify_partition(root, row, context, execution['wrapper_sha256'], validation)


def test_collect_failed_job_and_detect_changed_cached_evidence(branch, context, tmp_path, monkeypatch):
    root, row, execution, validation, selection, runs, jobs = partition_fixture(branch, context, tmp_path)
    batch = row['batch_index']
    run = runs[batch]
    job = next(j for j in jobs[batch]['jobs'] if j['id'] == row['job_id'])
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
    snapshots_for(snapshots, runs, jobs, {batch: {'total_count': 1, 'artifacts': [artifact]}})
    selection_path = tmp_path / 'selection.json'
    collector.write(selection_path, selection)
    monkeypatch.setattr(collector.producer, 'load_plan', lambda *a: context)
    monkeypatch.setattr(collector.producer.inputs, 'validate', lambda *a: validation)
    output = tmp_path / 'collected'
    args = (tmp_path / 'plan', tmp_path / 'inputs', selection_path, snapshots, archives, output)
    result = collector.collect(*args)
    assert result['status'] == 'incomplete' and not result['collection_errors']
    assert result['verified_arrays'] == 4 and len(result['pending_indices']) == 511
    assert result['partitions'][0]['job_conclusion'] == 'timed_out'
    assert result['runs'] == collector.RUNS and result['plan_sha256'] == collector.PLAN_SHA
    assert result['collector_script_sha256'] == collector.digest(Path(collector.__file__))
    assert result['transport_script_sha256'] == collector.digest(collector.ROOT / 'scripts/collect_rohwer_breaking_diagnostics.py')
    preserved = Path(result['preserved_api_snapshots']['directory'])
    assert {p.relative_to(preserved).as_posix() for p in preserved.rglob('*.json')} == {'selection.json'} | {
        f'batch-{b}/{name}.json' for b in range(2) for name in ('run', 'jobs', 'artifacts')}
    original = (preserved / f'batch-{batch}' / 'jobs.json').read_bytes()
    collector.write(snapshots / f'batch-{batch}' / 'jobs.json', {**jobs[batch], 'extra_snapshot_information': True})
    assert (preserved / f'batch-{batch}' / 'jobs.json').read_bytes() == original
    evidence = Path(result['partitions'][0]['evidence'])
    (evidence / 'execution.json').write_text('{}')
    failed = collector.collect(*args)
    assert failed['status'] == 'verification_failed' and failed['collection_errors']
    assert not failed['complete_selected_diagnostics']


def test_all_pending_jobs_never_claim_completion(context, tmp_path, monkeypatch):
    runs, jobs = api_fixture()
    selection = collector.bind_selection(context[0], runs, jobs)
    collector.write(tmp_path / 'selection.json', selection)
    snapshots_for(tmp_path / 'api', runs, jobs)
    monkeypatch.setattr(collector.producer, 'load_plan', lambda *a: context)
    monkeypatch.setattr(collector.producer.inputs, 'validate', lambda *a: {})
    result = collector.collect(tmp_path / 'plan', tmp_path / 'inputs', tmp_path / 'selection.json', tmp_path / 'api', tmp_path / 'archives', tmp_path / 'output')
    assert len(result['pending_indices']) == 512 and result['verified_arrays'] == 0
    assert not result['complete_selected_diagnostics'] and not result['all_10924_controls_confirmed']


@pytest.mark.parametrize('batch', [0, 1])
@pytest.mark.parametrize('change', ['none', 'other_batch', 'other_name', 'expired', 'missing_digest',
                                   'wrong_attempt', 'outside_job_interval', 'live_job'])
def test_artifact_must_belong_to_exact_batch_and_attempt(context, batch, change):
    runs, jobs = api_fixture()
    selection = collector.bind_selection(context[0], runs, jobs)
    row = selection['selected'][batch*256]
    job = next(j for j in jobs[batch]['jobs'] if j['id'] == row['job_id'])
    job.update(status='completed', conclusion='failure', started_at='2026-11-18T23:00:00Z',
               completed_at='2026-11-19T05:00:00Z')
    artifact = {'id': 1, 'name': row['artifact_name'], 'expired': False,
                'workflow_run': {'id': runs[batch]['id'], 'head_sha': collector.SOURCE},
                'created_at': '2026-11-19T04:59:00Z', 'digest': 'sha256:'+'0'*64, 'size_in_bytes': 10}
    if change == 'other_batch': artifact['workflow_run']['id'] = runs[1-batch]['id']
    elif change == 'other_name': artifact['name'] = selection['selected'][(1-batch)*256]['artifact_name']
    elif change == 'expired': artifact['expired'] = True
    elif change == 'missing_digest': artifact.pop('digest')
    elif change == 'wrong_attempt': job['run_attempt'] = 2
    elif change == 'outside_job_interval': artifact['created_at'] = '2026-11-18T22:59:00Z'
    elif change == 'live_job': job['status'] = 'in_progress'
    if change == 'none': collector.validate_artifact(row, runs[batch], job, artifact)
    else:
        with pytest.raises(ValueError):
            collector.validate_artifact(row, runs[batch], job, artifact)


def test_complete_failed_integration_kept_as_terminal_failure(branch, context):
    directory, row, entry = branch
    report = collector.read(directory / 'report.json')
    record = collector.read(directory / (row['record_id'] + '.json'))
    record['integrations']['scipy_refined'].update(completed=False, error='Synthetic failed solve')
    orphan = record['traces'].pop('scipy_refined')['file']
    save(directory, report, record, context, recompute=True)
    result = verify(branch, context)
    assert result['complete_diagnostic'] and result['status'] == 'incomplete'
    assert result['verified_arrays'] == 3 and result['unverified_arrays'] == [orphan]
    assert result['producer_outcome']['status'] == 'time_limit'


@pytest.mark.parametrize('batch', [0, 1])
def test_empty_terminal_partition_preserves_its_exact_unattempted_inventory(context, tmp_path, batch):
    plan = context[0]
    selection = collector.bind_selection(plan, *api_fixture())
    row = selection['selected'][batch*256]
    run = collector.RUNS[batch]
    validation = {'synthetic_test_fixture': True}
    collector.write(tmp_path / 'input-validation.json', validation)
    runner_sha = collector.digest(collector.ROOT / 'scripts/run_rohwer_later_controls.py')
    execution = {'model_id': plan['model_id'], 'plan_sha256': collector.PLAN_SHA,
        'batch_index': batch, 'partition_index': row['index'],
        'selected_branches': row['branches'], 'expected_branches': len(row['branches']),
        'metadata': collector.producer.metadata_for(plan), 'source_revision': collector.SOURCE,
        'wrapper_sha256': runner_sha, 'run_id': str(run['id']), 'run_attempt': '1',
        'input_validation_sha256': collector.digest(tmp_path / 'input-validation.json'),
        'case_recovery_claimed': False, 'full_model_coverage_claimed': False, 'full_case_audit_required': True,
        'branches': [], 'status': 'incomplete', 'confirmed_branches': 0, 'stop_reason': 'disk_limit'}
    collector.write(tmp_path / 'execution.json', execution)
    result = collector.verify_partition(tmp_path, row, context, runner_sha, validation)
    assert not result['complete_selected_diagnostics'] and result['producer_stop_reason'] == 'disk_limit'
    assert [b['record_id'] for b in result['branches']] == [b['record_id'] for b in row['branches']]
    assert all(b['status'] == 'not_started' and b['verified_arrays'] == 0 for b in result['branches'])


@pytest.mark.parametrize('which', ['inputs', 'snapshots', 'archives'])
def test_collection_cannot_write_into_an_input_directory(tmp_path, which):
    inputs, snapshots, archives = (tmp_path / name for name in ('inputs', 'snapshots', 'archives'))
    output = {'inputs': inputs, 'snapshots': snapshots, 'archives': archives}[which]
    with pytest.raises(ValueError, match='separate'):
        collector.collect(tmp_path / 'plan', inputs, tmp_path / 'selection', snapshots, archives, output)


@pytest.mark.parametrize('which', ['plan', 'selection'])
def test_collection_cannot_overwrite_a_source_plan_or_selection(tmp_path, which):
    output = tmp_path / 'output'
    plan = output / 'plan.json' if which == 'plan' else tmp_path / 'plan.json'
    selection = output / 'status.json' if which == 'selection' else tmp_path / 'selection.json'
    with pytest.raises(ValueError, match='separate'):
        collector.collect(plan, tmp_path / 'inputs', selection, tmp_path / 'snapshots', tmp_path / 'archives', output)
