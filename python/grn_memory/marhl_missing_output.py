"""Recover only the sixteen cancelled Marhl tasks with verified absent outputs.

Numerical sources, environments, task indices and observation grids are frozen.
This wrapper records missing-output provenance and supports exact later resumes.
"""
from functools import lru_cache
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile

from . import marhl_collection as collection, marhl_cloud as cloud, marhl_precision as work
from .marhl_precision import digest, read, require, write_json

ROOT = work.ROOT
WORKFLOW = '.github/workflows/marhl-precision-collection.yml'
BINDINGS = ROOT/'results/catalog-breaking-marhl-no-output-20261124'
BINDING_SHA = 'e83a84866d7cd5eefbdc1e2ac1c967fd2e98731dce2cd5753cb057c230d8ec0f'
RECOVERY_FIELDS = {'recovery_revision', 'missing_output_parent'}


def validate_missing_parent(run, job, artifacts, row):
    require(run['id'] == row['run_id'] and run['run_attempt'] == row['run_attempt']
            and run['head_sha'] == collection.PRODUCER and run['path'] == cloud.WORKFLOW
            and run['event'] == 'workflow_dispatch', 'Missing-output parent run differs')
    require(job['id'] == row['job_id'] and job['run_id'] == row['run_id']
            and job['run_attempt'] == row['run_attempt'] and job['head_sha'] == collection.PRODUCER
            and job['name'] == cloud.job_name(row['index']) and job['status'] == 'completed'
            and job['conclusion'] == 'cancelled' and job['completed_at']
            and job['runner_id'] == 0 and job['steps'] == [], 'Parent is not the selected unexecuted cancelled job')
    require(not any(a['name'] == row['artifact_name'] for a in artifacts),
            'Parent output exists; use verified checkpoint continuation instead')


def context():
    require(not (BINDINGS/'binding.json').is_symlink() and digest(BINDINGS/'binding.json') == BINDING_SHA,
            'Pinned missing-output binding differs')
    binding = read(BINDINGS/'binding.json')
    require(binding['schema'] == 1 and binding['original_producer'] == collection.PRODUCER
            and binding['full_task_count'] == 1520, 'Recovery source or full scope differs')
    for name, sha in binding['files'].items():
        path = (BINDINGS/name).resolve()
        require(path.is_relative_to(BINDINGS.resolve()) and not (BINDINGS/name).is_symlink()
                and digest(path) == sha, 'Pinned recovery input differs: '+name)
    plan, inventory = collection.context()
    selection = collection.validate_selection(read(BINDINGS/'selection.json'), plan)
    missing = read(BINDINGS/'missing-output-plan.json')
    rows = {r['original_binding']['index']: r['original_binding'] for r in missing['records']}
    require(len(rows) == 16 and sorted(rows) == binding['indices'], 'All sixteen missing-output tasks required')
    for index, row in rows.items():
        require(row == selection['selected'][index], 'Missing-output task selection differs')
        run, jobs, artifacts, _ = collection.snapshot(BINDINGS/'parents', row['run_id'], row['run_attempt'])
        require(row == collection.task_binding(index, row['batch'], run, jobs), 'Original parent job binding differs')
        validate_missing_parent(run, next(j for j in jobs if j['id'] == row['job_id']), artifacts, row)
    return {'plan': plan, 'inventory': inventory, 'rows': rows, 'binding': binding}


def source_files():
    files = cloud.source_files()
    own = ['python/grn_memory/marhl_missing_output.py', 'python/grn_memory/marhl_collection.py',
           'python/scripts/run_marhl_missing_output.py', WORKFLOW]
    own += ['python/'+(BINDINGS/name).relative_to(ROOT).as_posix()
            for name in ['binding.json', *read(BINDINGS/'binding.json')['files']]]
    files.update({name: digest(ROOT.parent/name) for name in own})
    return files


@lru_cache(None)
def source_at_revision(revision):
    require(bool(re.fullmatch('[0-9a-f]{40}', revision)), 'Exact recovery revision required')
    files = {name: hashlib.sha256(subprocess.check_output(['git', 'show', revision+':'+name],
                cwd=ROOT.parent)).hexdigest() for name in source_files()}
    require(all(files[name] == sha for name, sha in cloud.source_files().items()),
            'Recovery revision changes frozen numerical or original cloud sources')
    return files


def verify_current_source(revision):
    require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT.parent, text=True).strip() == revision,
            'Recovery checkout differs from the workflow')
    require(source_files() == source_at_revision(revision), 'Uncommitted recovery source differs')


def validate_row(row, ctx=None):
    ctx = context() if ctx is None else ctx
    require(type(row.get('recovery_revision')) is str
            and bool(re.fullmatch('[0-9a-f]{40}', row['recovery_revision'])), 'Invalid recovery source revision')
    require(row['index'] in ctx['rows'] and row['missing_output_parent'] == ctx['rows'][row['index']],
            'Recovery changed its original missing-output parent')
    previous = row.get('previous')
    require(previous is None or previous.get('recovery_revision') == row['recovery_revision']
            and previous.get('missing_output_parent') == row['missing_output_parent'],
            'Recovery checkpoint ancestry differs')


def verify_execution(execution, row, plan):
    validate_row(row)
    revision = row['recovery_revision']
    expected = {'schema': 1, 'repository': collection.REPOSITORY, 'run_id': row['run_id'],
        'run_attempt': row['run_attempt'], 'job_id': row['job_id'], 'head_sha': revision,
        'workflow_path': WORKFLOW, 'task_index': row['index'], 'batch': row['batch'],
        'task_count': plan['task_count'], 'plan_sha256': collection.PLAN_SHA,
        'inventory_sha256': work.INVENTORY_SHA256, 'evidence_directory': 'evidence',
        'recovery_binding_sha256': BINDING_SHA, 'missing_output_parent': row['missing_output_parent'],
        'case_recovery_claimed': False, 'full_model_coverage_claimed': False, 'max_seconds': 14400.}
    require(all(execution.get(k) == v for k, v in expected.items()), 'Recovery execution identity differs')
    require(execution.get('source_provenance') == {'source_revision': revision,
            'file_sha256': source_at_revision(revision), 'implementation_files_differing_from_revision': []},
            'Recovery source provenance differs')
    evidence = execution['missing_parent_evidence']
    validate_missing_parent(evidence['run'], evidence['job'], evidence['artifacts'], row['missing_output_parent'])


def select_tasks(requested='', parent_run=None):
    import json
    indices = sorted(context()['rows'])
    require(parent_run is None or type(parent_run) is int and parent_run > 0, 'Positive checkpoint parent required')
    if requested.strip():
        require(parent_run is not None, 'Cold recovery always includes all sixteen tasks')
        selected = json.loads(requested)
    else:
        selected = indices
    require(isinstance(selected, list) and selected and len(set(selected)) == len(selected)
            and all(type(i) is int and i in indices for i in selected), 'Invalid recovery task selection')
    return sorted(selected)


def binding(github, run_id, index, revision, terminal):
    run = github.api(f'actions/runs/{run_id}')
    require(run['id'] == run_id and run['path'] == WORKFLOW and run['head_sha'] == revision
            and run['event'] == 'workflow_dispatch' and type(run['run_attempt']) is int
            and run['run_attempt'] > 0, 'Recovery workflow identity differs')
    jobs = github.rows(f"actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs", 'jobs')
    gates = [j for j in jobs if j['name'] == 'marhl-full-precision']
    require(len(gates) == 1 and gates[0]['status'] == 'completed' and gates[0]['conclusion'] == 'success'
            and gates[0]['head_sha'] == revision and gates[0]['run_attempt'] == run['run_attempt'],
            'Matching Linux recovery validation must pass')
    matches = [j for j in jobs if j['name'] == cloud.job_name(index)]
    require(len(matches) == 1, 'Unique actual recovery task required')
    job = matches[0]
    require(job['run_id'] == run_id and job['run_attempt'] == run['run_attempt'] and job['head_sha'] == revision
            and job['status'] == ('completed' if terminal else 'in_progress'), 'Recovery task state differs')
    return run, job


def restore(github, parent_run, index, revision, output, ctx):
    output = Path(output)
    require(not output.exists() and not output.is_symlink(), 'Use a new recovery checkpoint directory')
    run, job = binding(github, parent_run, index, revision, True)
    row = {'index': index, 'batch': index//ctx['plan']['batch_size'], 'run_id': parent_run,
           'run_attempt': run['run_attempt'], 'job_id': job['id'],
           'artifact_name': cloud.artifact_name(index, run['run_attempt']),
           'recovery_revision': revision, 'missing_output_parent': ctx['rows'][index]}
    matches = [a for a in github.rows(f'actions/runs/{parent_run}/artifacts', 'artifacts')
               if a['name'] == row['artifact_name']]
    require(len(matches) == 1, 'Unique recovery checkpoint artifact required')
    artifact = matches[0]
    collection.validate_artifact(artifact, run, job, row, revision=revision)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='marhl-recovery-', dir=output.parent) as temporary:
        stage = Path(temporary)
        archive = stage/'download.zip'
        github.download(artifact['id'], archive)
        require(archive.stat().st_size == artifact['size_in_bytes'] and 'sha256:'+digest(archive) == artifact['digest'],
                'Recovery checkpoint archive differs')
        files = cloud.extract(archive, stage/'payload')
        execution = read(stage/'payload/execution.json')
        verify_execution(execution, row, ctx['plan'])
        source = stage/'payload/evidence'
        validation = cloud.validate_evidence(source, ctx['plan'], ctx['inventory'], index)
        require(execution.get('status') == validation['reported_status'] or 'finished_at' not in execution,
                'Recovery checkpoint final state differs')
        history_path = source/'restore-provenance.json'
        history = read(history_path)['history'] if history_path.exists() else []
        require(isinstance(history, list), 'Invalid recovery checkpoint history')
        provenance = {'restored_at': work.now(), 'repository': github.repository,
            'parent_run_id': parent_run, 'parent_run_attempt': run['run_attempt'], 'parent_job_id': job['id'],
            'parent_job_conclusion': job['conclusion'], 'parent_revision': revision, 'task_index': index,
            'artifact_id': artifact['id'], 'archive_sha256': artifact['digest'], 'archive_bytes': artifact['size_in_bytes'],
            'archived_file_sha256': files, 'validation': validation,
            'api_snapshots': {'run': run, 'job': job, 'artifact': artifact},
            'restore_script_sha256': digest(__file__), 'numerical_integrations_performed': 0}
        write_json(history_path, {'history': [*history, provenance]})
        source.rename(output)
    return provenance


def execute(github, run_id, attempt, revision, index, output, parent_run=None):
    ctx = context()
    require(index in ctx['rows'] and parent_run != run_id, 'Invalid recovery task or parent')
    run, job = binding(github, run_id, index, revision, False)
    require(run['run_attempt'] == attempt, 'Recovery run attempt differs')
    verify_current_source(revision)
    missing = ctx['rows'][index]
    old_run = github.api(f"actions/runs/{missing['run_id']}")
    old_jobs = github.rows(f"actions/runs/{missing['run_id']}/attempts/{missing['run_attempt']}/jobs", 'jobs')
    matches = [j for j in old_jobs if j['id'] == missing['job_id']]
    require(len(matches) == 1, 'Original missing-output job must still be identifiable')
    artifacts = github.rows(f"actions/runs/{missing['run_id']}/artifacts", 'artifacts')
    validate_missing_parent(old_run, matches[0], artifacts, missing)
    output = Path(output)
    require(not output.exists() and not output.is_symlink(), 'Use a new recovery output')
    output.mkdir(parents=True)
    execution = {'schema': 1, 'repository': github.repository, 'run_id': run_id, 'run_attempt': attempt,
        'job_id': job['id'], 'head_sha': revision, 'workflow_path': WORKFLOW, 'task_index': index,
        'batch': index//ctx['plan']['batch_size'], 'task_count': 1520, 'plan_sha256': collection.PLAN_SHA,
        'inventory_sha256': work.INVENTORY_SHA256, 'evidence_directory': 'evidence',
        'source_provenance': {'source_revision': revision, 'file_sha256': source_files(),
                              'implementation_files_differing_from_revision': []},
        'recovery_binding_sha256': BINDING_SHA, 'missing_output_parent': missing,
        'missing_parent_evidence': {'run': old_run, 'job': matches[0], 'artifacts': artifacts},
        'requested_parent_run': parent_run, 'status': 'restoring' if parent_run else 'running',
        'max_seconds': 14400., 'started_at': work.now(), 'case_recovery_claimed': False,
        'full_model_coverage_claimed': False}
    write_json(output/'execution.json', execution)
    if parent_run is not None:
        try:
            restore(github, parent_run, index, revision, output/'evidence', ctx)
        except Exception as error:
            execution.update(status='restore_failed', error=f'{type(error).__name__}: {error}', finished_at=work.now())
            write_json(output/'execution.json', execution)
            raise
    execution['status'] = 'running'
    write_json(output/'execution.json', execution)
    report = work.run_task(cloud.PLAN, cloud.INVENTORY, index, output/'evidence',
                           resume=parent_run is not None, max_seconds=14400.)
    execution.update(status=report['status'], finished_at=work.now(),
                     report_sha256=digest(output/'evidence/report.json'))
    write_json(output/'execution.json', execution)
    return {'task_index': index, 'status': report['status'], 'execution_sha256': digest(output/'execution.json'),
            'report_sha256': execution['report_sha256'], 'case_recovery_claimed': False}


def rebind(selection, run_id, attempt, indices, snapshots, revision, parent_run=None):
    ctx = context()
    collection.validate_selection(selection, ctx['plan'])
    require(isinstance(indices, list) and sorted(indices) == select_tasks(
        __import__('json').dumps(indices) if parent_run else '', parent_run), 'Recovery selection differs')
    run, jobs, _, _ = collection.snapshot(snapshots, run_id, attempt, revision=revision)
    require(len(jobs) == len(indices)+1 and {j['name'] for j in jobs} ==
            {'marhl-full-precision', *(cloud.job_name(i) for i in indices)}, 'Complete recovery job matrix required')
    from copy import deepcopy
    result = deepcopy(selection)
    for index in indices:
        old = result['selected'][index]
        if parent_run is None:
            require(old == ctx['rows'][index], 'Do not replace a computed or already replaced task')
            prior_run, prior_jobs, artifacts, _ = collection.snapshot(snapshots, old['run_id'], old['run_attempt'])
            validate_missing_parent(prior_run, next(j for j in prior_jobs if j['id'] == old['job_id']), artifacts, old)
        else:
            validate_row(old, ctx)
            require(old['run_id'] == parent_run and old['recovery_revision'] == revision, 'Recovery parent selection differs')
            _, parents, _, _ = collection.snapshot(snapshots, parent_run, old['run_attempt'], revision=revision)
            require(next(j for j in parents if j['id'] == old['job_id'])['status'] == 'completed', 'Do not replace a live recovery')
        row = {**collection.task_binding(index, index//ctx['plan']['batch_size'], run, jobs),
               'recovery_revision': revision, 'missing_output_parent': ctx['rows'][index]}
        if parent_run is not None:
            row['previous'] = old
        result['selected'][index] = row
    return collection.validate_selection(result, ctx['plan'])
