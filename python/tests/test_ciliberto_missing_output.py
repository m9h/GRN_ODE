"""Missing-job routing and frozen-source checks; no numerical integrations."""
from copy import deepcopy
from pathlib import Path
import subprocess
import zipfile

import pytest

from scripts import ciliberto_missing_output as recovery
from scripts import audit_ciliberto_full_cases as full
from test_ciliberto_later_controls import context, synthetic, save
from test_ciliberto_later_collection import branch, partition_fixture, api_fixture
from test_ciliberto_full_case_audit import first_plan, stage_fixture


@pytest.fixture
def recovery_api(monkeypatch):
    revision = 'a'*40
    run = {'id': 50000000001, 'run_attempt': 1, 'workflow_id': 500000001,
           'head_sha': revision, 'path': recovery.WORKFLOW, 'event': 'workflow_dispatch',
           'repository': {'full_name': 'm9h/GRN_ODE'}}
    gate = {'id': 150000000001, 'name': 'validation', 'run_id': run['id'], 'run_attempt': 1,
            'head_sha': revision, 'status': 'completed', 'conclusion': 'success'}
    job = {**gate, 'id': 150000000002, 'name': 'ciliberto-later-controls-43',
           'status': 'queued', 'conclusion': None}
    # API fixtures are explicitly synthetic. Actual frozen files/runtime are
    # checked separately below and by the required Linux workflow gate.
    proof = {'revision': revision, 'synthetic_test_fixture': True,
             'frozen_numerical_files': recovery.read(recovery.PLAN)['runtime']['source_hashes']}
    monkeypatch.setattr(recovery, 'source_proof', lambda selected: proof)
    return run, {'total_count': 2, 'jobs': [gate, job]}, revision


def test_capture_keeps_full_scope_and_all_existing_archives():
    capture, plan, selection = recovery.check_capture()
    assert len(selection['selected']) == 256 and len(plan['partitions']) == 256
    assert sum(len(r['branches']) for r in selection['selected']) == 6859
    assert capture['required_full_branches'] == 7334 and capture['required_cases'] == 74
    assert capture['captured_original_archives'] == 195
    assert capture['captured_original_archive_bytes'] == 478646175890
    assert capture['missing_indices'] == [43]
    assert len(selection['selected'][43]['branches']) == 27


@pytest.mark.parametrize('change', ['dependency_hash', 'version', 'repo_hash'])
def test_installed_dependency_and_repository_changes_rejected(monkeypatch, change):
    plan = recovery.read(recovery.PLAN)
    runtime = deepcopy(plan['runtime'])
    if change == 'dependency_hash':
        runtime['source_hashes']['jaxkineticmodel/load_sbml/sbml_model.py'] = 'wrong'
    elif change == 'version':
        runtime['versions']['jax'] = 'wrong'
    else:
        runtime['source_hashes']['uv.lock'] = 'wrong'
    monkeypatch.setattr(recovery.producer, 'runtime', lambda: runtime)
    with pytest.raises(ValueError, match='runtime changed'):
        recovery.check_runtime(plan)


def test_repository_and_installed_dependencies_are_both_checked():
    plan = recovery.read(recovery.PLAN)
    files = recovery.check_runtime(plan)
    assert len(files) + len(recovery.DEPENDENCY_FILES) == len(plan['runtime']['source_hashes'])
    assert {'uv.lock', 'pyproject.toml'} <= set(files)
    for name, sha in files.items():
        assert recovery.digest(recovery.ROOT/name) == sha
        frozen = subprocess.check_output(['git', 'show', recovery.original.RUN['head_sha']+':python/'+name],
                                         cwd=recovery.ROOT)
        import hashlib
        assert hashlib.sha256(frozen).hexdigest() == sha


@pytest.mark.parametrize('value', ['[]', '[0]', '[43,44]', '[43,43]', '[43.0]', '[true]', '{}', 'null'])
def test_only_missing_partition_can_be_requested(value):
    with pytest.raises(ValueError):
        recovery.indices(value)


def test_only_actual_missing_job_is_rebound(recovery_api):
    selected = recovery.bind(*recovery_api)
    original = recovery.read(recovery.INPUTS/'original-selection.json')['selected']
    assert sum(a == b for a,b in zip(selected['selected'], original, strict=True)) == 255
    assert selected['selected'][43]['previous'] == original[43]
    assert selected['selected'][43]['job_id'] == recovery_api[1]['jobs'][1]['id']
    assert selected['required_full_branches'] == 7334 and selected['required_cases'] == 74
    assert not selected['case_recovery_claimed'] and not selected['full_model_coverage_claimed']


@pytest.mark.parametrize('change', ['gate_queued', 'gate_failed', 'missing_job', 'extra_job', 'duplicate_id',
                                   'wrong_job', 'wrong_source', 'wrong_attempt', 'wrong_workflow', 'wrong_repo'])
def test_recovery_requires_exact_actual_run_and_successful_gate(recovery_api, change):
    run, jobs, revision = recovery_api
    if change == 'gate_queued': jobs['jobs'][0]['status'] = 'queued'
    elif change == 'gate_failed': jobs['jobs'][0]['conclusion'] = 'failure'
    elif change == 'missing_job': jobs['jobs'].pop()
    elif change == 'extra_job': jobs['jobs'].append(deepcopy(jobs['jobs'][1])); jobs['total_count'] += 1
    elif change == 'duplicate_id': jobs['jobs'][1]['id'] = jobs['jobs'][0]['id']
    elif change == 'wrong_job': jobs['jobs'][1]['name'] = 'ciliberto-later-controls-44'
    elif change == 'wrong_source': jobs['jobs'][1]['head_sha'] = 'b'*40
    elif change == 'wrong_attempt': jobs['jobs'][1]['run_attempt'] = 2
    elif change == 'wrong_workflow': run['path'] = recovery.original.RUN['path']
    elif change == 'wrong_repo': run['repository']['full_name'] = 'different/repo'
    with pytest.raises(ValueError): recovery.bind(run, jobs, revision)


@pytest.mark.parametrize('change', ['live_job', 'artifact_available', 'incomplete_pages'])
def test_available_or_running_original_is_never_replaced(change):
    _, _, selection = recovery.check_capture()
    run, jobs, artifacts = (recovery.read(recovery.INPUTS/'original-api'/(n+'.json'))
                            for n in ('run', 'jobs', 'artifacts'))
    row = selection['selected'][43]
    if change == 'live_job':
        next(j for j in jobs['jobs'] if j['id'] == row['job_id'])['status'] = 'in_progress'
    elif change == 'artifact_available':
        artifacts['artifacts'].append({'name': row['artifact_name']}); artifacts['total_count'] += 1
    else:
        jobs['jobs'].pop()
    with pytest.raises(ValueError): recovery.validate_missing(row, run, jobs, artifacts)


def test_original_collector_identity_is_not_mutated(recovery_api, branch, context):
    run = recovery_api[0]
    original_identity = deepcopy(recovery.original.RUN)
    bound = recovery.isolated_collector(run)
    directory, row, entry = branch
    report = recovery.read(directory/'report.json')
    report.update(source_revision=run['head_sha'], run_id=str(run['id']))
    recovery.write(directory/'report.json', report)
    result = bound.verify_branch(directory, row, entry, context)
    assert result['verified_arrays'] == 4 and result['complete_diagnostic']
    assert recovery.original.RUN == original_identity
    with pytest.raises(ValueError): recovery.original.verify_branch(directory, row, entry, context)


def prepare_descriptor(tmp_path, api, *, artifacts=None):
    run, jobs, revision = api
    root = tmp_path/'recovery'
    root.mkdir()
    (root/'api').mkdir()
    recovery.write(root/'binding.json', recovery.bind(run, jobs, revision))
    for name, value in [('run', run), ('jobs', jobs), ('artifacts', artifacts or {'total_count': 0, 'artifacts': []})]:
        recovery.write(root/'api'/(name+'.json'), value)
    recovery.write(root/'descriptor.json', {'binding':'binding.json', 'snapshots':'api', 'cache':'cache'})
    return root/'descriptor.json'


@pytest.mark.parametrize('change', ['selection', 'branch', 'gate', 'artifacts'])
def test_persisted_binding_cannot_be_changed(recovery_api, tmp_path, change):
    descriptor = prepare_descriptor(tmp_path, recovery_api)
    path = descriptor.parent/'binding.json'
    binding = recovery.read(path)
    if change == 'selection': binding['selected'].pop()
    elif change == 'branch': binding['selected'][43]['branches'].pop()
    elif change == 'gate': binding['validation_job_id'] += 1
    else:
        recovery.write(descriptor.parent/'api/artifacts.json', {'total_count':1, 'artifacts':[]})
    recovery.write(path, binding)
    with pytest.raises(ValueError): recovery.Recovery(descriptor)


@pytest.mark.parametrize('replacement_status', ['queued', 'missing_checkpoint', 'tampered_zip'])
def test_replacement_route_preserves_other_outputs_and_full_scope(
        recovery_api, branch, context, first_plan, tmp_path, replacement_status):
    paths, validation, output, store, _ = stage_fixture(branch, context, tmp_path)
    # Keep one complete synthetic original branch; use the pinned original job
    # identities for all 256 partitions. Every other branch remains required.
    original_selection = recovery.read(recovery.INPUTS/'original-selection.json')
    original_jobs = recovery.read(recovery.INPUTS/'original-api/jobs.json')
    original_artifact = recovery.read(paths['snapshots']/'artifacts.json')['artifacts'][0]
    for job in original_jobs['jobs']:
        if job['name'] == 'validation': continue
        if job['name'] == 'ciliberto-later-controls-43': continue
        row = next(r for r in original_selection['selected'] if r['job_id'] == job['id'])
        if row['artifact_name'] == original_artifact['name']:
            job.update(status='completed', conclusion='timed_out', started_at='2026-11-18T23:00:00Z',
                       completed_at='2026-11-19T05:00:00Z')
        else:
            job.update(status='queued', conclusion=None)
    recovery.write(paths['selection'], original_selection)
    recovery.write(paths['snapshots']/'jobs.json', original_jobs)
    descriptor = prepare_descriptor(tmp_path, recovery_api)
    run, jobs, _ = recovery_api
    if replacement_status != 'queued':
        jobs['jobs'][1].update(status='completed', conclusion='failure', started_at='2026-11-26T00:00:00Z',
                               completed_at='2026-11-26T06:00:00Z')
        recovery.write(descriptor.parent/'api/jobs.json', jobs)
        target = descriptor.parent/'cache'/str(run['id'])/'attempt-1/artifact-2'
        (target/'evidence').mkdir(parents=True)
        (target/'evidence/execution.json.tmp').write_text('{interrupted')
        archive = target/'download.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.write(target/'evidence/execution.json.tmp', 'execution.json.tmp')
        artifact = {'id':2, 'name':original_selection['selected'][43]['artifact_name'], 'expired':False,
                    'workflow_run':{'id':run['id'], 'head_sha':run['head_sha']},
                    'created_at':'2026-11-26T05:59:00Z', 'digest':'sha256:'+recovery.digest(archive),
                    'size_in_bytes':archive.stat().st_size}
        recovery.write(descriptor.parent/'api/artifacts.json', {'total_count':1, 'artifacts':[artifact]})
        if replacement_status == 'tampered_zip':
            with archive.open('ab') as stream: stream.write(b'tampered')
    selected = recovery.Recovery(descriptor)
    result = full.verify_stage('controls', paths, context, first_plan, validation, output, store, recovery=selected)
    assert len(store) == 7334
    assert sum(r['complete_diagnostic'] for r in store.index.values()) == 1
    assert store[branch[1]['record_id']]['verified_arrays'] == 4
    assert result['missing_output_recovery']['unchanged_original_selections'] == 255
    assert not result['missing_output_recovery']['case_recovery_claimed']
    assert bool(result['verification_errors']) == (replacement_status == 'tampered_zip')
    if replacement_status == 'missing_checkpoint':
        recovered = next(p for p in result['partitions'] if p['index'] == 43)
        assert recovered['recovery_run']['id'] == run['id']
        assert not recovered['complete_selected_diagnostics']
        rows = original_selection['selected'][43]['branches']
        assert len(rows) == 27
        assert all(store[b['record_id']]['status'] == 'not_started' for b in rows)
