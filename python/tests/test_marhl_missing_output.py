"""Full-selection recovery with synthetic full-grid arrays; no production ODE runs."""
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import zipfile

import pytest

from grn_memory import marhl_missing_output as r, marhl_collection as c, marhl_precision as work
from test_marhl_collection import api
from test_marhl_precision import fake

REVISION = 'b'*40
INDICES = [33, 34, 36, 287, 536, 537, 789, 1042, 1043, 1045, 1046, 1047, 1297, 1298, 1299, 1302]


def test_pinned_all_sixteen_parents_and_frozen_full_scope():
    ctx = r.context()
    assert sorted(ctx['rows']) == INDICES and ctx['plan']['task_count'] == 1520
    assert len(ctx['plan']['branches']) == 380 and len(ctx['inventory']['cases']) == 12
    assert r.select_tasks() == INDICES


@pytest.mark.parametrize('name', ['binding.json', 'selection.json', 'missing-output-plan.json'])
def test_modified_recovery_inputs_rejected(tmp_path, monkeypatch, name):
    shutil.copytree(r.BINDINGS, tmp_path/'inputs')
    monkeypatch.setattr(r, 'BINDINGS', tmp_path/'inputs')
    with (r.BINDINGS/name).open('a') as stream:
        stream.write(' ')
    with pytest.raises(ValueError, match='Pinned'):
        r.context()


def add_run(root, run_id, indices, status='queued'):
    directory = root/str(run_id)/'attempt-1'
    run = {'id': run_id, 'run_attempt': 1, 'head_sha': REVISION, 'path': r.WORKFLOW,
           'event': 'workflow_dispatch', 'status': 'in_progress'}
    common = {'run_id': run_id, 'run_attempt': 1, 'head_sha': REVISION,
              'started_at': '2026-11-24T06:00:00Z', 'completed_at': None}
    jobs = [{**common, 'id': run_id*10000, 'name': 'marhl-full-precision',
             'status': 'completed', 'conclusion': 'success'}]
    jobs += [{**common, 'id': run_id*10000+i+1, 'name': r.cloud.job_name(i),
              'status': status, 'conclusion': None} for i in indices]
    for name, data in [('run', run), ('jobs', {'total_count': len(jobs), 'jobs': jobs}),
                       ('artifacts', {'total_count': 0, 'artifacts': []})]:
        work.write_json(directory/(name+'.json'), data)


@pytest.fixture
def recovery_api(api, monkeypatch):
    root, batches, path = api
    selection = work.read(path)
    plan, inventory = c.context()
    ctx = {'plan': plan, 'inventory': inventory, 'rows': {i: selection['selected'][i] for i in INDICES}}
    for batch in batches:
        jobs_path = root/str(batch['run_id'])/'attempt-1/jobs.json'
        jobs = work.read(jobs_path)
        for job in jobs['jobs']:
            if any(job['id'] == ctx['rows'][i]['job_id'] for i in INDICES):
                job.update(status='completed', conclusion='cancelled', runner_id=0, steps=[],
                           completed_at='2026-11-19T00:01:00Z')
        work.write_json(jobs_path, jobs)
    monkeypatch.setattr(r, 'context', lambda: ctx)
    monkeypatch.setattr(r, 'source_at_revision', lambda revision: r.source_files() if revision == REVISION else {})
    monkeypatch.setattr(r, 'verify_current_source', lambda revision: work.require(revision == REVISION, 'Source differs'))
    monkeypatch.setattr(work, 'runtime', lambda backend: c.expected_runtime(
        next(request for request in work.REQUESTS.values() if request['backend'] == backend)))
    add_run(root, 2000, INDICES)
    return root, selection, ctx


@pytest.mark.parametrize('requested,parent', [('[33]', None), ('[0]', 2000), ('[33,33]', 2000),
                                              ('[]', 2000), ('[true]', 2000), ('[33]', -1)])
def test_cold_subset_and_invalid_resumes_rejected(recovery_api, requested, parent):
    with pytest.raises(ValueError):
        r.select_tasks(requested, parent)


def test_all_1520_bindings_preserved_with_exact_sixteen_replacements(recovery_api):
    root, original, ctx = recovery_api
    selected = r.rebind(original, 2000, 1, INDICES, root, REVISION)
    assert len(selected['selected']) == 1520
    for old, new in zip(original['selected'], selected['selected'], strict=True):
        if old['index'] in INDICES:
            assert new['missing_output_parent'] == old and new['recovery_revision'] == REVISION
            assert 'previous' not in new
        else:
            assert new == old
    with pytest.raises(ValueError, match='already replaced'):
        r.rebind(selected, 2000, 1, INDICES, root, REVISION)


@pytest.mark.parametrize('mutation', ['live_parent', 'parent_output', 'runner_assigned', 'recorded_step',
                                     'wrong_parent', 'gate_failed', 'missing_job', 'missing_task'])
def test_rebind_rejects_ineligible_parent_or_incomplete_scope(recovery_api, mutation):
    root, original, ctx = recovery_api
    parent = ctx['rows'][33]
    directory = root/str(parent['run_id'])/'attempt-1'
    jobs = work.read(directory/'jobs.json')
    job = next(j for j in jobs['jobs'] if j['id'] == parent['job_id'])
    indices = INDICES
    if mutation == 'live_parent': job['status'] = 'in_progress'
    elif mutation == 'runner_assigned': job['runner_id'] = 99
    elif mutation == 'recorded_step': job['steps'] = [{'name': 'started'}]
    elif mutation == 'wrong_parent': original['selected'][33]['job_id'] += 100
    elif mutation == 'missing_task': indices = INDICES[:-1]
    elif mutation == 'parent_output':
        work.write_json(directory/'artifacts.json', {'total_count': 1, 'artifacts': [{'id': 99, 'name': parent['artifact_name']}]})
    else:
        target = root/'2000/attempt-1/jobs.json'
        new_jobs = work.read(target)
        if mutation == 'gate_failed': new_jobs['jobs'][0]['conclusion'] = 'failure'
        else: new_jobs['jobs'].pop(); new_jobs['total_count'] -= 1
        work.write_json(target, new_jobs)
    work.write_json(directory/'jobs.json', jobs)
    with pytest.raises((ValueError, StopIteration)):
        r.rebind(original, 2000, 1, indices, root, REVISION)


class GitHub:
    repository = 'm9h/GRN_ODE'
    def __init__(self, root, archives):
        self.root, self.archives = root, archives
    def api(self, endpoint):
        run_id = int(endpoint.split('/')[2])
        return work.read(self.root/str(run_id)/'attempt-1/run.json')
    def rows(self, endpoint, field):
        run_id = int(endpoint.split('/')[2])
        return work.read(self.root/str(run_id)/'attempt-1'/(field+'.json'))[field]
    def download(self, artifact_id, output):
        shutil.copyfile(self.archives/f'artifact-{artifact_id}.zip', output)


def set_job(root, run_id, index, status):
    path = root/str(run_id)/'attempt-1/jobs.json'
    data = work.read(path)
    job = next(j for j in data['jobs'] if j['name'] == r.cloud.job_name(index))
    job.update(status=status, conclusion='success' if status == 'completed' else None,
               completed_at='2026-11-24T07:00:00Z' if status == 'completed' else None)
    work.write_json(path, data)


def publish(root, archives, output, run_id, index):
    artifact_id = run_id*100+index
    archives.mkdir(exist_ok=True)
    path = archives/f'artifact-{artifact_id}.zip'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for file in output.rglob('*'):
            name = file.relative_to(output).as_posix()
            if file.is_file() and name in r.cloud.ALLOWED:
                archive.write(file, name)
    artifact = {'id': artifact_id, 'name': r.cloud.artifact_name(index, 1), 'expired': False,
                'workflow_run': {'id': run_id, 'head_sha': REVISION},
                'created_at': '2026-11-24T06:59:00Z', 'digest': 'sha256:'+work.digest(path),
                'size_in_bytes': path.stat().st_size}
    work.write_json(root/str(run_id)/'attempt-1/artifacts.json', {'total_count': 1, 'artifacts': [artifact]})
    set_job(root, run_id, index, 'completed')
    return artifact


def test_execute_and_collect_recovery_without_narrowing_full_scope(recovery_api, fake, tmp_path):
    root, original, ctx = recovery_api
    selected = r.rebind(original, 2000, 1, INDICES, root, REVISION)
    set_job(root, 2000, 33, 'in_progress')
    output, archives = tmp_path/'recovery', tmp_path/'archives'
    result = r.execute(GitHub(root, archives), 2000, 1, REVISION, 33, output)
    assert result['status'] == 'completed' and len(fake) == 1
    assert fake[0]['kwargs']['resume'] is False
    assert fake[0]['times'][-1] == work.read(output/'evidence/report.json')['identity']['specification']['stop']
    publish(root, archives, output, 2000, 33)
    selection_path = tmp_path/'recovery-selection.json'
    work.write_json(selection_path, selected)
    result = c.collect(selection_path, root, archives, tmp_path/'collected')
    assert not result['verification_errors'] and result['required_tasks'] == 1520
    assert result['complete_arrays'] == 1 and not result['all_required_arrays_verified']
    assert result['tasks'][33]['cancelled_parent_job_preserved'] == ctx['rows'][33]['job_id']
    assert not result['case_recovery_claimed'] and not result['full_model_coverage_claimed']


@pytest.mark.parametrize('mutation', ['parent_output', 'live_parent', 'gate_failed'])
def test_execute_rechecks_live_api_before_any_integration(recovery_api, fake, tmp_path, mutation):
    root, original, ctx = recovery_api
    set_job(root, 2000, 33, 'in_progress')
    if mutation == 'parent_output':
        work.write_json(root/'1000/attempt-1/artifacts.json', {'total_count': 1, 'artifacts':
            [{'name': ctx['rows'][33]['artifact_name']}]})
    elif mutation == 'live_parent': set_job(root, 1000, 33, 'in_progress')
    else:
        path = root/'2000/attempt-1/jobs.json'; jobs = work.read(path)
        jobs['jobs'][0]['conclusion'] = 'failure'; work.write_json(path, jobs)
    with pytest.raises(ValueError):
        r.execute(GitHub(root, tmp_path/'archives'), 2000, 1, REVISION, 33, tmp_path/'invalid')
    assert not fake and not (tmp_path/'invalid').exists()


@pytest.mark.parametrize('invalid_state', [False, True])
def test_later_recovery_resume_validates_state_before_reusing_full_arrays(recovery_api, fake, tmp_path, monkeypatch, invalid_state):
    root, original, ctx = recovery_api
    selected = r.rebind(original, 2000, 1, INDICES, root, REVISION)
    set_job(root, 2000, 33, 'in_progress')
    archives, first = tmp_path/'archives', tmp_path/'first'
    github = GitHub(root, archives)
    r.execute(github, 2000, 1, REVISION, 33, first)
    publish(root, archives, first, 2000, 33)
    add_run(root, 3000, [33], 'in_progress')
    selected = r.rebind(selected, 3000, 1, [33], root, REVISION, parent_run=2000)
    validations = []
    def validate(path, times, trains, request):
        validations.append(str(path))
        if invalid_state: raise ValueError('Synthetic exact-state mismatch')
        # Exact adapter round trips are tested by the separate Linux adapter suites.
        return {'sha256': work.digest(path), 'state_validated_in_matching_runtime': True,
                'numerical_integrations_performed': 0}
    monkeypatch.setattr(r.cloud, 'validate_checkpoint', validate)
    second = tmp_path/'second'
    if invalid_state:
        with pytest.raises(ValueError, match='exact-state'):
            r.execute(github, 3000, 1, REVISION, 33, second, parent_run=2000)
        assert work.read(second/'execution.json')['status'] == 'restore_failed'
    else:
        r.execute(github, 3000, 1, REVISION, 33, second, parent_run=2000)
        assert work.digest(first/'evidence/trajectory.npz') == work.digest(second/'evidence/trajectory.npz')
        publish(root, archives, second, 3000, 33)
        path = tmp_path/'continued-selection.json'; work.write_json(path, selected)
        result = c.collect(path, root, archives, tmp_path/'continued-collection')
        assert not result['verification_errors'] and result['complete_arrays'] == 1
        assert result['tasks'][33]['parent_archive_verified']
    assert validations and len(fake) == 1


def test_workflow_reuses_frozen_environment_and_gates_complete_recovery():
    text = (work.ROOT.parent/r.WORKFLOW).read_text()
    assert 'needs: marhl-full-precision' in text and 'test_marhl_missing_output.py' in text
    assert 'environments/marhl-full-precision-requirements.txt' in text
    assert 'timeout --signal=TERM --kill-after=30s 18000s' in text
    assert 'retention-days: 90' in text and 'if: always()' in text
