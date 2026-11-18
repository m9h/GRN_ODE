"""Synthetic trajectories and API fixtures; no scientific outcome is simulated."""

from copy import deepcopy
import hashlib
from pathlib import Path
import shutil
import stat
from types import SimpleNamespace
import zipfile

import numpy as np
import pytest

from scripts import collect_rohwer_breaking_diagnostics as c

INPUTS = c.ROOT/'results/catalog-breaking-rohwer-diagnostics-20261118'


def api_fixture():
    plan = c.read(INPUTS/'plan.json')
    run = {**c.RUN, 'event': 'workflow_dispatch'}
    common = {'run_id': c.RUN['id'], 'run_attempt': 1, 'head_sha': c.RUN['head_sha']}
    jobs = [{'id': c.VALIDATION_JOB, 'name': 'validation', 'status': 'completed', 'conclusion': 'success', **common}]
    jobs += [{'id': 100+i, 'name': f'rohwer-failed-branches-{i}', 'status': 'queued', 'conclusion': None, **common}
             for i in range(32)]
    return plan, run, {'total_count': 33, 'jobs': jobs}


def test_binding_selects_all_750_once():
    plan, run, jobs = api_fixture()
    selection = c.bind_selection(plan, run, jobs)
    branches = [b for row in selection['selected'] for b in row['branches']]
    assert len(branches) == len({b['record_id'] for b in branches}) == 750
    assert not selection['case_recovery_claimed']


@pytest.mark.parametrize('mutation', ['queued_gate', 'gate_source', 'gate_id', 'missing_job',
                                     'duplicate_name', 'duplicate_id', 'pages', 'run_attempt', 'run_source'])
def test_reject_wrong_or_incomplete_job_identity(mutation):
    plan, run, jobs = api_fixture()
    if mutation == 'queued_gate': jobs['jobs'][0].update(status='queued', conclusion=None)
    elif mutation == 'gate_source': jobs['jobs'][0]['head_sha'] = 'b'*40
    elif mutation == 'gate_id': jobs['jobs'][0]['id'] += 1
    elif mutation == 'missing_job': jobs['jobs'].pop(); jobs['total_count'] -= 1
    elif mutation == 'duplicate_name': jobs['jobs'][-1]['name'] = jobs['jobs'][-2]['name']
    elif mutation == 'duplicate_id': jobs['jobs'][-1]['id'] = jobs['jobs'][-2]['id']
    elif mutation == 'pages': jobs['total_count'] += 1
    elif mutation == 'run_attempt': run['run_attempt'] = 2
    else: run['head_sha'] = 'b'*40
    with pytest.raises(ValueError): c.bind_selection(plan, run, jobs)


@pytest.mark.parametrize('mutation', ['branch', 'source_partition', 'job', 'artifact', 'plan'])
def test_fixed_selection_rejects_changed_scope(mutation):
    plan, run, jobs = api_fixture()
    selection = deepcopy(c.bind_selection(plan, run, jobs))
    row = selection['selected'][0]
    if mutation == 'branch': row['branches'].pop()
    elif mutation == 'source_partition': row['branches'][0]['source_partition'] = 99
    elif mutation == 'job': row['job_id'] = selection['selected'][1]['job_id']
    elif mutation == 'artifact': row['artifact_name'] = 'favorable-old-artifact'
    else: selection['plan_sha256'] = '0'*64
    with pytest.raises(ValueError): c.validate_selection(selection, plan)


def artifact_fixture(row, run, job):
    job.update(status='completed', conclusion='failure', started_at='2026-11-18T21:30:00Z',
               completed_at='2026-11-18T21:40:00Z')
    return {'id': 42, 'name': row['artifact_name'], 'expired': False,
            'workflow_run': {'id': run['id'], 'head_sha': run['head_sha']},
            'created_at': '2026-11-18T21:39:00Z', 'digest': 'sha256:'+'0'*64, 'size_in_bytes': 1}


def test_failed_job_artifact_is_allowed_but_other_attempt_is_rejected():
    plan, run, jobs = api_fixture()
    row = c.bind_selection(plan, run, jobs)['selected'][0]
    job = jobs['jobs'][1]
    artifact = artifact_fixture(row, run, job)
    c.validate_artifact(row, run, job, artifact)
    for change in ('before', 'after', 'source', 'expired', 'digest'):
        bad = deepcopy(artifact)
        if change == 'before': bad['created_at'] = '2026-11-18T21:29:59Z'
        elif change == 'after': bad['created_at'] = '2026-11-18T21:40:01Z'
        elif change == 'source': bad['workflow_run']['head_sha'] = 'b'*40
        elif change == 'expired': bad['expired'] = True
        else: bad['digest'] = ''
        with pytest.raises(ValueError): c.validate_artifact(row, run, job, bad)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a/../b', 'a//b', 'a\\b'])
def test_zip_rejects_unsafe_paths(tmp_path, name):
    archive = tmp_path/'archive.zip'
    with zipfile.ZipFile(archive, 'w') as stream: stream.writestr(name, '{}')
    with pytest.raises(ValueError, match='Unsafe'):
        c.verify_zip(archive, tmp_path/'out', extract=True)


def test_zip_rejects_symlink(tmp_path):
    archive = tmp_path/'archive.zip'
    entry = zipfile.ZipInfo('a')
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, 'w') as stream: stream.writestr(entry, '/outside')
    with pytest.raises(ValueError, match='Unsafe'):
        c.verify_zip(archive, tmp_path/'out', extract=True)


def test_cached_nested_extraction_is_rechecked(tmp_path):
    archive, output = tmp_path/'archive.zip', tmp_path/'out'
    with zipfile.ZipFile(archive, 'w') as stream: stream.writestr('branch/report.json', '{}')
    c.verify_zip(archive, output, extract=True)
    assert len(c.verify_zip(archive, output)) == 1
    (output/'branch/report.json').write_text('{"changed":true}')
    with pytest.raises(ValueError, match='inventory|bytes'):
        c.verify_zip(archive, output)


@pytest.fixture(scope='module')
def synthetic(tmp_path_factory):
    root = tmp_path_factory.mktemp('synthetic-rohwer')
    plan = c.read(INPUTS/'plan.json')
    plan['runtime']['versions'] = {k: 'synthetic-test-fixture' for k in c.auditor.PACKAGES}
    row = plan['partitions'][0]['branches'][0]
    bid = row['record_id']
    directory = root/bid
    directory.mkdir()
    entry = plan['source_partitions'][row['source_partition']]
    source = INPUTS/entry['file']
    shutil.copyfile(source, directory/'source-evidence.json')
    evidence, _, info, grid, originals = c.prepare(source, [bid])
    spec = originals[bid]['specification']
    times = grid[grid <= spec['stop']]
    settings = c.requests(SimpleNamespace(**c.producer.REQUESTS))
    sources = c.source_hashes()
    sources.update({name: c.digest(c.ROOT/name) for name in c.auditor.SOURCES})
    report = {'model_id': c.producer.MODEL, 'model_sha256': info['sha256'],
              'source_evidence_sha256': entry['sha256'], 'source_report_sha256': entry['original_report_sha256'],
              'source_fingerprint': evidence['original_report']['fingerprint'], 'requests': settings,
              'acceptance': plan['acceptance'], 'implementation_sha256': sources,
              'versions': plan['runtime']['versions'], 'sample_grid_sha256': hashlib.sha256(grid.tobytes()).hexdigest(),
              'selected_branch_ids': [bid], 'case_recovery_claimed': False, 'expected_branches': 1,
              'status': 'completed', 'confirmed_branches': 1}
    report['fingerprint'] = c.fingerprint({k: report[k] for k in c.auditor.META_KEYS})
    record = {'fingerprint': report['fingerprint'], 'record_id': bid, 'specification': spec,
              'integrations': {}, 'traces': {}, 'status': 'confirmed', 'case_recovery_claimed': False}
    trains = [c.ResetTrain(**t) for t in spec['reset_trains']]
    resets = sorted({float(v) for t in trains for v in t.times()})
    counts = [len(t.indices()) for t in trains]
    for label, request in settings.items():
        path = directory/(bid+'-'+label+'.npz')
        np.savez_compressed(path, times=times, observables=np.array(info['observables']),
                            values=np.ones((len(times), len(info['observables']))))
        record['traces'][label] = {'file': path.name, 'sha256': c.digest(path)}
        outcome = {'request': request, 'completed': True, 'sample_count': len(times), 'observables': info['observables']}
        if label.startswith('scipy'):
            outcome.update(backend='scipy.solve_ivp', rhs_backend='Jaxkineticmodel', jacobian='jax.jacfwd',
                model_sha256=info['sha256'], method='Radau', rtol=request['rtol'], atol=request['atol'], x64=True,
                absolute_time_preserved=True, expected_resets=len(resets), performed_resets=len(resets),
                expected_train_reset_counts=counts, train_reset_counts=counts, expected_segments=len(resets)+1,
                completed_segments=len(resets)+1, last_interval=[resets[-1] if resets else 0., float(times[-1])])
        record['integrations'][label] = outcome
    record['comparisons'] = comparisons(directory, record)
    c.write(directory/(bid+'.json'), record)
    report['branches'] = [{'record_id': bid, 'file': bid+'.json', 'sha256': c.digest(directory/(bid+'.json')), 'status': 'confirmed'}]
    c.write(directory/'report.json', report)
    c.write(directory/'audit.json', c.auditor.audit(directory))
    outcome = {**row, 'status': 'confirmed', 'report_sha256': c.digest(directory/'report.json'),
               'audit_sha256': c.digest(directory/'audit.json')}
    return directory, row, outcome, plan


def comparisons(directory, record):
    sample = next(iter(record['traces'].values()))
    with np.load(directory/sample['file'], allow_pickle=False) as data:
        times, names = data['times'].copy(), list(data['observables'])
    traces = {label: c.auditor.trajectory(directory, record['record_id'], label, saved, times, names)
              for label, saved in record['traces'].items()}
    return {a+'_vs_'+b: c.comparison(traces[a], traces[b], rtol=2e-5, atol=1e-7)
            for i, a in enumerate(c.auditor.LABELS) for b in c.auditor.LABELS[i+1:] if a in traces and b in traces}


@pytest.fixture
def branch(synthetic, tmp_path):
    original, row, entry, plan = synthetic
    directory = tmp_path/row['record_id']
    shutil.copytree(original, directory)
    return directory, deepcopy(row), deepcopy(entry), INPUTS, deepcopy(plan)


def refresh(args, record, *, recompute=False):
    directory, row, entry, _, _ = args
    bid = row['record_id']
    report = c.read(directory/'report.json')
    if recompute: record['comparisons'] = comparisons(directory, record)
    c.write(directory/(bid+'.json'), record)
    report['branches'][0].update(sha256=c.digest(directory/(bid+'.json')), status=record['status'])
    report['confirmed_branches'] = int(record['status'] == 'confirmed')
    c.write(directory/'report.json', report)
    entry['report_sha256'] = c.digest(directory/'report.json')
    if recompute:
        c.write(directory/'audit.json', c.auditor.audit(directory))
        entry.update(audit_sha256=c.digest(directory/'audit.json'),
                     status='confirmed' if record['status'] == 'confirmed' else 'numerical_failure')


def test_full_original_grid_is_audited_without_a_lock_file(branch):
    result = c.verify_branch(*branch)
    assert result['complete_diagnostic'] and result['verified_arrays'] == 4 and result['status'] == 'confirmed'
    assert result['independent_audit']['branches'][0]['samples'] == branch[1]['sample_count']
    assert len(result['independent_audit']['branches'][0]['comparisons']) == 6
    assert not result['independent_audit']['case_recovery_claimed']


def test_last_observation_change_detected_and_honest_mismatch_retained(branch):
    directory, row, *_ = branch
    record = c.read(directory/(row['record_id']+'.json'))
    saved = record['traces']['scipy_refined']
    path = directory/saved['file']
    with np.load(path, allow_pickle=False) as arrays: data = {k: arrays[k].copy() for k in arrays.files}
    data['values'][-1, 0] += 1
    np.savez_compressed(path, **data)
    saved['sha256'] = c.digest(path)
    refresh(branch, record)
    with pytest.raises(ValueError, match='comparisons'): c.verify_branch(*branch)
    record['status'] = 'mismatch'
    refresh(branch, record, recompute=True)
    result = c.verify_branch(*branch)
    assert result['complete_diagnostic'] and result['status'] == 'mismatch'


def test_explicit_failed_integration_is_retained(branch):
    directory, row, *_ = branch
    record = c.read(directory/(row['record_id']+'.json'))
    saved = record['traces'].pop('scipy_refined')
    (directory/saved['file']).unlink()
    record['integrations']['scipy_refined'].update(completed=False, error='Synthetic solver failure')
    record['status'] = 'incomplete'
    refresh(branch, record, recompute=True)
    result = c.verify_branch(*branch)
    assert result['complete_diagnostic'] and result['status'] == 'incomplete' and result['verified_arrays'] == 3


def interrupt(branch, orphan=False):
    directory, row, entry, *_ = branch
    report = c.read(directory/'report.json')
    report.update(status='running', branches=[])
    c.write(directory/'report.json', report)
    (directory/'audit.json').unlink()
    entry.update(status='time_limit', error='Synthetic timeout')
    record = c.read(directory/(row['record_id']+'.json'))
    record.update(status='running', comparisons={})
    if orphan:
        record['traces'].pop('scipy_refined')
        record['integrations']['scipy_refined'] = {'completed': False, 'request': report['requests']['scipy_refined']}
    c.write(directory/(row['record_id']+'.json'), record)


def test_partial_arrays_do_not_complete_diagnostic(branch):
    interrupt(branch)
    result = c.verify_branch(*branch)
    assert not result['complete_diagnostic'] and result['verified_arrays'] == 4


def test_orphaned_partial_array_is_preserved_without_validation_claim(branch):
    interrupt(branch, orphan=True)
    result = c.verify_branch(*branch)
    assert result['verified_arrays'] == 3 and not result['complete_diagnostic']
    assert result['unverified_arrays'] == [branch[1]['record_id']+'-scipy_refined.npz']


@pytest.mark.parametrize('change', ['truncated', 'missing_reset'])
def test_partial_arrays_require_full_grid_and_reset_evidence(branch, change):
    interrupt(branch)
    directory, row, *_ = branch
    path = directory/(row['record_id']+'.json')
    record = c.read(path)
    if change == 'missing_reset':
        record['integrations']['scipy_refined']['performed_resets'] -= 1
    else:
        saved = record['traces']['scipy_refined']
        array_path = directory/saved['file']
        with np.load(array_path, allow_pickle=False) as arrays:
            data = {k: arrays[k].copy() for k in arrays.files}
        data['times'] = data['times'][:-1]
        data['values'] = data['values'][:-1]
        np.savez_compressed(array_path, **data)
        saved['sha256'] = c.digest(array_path)
    c.write(path, record)
    with pytest.raises(ValueError):
        c.verify_branch(*branch)


def test_finished_report_survives_wrapper_interruption_without_changing_recorded_failure(branch):
    branch[2].update(status='time_limit', error='Synthetic interruption after report completion')
    result = c.verify_branch(*branch)
    assert result['complete_diagnostic'] and result['verified_arrays'] == 4
    assert result['producer_outcome']['status'] == 'time_limit'


def partition_fixture(branch):
    directory, _, entry, inputs, plan = branch
    _, run, jobs = api_fixture()
    row = c.bind_selection(plan, run, jobs)['selected'][0]
    execution = {'model_id': c.producer.MODEL, 'plan_sha256': c.PLAN_SHA, 'partition_index': 0,
                 'selected_branches': row['branches'], 'expected_branches': len(row['branches']),
                 'producer_revision': c.RUN['head_sha'], 'runner_sha256': c.digest(Path(c.producer.__file__)),
                 'run_id': str(c.RUN['id']), 'run_attempt': '1', 'runtime': plan['runtime'],
                 'case_recovery_claimed': False, 'status': 'incomplete', 'branches': [entry], 'confirmed_branches': 1}
    c.write(directory.parent/'execution.json', execution)
    return directory.parent, row, inputs, plan, execution['runner_sha256']


def test_partition_keeps_all_pending_branches_and_rejects_changed_lineage(branch):
    args = partition_fixture(branch)
    result = c.verify_partition(*args)
    assert len(result['branches']) == len(args[1]['branches']) and not result['complete_selected_diagnostics']
    assert sum(b['complete_diagnostic'] for b in result['branches']) == 1
    path = args[0]/'execution.json'
    execution = c.read(path)
    execution['selected_branches'].pop()
    c.write(path, execution)
    with pytest.raises(ValueError, match='lineage'): c.verify_partition(*args)


def test_collect_partial_failed_job_and_detect_changed_cached_evidence(branch, tmp_path, monkeypatch):
    directory, row, inputs, plan, _ = partition_fixture(branch)
    _, run, jobs = api_fixture()
    selection = c.bind_selection(plan, run, jobs)
    artifact = artifact_fixture(row, run, jobs['jobs'][1])
    archives = tmp_path/'archives'
    archives.mkdir()
    archive = archives/'artifact-42.zip'
    paths = [directory/'execution.json', *sorted((directory/row['branches'][0]['record_id']).iterdir())]
    with zipfile.ZipFile(archive, 'w') as stream:
        for path in paths: stream.write(path, path.relative_to(directory).as_posix())
    artifact.update(digest='sha256:'+c.digest(archive), size_in_bytes=archive.stat().st_size)
    snapshots = tmp_path/'api'
    snapshots.mkdir()
    for name, value in [('run', run), ('jobs', jobs), ('artifacts', {'total_count': 1, 'artifacts': [artifact]})]:
        c.write(snapshots/(name+'.json'), value)
    selection_path = tmp_path/'selection.json'
    c.write(selection_path, selection)
    monkeypatch.setattr(c.producer, 'check', lambda *a: plan)
    output = tmp_path/'collected'
    result = c.collect(inputs, selection_path, snapshots, archives, output)
    assert not result['collection_errors'] and result['pending_indices'] == list(range(1, 32))
    assert result['confirmed_branches'] == 1 and result['verified_arrays'] == 4
    assert not result['complete_selected_diagnostics'] and not result['case_recovery_claimed']
    assert result['partitions'][0]['job_conclusion'] == 'failure'
    cached = Path(result['partitions'][0]['evidence'])/'execution.json'
    cached.write_text('{}')
    changed = c.collect(inputs, selection_path, snapshots, archives, output)
    assert changed['collection_errors'] and changed['confirmed_branches'] == 0


def test_pending_jobs_never_claim_completion(tmp_path, monkeypatch):
    plan, run, jobs = api_fixture()
    selection = c.bind_selection(plan, run, jobs)
    selection_path = tmp_path/'selection.json'
    c.write(selection_path, selection)
    api = tmp_path/'api'
    api.mkdir()
    for name, value in [('run', run), ('jobs', jobs), ('artifacts', {'total_count': 0, 'artifacts': []})]:
        c.write(api/(name+'.json'), value)
    monkeypatch.setattr(c.producer, 'check', lambda *a: plan)
    result = c.collect(INPUTS, selection_path, api, tmp_path/'archives', tmp_path/'out')
    assert result['pending_indices'] == list(range(32)) and not result['collection_errors']
    assert result['confirmed_branches'] == result['verified_arrays'] == 0
    assert not result['complete_selected_diagnostics'] and not result['all_750_branches_confirmed']
