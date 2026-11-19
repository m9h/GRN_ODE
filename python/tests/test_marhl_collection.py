"""Synthetic full-grid transport fixtures; no biological conclusions."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import zipfile

import numpy as np
import pytest

from grn_memory import marhl_collection as collect, marhl_cloud as cloud, marhl_precision as work
from test_marhl_precision import fake  # Synthetic adapter fixture, explicitly no ODE integration.


@pytest.fixture
def api(tmp_path):
    plan, _ = collect.context()
    root = tmp_path/'api'
    batches = []
    for batch, indices in enumerate(plan['batches']):
        run_id = 1000+batch
        batches.append({'batch': batch, 'run_id': run_id, 'run_attempt': 1})
        directory = root/str(run_id)/'attempt-1'
        run = {'id': run_id, 'run_attempt': 1, 'head_sha': collect.PRODUCER,
               'path': cloud.WORKFLOW, 'event': 'workflow_dispatch', 'status': 'in_progress'}
        common = {'run_id': run_id, 'run_attempt': 1, 'head_sha': collect.PRODUCER,
                  'started_at': '2026-11-19T00:00:00Z', 'status': 'queued', 'conclusion': None}
        jobs = [{**common, 'id': 90000+batch, 'name': 'marhl-full-precision',
                 'status': 'completed', 'conclusion': 'success'}]
        jobs += [{**common, 'id': 100000+i, 'name': cloud.job_name(i)} for i in indices]
        work.write_json(directory/'run.json', run)
        work.write_json(directory/'jobs.json', {'total_count': len(jobs), 'jobs': jobs})
        work.write_json(directory/'artifacts.json', {'total_count': 0, 'artifacts': []})
    selection = collect.bind(batches, root)
    selected = tmp_path/'selection.json'
    work.write_json(selected, selection)
    return root, batches, selected


@pytest.fixture
def payloads(tmp_path, api, fake, monkeypatch):
    root, batches, selected = api
    monkeypatch.setattr(work, 'runtime', lambda backend: collect.expected_runtime(
        next(r for r in work.REQUESTS.values() if r['backend'] == backend)))
    paths = []
    for i in range(4):
        directory = tmp_path/f'payload-{i}'
        report = work.run_task(cloud.PLAN, cloud.INVENTORY, i, directory/'evidence')
        assert report['status'] == 'completed', report.get('error')
        row = work.read(selected)['selected'][i]
        execution = {'schema': 1, 'repository': collect.REPOSITORY, 'run_id': row['run_id'],
            'run_attempt': 1, 'job_id': row['job_id'], 'head_sha': collect.PRODUCER,
            'workflow_path': cloud.WORKFLOW, 'task_index': i, 'batch': 0, 'task_count': 1520,
            'plan_sha256': collect.PLAN_SHA, 'inventory_sha256': work.INVENTORY_SHA256,
            'evidence_directory': 'evidence', 'source_provenance': {'source_revision': collect.PRODUCER,
            'file_sha256': cloud.source_files(), 'implementation_files_differing_from_revision': []},
            'status': 'completed', 'finished_at': '2026-11-19T00:01:00Z', 'requested_parent_run': None}
        work.write_json(directory/'execution.json', execution)
        paths.append(directory)
    return paths


def publish(api, payloads, archives, indices=range(4)):
    root, _, selected = api
    snapshots = root/'1000/attempt-1'
    jobs = work.read(snapshots/'jobs.json')
    artifacts = []
    archives.mkdir(exist_ok=True)
    for i in indices:
        artifact_id = 200000+i
        archive = archives/f'artifact-{artifact_id}.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for p in payloads[i].rglob('*'):
                name = str(p.relative_to(payloads[i]))
                if p.is_file() and name in cloud.ALLOWED:
                    z.write(p, name)
        artifacts.append({'id': artifact_id, 'name': cloud.artifact_name(i, 1), 'expired': False,
            'workflow_run': {'id': 1000, 'head_sha': collect.PRODUCER},
            'created_at': '2026-11-19T00:02:00Z', 'size_in_bytes': archive.stat().st_size,
            'digest': 'sha256:'+work.digest(archive)})
        job = next(j for j in jobs['jobs'] if j['id'] == 100000+i)
        job.update(status='completed', conclusion='success')
    work.write_json(snapshots/'jobs.json', jobs)
    work.write_json(snapshots/'artifacts.json', {'total_count': len(artifacts), 'artifacts': artifacts})
    return archives


def test_all_1520_bound_without_relying_on_success(api):
    root, batches, selected = api
    selection = work.read(selected)
    assert len(selection['selected']) == 1520
    assert [sum(r['batch'] == b for r in selection['selected']) for b in range(6)] == [256]*5+[240]
    assert selection == collect.bind(batches, root)
    assert all(j['status'] == 'queued' for b in batches for j in
               work.read(root/str(b['run_id'])/'attempt-1/jobs.json')['jobs'][1:])


@pytest.mark.parametrize('change', ['missing_task', 'duplicate_task', 'wrong_batch', 'wrong_artifact',
                                  'wrong_source', 'wrong_plan', 'bad_type'])
def test_reject_incomplete_or_changed_fixed_selection(api, change):
    selection = work.read(api[2])
    if change == 'missing_task': selection['selected'].pop()
    if change == 'duplicate_task': selection['selected'][-1] = selection['selected'][0]
    if change == 'wrong_batch': selection['selected'][0]['batch'] = 1
    if change == 'wrong_artifact': selection['selected'][0]['artifact_name'] = 'passing-alternative'
    if change == 'wrong_source': selection['source_revision'] = '0'*40
    if change == 'wrong_plan': selection['plan_sha256'] = '0'*64
    if change == 'bad_type': selection['selected'][0]['index'] = False
    with pytest.raises(ValueError):
        collect.validate_selection(selection, work.read(cloud.PLAN))


@pytest.mark.parametrize('change', ['gate_failed', 'truncated', 'duplicate', 'wrong_attempt', 'wrong_source', 'wrong_workflow'])
def test_api_binding_rejects_wrong_or_incomplete_inventory(api, change):
    root, batches, _ = api
    path = root/'1000/attempt-1'
    jobs, run = work.read(path/'jobs.json'), work.read(path/'run.json')
    if change == 'gate_failed': jobs['jobs'][0]['conclusion'] = 'failure'
    if change == 'truncated': jobs['jobs'].pop()
    if change == 'duplicate': jobs['jobs'][-1] = jobs['jobs'][1]
    if change == 'wrong_attempt': jobs['jobs'][1]['run_attempt'] = 2
    if change == 'wrong_source': run['head_sha'] = 'a'*40
    if change == 'wrong_workflow': run['path'] = 'other.yml'
    work.write_json(path/'run.json', run); work.write_json(path/'jobs.json', jobs)
    with pytest.raises(ValueError):
        collect.bind(batches, root)


def test_pending_selection_cannot_be_claimed_complete(api, tmp_path):
    result = collect.collect(api[2], api[0], tmp_path/'archives', tmp_path/'collected')
    assert len(result['tasks']) == 1520 and len(result['branches']) == 380
    assert result['complete_arrays'] == result['complete_branches'] == 0
    assert result['all_required_arrays_verified'] is False and not result['verification_errors']
    assert not result['all_required_branches_agree'] and not result['case_recovery_claimed']
    assert len(result['original_api_snapshot_sha256']) == 6
    with pytest.raises(ValueError, match='new collection'):
        collect.collect(api[2], api[0], tmp_path/'archives', tmp_path/'collected')


def test_collects_original_zips_and_checks_complete_grid(api, payloads, tmp_path):
    archives = publish(api, payloads, tmp_path/'archives')
    before = {p.name: work.digest(p) for p in archives.iterdir()}
    result = collect.collect(api[2], api[0], archives, tmp_path/'collected')
    assert not result['verification_errors'], result['verification_errors']
    assert result['complete_arrays'] == 4 and result['complete_branches'] == 1
    assert result['branches'][0]['status'] == 'agreement'
    branch = work.read(tmp_path/'collected'/result['branches'][0]['file'])
    assert branch['samples'] == 221001 and len(branch['comparisons']) == 6
    assert all(c['passed'] for c in branch['comparisons'].values())
    assert not result['all_required_arrays_verified'] and not result['case_recovery_claimed']
    for task in result['tasks'][:4]:
        saved = tmp_path/'collected/artifacts'/str(task['artifact_id'])/'download.zip'
        assert work.digest(saved) == before[f'artifact-{task["artifact_id"]}.zip']
        assert task['checkpoint']['exact_restart_state_validated'] is False
    assert before == {p.name: work.digest(p) for p in archives.iterdir()}


@pytest.mark.parametrize('change', ['job', 'runtime', 'source', 'grid', 'report_status', 'last_sample', 'checkpoint', 'state'])
def test_rejects_forged_or_damaged_task(payloads, api, change):
    directory = payloads[0]
    report_path = directory/'evidence/report.json'
    report = work.read(report_path)
    if change == 'job':
        x = work.read(directory/'execution.json'); x['job_id'] += 1; work.write_json(directory/'execution.json', x)
    elif change in ('runtime', 'source', 'grid'):
        if change == 'runtime': report['identity']['runtime']['packages']['heyoka'] = '7.0'
        if change == 'source': report['identity']['sources']['grn_memory/taylor_reference.py'] = '0'*64
        if change == 'grid': report['identity']['sample_count'] -= 1
        report['fingerprint'] = work.fingerprint(report['identity'])
    elif change == 'report_status': report['status'] = 'successful'
    elif change == 'last_sample':
        path = directory/'evidence/trajectory.npz'
        with np.load(path, allow_pickle=False) as z: data = {k: z[k].copy() for k in z.files}
        data['values'][-1, 0] += 1
        np.savez_compressed(path, **data)
        report['trace']['sha256'] = work.digest(path)
    elif change == 'checkpoint': (directory/'evidence/checkpoint.npz').write_bytes(b'bad checkpoint')
    elif change == 'state':
        path = directory/'evidence/checkpoint.npz'
        with np.load(path, allow_pickle=False) as z: data = {k: z[k].copy() for k in z.files}
        meta = json.loads(str(data['metadata'])); meta['state'][0] = 'NaN'
        meta.pop('payload_sha256'); meta['payload_sha256'] = work.fingerprint(meta)
        np.savez_compressed(path, metadata=np.asarray(json.dumps(meta)), observations=data['observations'])
        report['checkpoint_sha256'] = work.digest(path)
    work.write_json(report_path, report)
    plan, inventory = collect.context()
    with pytest.raises((ValueError, zipfile.BadZipFile)):
        collect.verify_task(directory, work.read(api[2])['selected'][0], plan, inventory)


def test_integration_failure_and_orphan_array_are_not_completed(payloads, api):
    directory = payloads[0]
    report = work.read(directory/'evidence/report.json')
    report.update(status='integration_failed', error='retained synthetic solver error')
    work.write_json(directory/'evidence/report.json', report)
    execution = work.read(directory/'execution.json'); execution['status'] = 'integration_failed'
    work.write_json(directory/'execution.json', execution)
    result = collect.verify_task(directory, work.read(api[2])['selected'][0], *collect.context())
    assert result['status'] == 'integration_failed' and not result['complete_array_verified']
    assert result['unclaimed_orphan_trajectory'] and result['error']


@pytest.mark.parametrize('change', ['digest', 'size', 'name', 'time', 'run', 'source', 'expired'])
def test_artifact_identity_and_server_checks(api, payloads, tmp_path, change):
    publish(api, payloads, tmp_path/'archives', [0])
    run, jobs, artifacts, _ = collect.snapshot(api[0], 1000, 1)
    artifact = artifacts[0]
    if change == 'digest': artifact['digest'] = 'missing'
    if change == 'size': artifact['size_in_bytes'] = cloud.MAX_ARCHIVE_BYTES+1
    if change == 'name': artifact['name'] = cloud.artifact_name(0, 2)
    if change == 'time': artifact['created_at'] = '2026-11-18T00:00:00Z'
    if change == 'run': artifact['workflow_run']['id'] = 42
    if change == 'source': artifact['workflow_run']['head_sha'] = '0'*40
    if change == 'expired': artifact['expired'] = True
    with pytest.raises(ValueError):
        collect.validate_artifact(artifact, run, jobs[1], work.read(api[2])['selected'][0])


def test_bad_zip_is_retained_as_verification_error(api, payloads, tmp_path):
    archives = publish(api, payloads, tmp_path/'archives', [0])
    path = archives/'artifact-200000.zip'
    with path.open('ab') as f: f.write(b'changed')
    result = collect.collect(api[2], api[0], archives, tmp_path/'collected')
    assert result['tasks'][0]['status'] == 'verification_error'
    assert result['verification_errors'][0]['index'] == 0
    assert not result['all_required_arrays_verified']


def test_cannot_rebind_live_parent(api):
    root, _, selected = api
    old = root/'1000/attempt-1'
    new = root/'2000/attempt-1'
    shutil.copytree(old, new)
    run = work.read(new/'run.json'); run['id'] = 2000; work.write_json(new/'run.json', run)
    jobs = work.read(new/'jobs.json'); jobs['jobs'] = jobs['jobs'][:2]; jobs['total_count'] = 2
    for j in jobs['jobs']: j['run_id'] = 2000; j['id'] += 1000000
    work.write_json(new/'jobs.json', jobs)
    with pytest.raises(ValueError, match='live numerical'):
        collect.rebind(work.read(selected), 2000, 1, [0], root)
    old_jobs = work.read(old/'jobs.json'); old_jobs['jobs'][1].update(status='completed', conclusion='failure')
    work.write_json(old/'jobs.json', old_jobs)
    result = collect.rebind(work.read(selected), 2000, 1, [0], root)
    assert len(result['selected']) == 1520
    assert result['selected'][0]['previous'] == work.read(selected)['selected'][0]
    assert result['selected'][1:] == work.read(selected)['selected'][1:]


@pytest.fixture
def continuation(api, payloads, tmp_path):
    archives = publish(api, payloads, tmp_path/'archives')
    root = api[0]
    source = root/'1000/attempt-1'
    destination = root/'2000/attempt-1'
    shutil.copytree(source, destination)
    run = work.read(destination/'run.json'); run['id'] = 2000
    work.write_json(destination/'run.json', run)
    jobs = work.read(destination/'jobs.json'); jobs['jobs'] = jobs['jobs'][:2]; jobs['total_count'] = 2
    for j in jobs['jobs']: j['run_id'] = 2000; j['id'] += 1000000
    work.write_json(destination/'jobs.json', jobs)
    selection = collect.rebind(work.read(api[2]), 2000, 1, [0], root)
    work.write_json(api[2], selection)
    child = tmp_path/'continued'
    shutil.copytree(payloads[0], child)
    parent_archive = work.read(source/'artifacts.json')['artifacts'][0]
    members = {str(p.relative_to(payloads[0])): work.digest(p) for p in payloads[0].rglob('*')
               if p.is_file() and str(p.relative_to(payloads[0])) in cloud.ALLOWED}
    history = {'parent_run_id': 1000, 'parent_run_attempt': 1, 'parent_job_id': 100000,
        'artifact_id': 200000, 'archive_sha256': parent_archive['digest'],
        'archive_bytes': parent_archive['size_in_bytes'], 'archived_file_sha256': members,
        'parent_revision': collect.PRODUCER, 'task_index': 0}
    work.write_json(child/'evidence/restore-provenance.json', {'history': [history]})
    execution = work.read(child/'execution.json')
    execution.update(run_id=2000, job_id=1100000, requested_parent_run=1000)
    work.write_json(child/'execution.json', execution)
    def repack():
        path = archives/'artifact-300000.zip'
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for p in child.rglob('*'):
                name = str(p.relative_to(child))
                if p.is_file() and name in cloud.ALLOWED: z.write(p, name)
        artifact = {**parent_archive, 'id': 300000, 'workflow_run': {'id': 2000, 'head_sha': collect.PRODUCER},
                    'size_in_bytes': path.stat().st_size, 'digest': 'sha256:'+work.digest(path)}
        work.write_json(destination/'artifacts.json', {'total_count': 1, 'artifacts': [artifact]})
    repack()
    return archives, child, repack


def test_continuation_rechecks_parent_zip_history_and_preserved_arrays(api, continuation, tmp_path):
    archives, _, _ = continuation
    result = collect.collect(api[2], api[0], archives, tmp_path/'collected')
    assert not result['verification_errors'], result['verification_errors']
    assert result['complete_arrays'] == 4 and result['complete_branches'] == 1
    assert result['tasks'][0]['parent_archive_verified'] == 'sha256:'+work.digest(archives/'artifact-200000.zip')
    assert len(list((tmp_path/'collected/artifacts').iterdir())) == 5


@pytest.mark.parametrize('change', ['history', 'prefix', 'parent_zip', 'wrong_parent'])
def test_continuation_rejects_changed_history_prefix_or_original_archive(api, continuation, tmp_path, change):
    archives, child, repack = continuation
    if change == 'history':
        history = work.read(child/'evidence/restore-provenance.json')
        history['history'][0]['parent_job_id'] += 1
        work.write_json(child/'evidence/restore-provenance.json', history)
    elif change == 'wrong_parent':
        execution = work.read(child/'execution.json'); execution['requested_parent_run'] = 42
        work.write_json(child/'execution.json', execution)
    elif change == 'prefix':
        checkpoint = child/'evidence/checkpoint.npz'
        with np.load(checkpoint, allow_pickle=False) as z:
            meta, values = json.loads(str(z['metadata'])), z['observations'].copy()
        values[0,0] += 1
        import hashlib
        meta['observations_sha256'] = hashlib.sha256(values.tobytes()).hexdigest()
        meta.pop('payload_sha256'); meta['payload_sha256'] = work.fingerprint(meta)
        np.savez_compressed(checkpoint, metadata=np.asarray(json.dumps(meta)), observations=values)
        trace = child/'evidence/trajectory.npz'
        with np.load(trace, allow_pickle=False) as z: data = {k: z[k].copy() for k in z.files}
        data['values'] = values; np.savez_compressed(trace, **data)
        report = work.read(child/'evidence/report.json'); report['trace']['sha256'] = work.digest(trace)
        report['checkpoint_sha256'] = work.digest(checkpoint)
        work.write_json(child/'evidence/report.json', report)
    elif change == 'parent_zip':
        with (archives/'artifact-200000.zip').open('ab') as f: f.write(b'changed parent')
    repack()
    result = collect.collect(api[2], api[0], archives, tmp_path/'collected')
    assert result['tasks'][0]['status'] == 'verification_error'
    assert result['verification_errors'][0]['index'] == 0
    assert result['complete_arrays'] == 3 and result['complete_branches'] == 0
