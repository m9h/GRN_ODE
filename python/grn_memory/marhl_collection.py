"""Offline collection of all 1,520 original Marhl precision tasks.

The caller supplies fixed run/attempt/job selections and original GitHub API
snapshots and ZIPs. No network access, integration, or automatic replacement of
failed tasks occurs here. Partial checkpoints are preserved; only complete
original arrays can enter the six-way branch comparison.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

import numpy as np

from . import marhl_cloud as cloud, marhl_precision as work
from .marhl_precision import digest, read, require, write_json

REPOSITORY = 'm9h/GRN_ODE'
PRODUCER = 'a3778b8cbb8bfdc16a9ddd4bbe84dd213fdf1022'
PLAN_SHA = 'd5589646d0f6393eaf7a76635276e6ac585d949cc2718e52c1ccc7e3df83abb3'
FIELDS = {'index', 'batch', 'run_id', 'run_attempt', 'job_id', 'artifact_name'}


def context():
    plan, inventory = work.check_plan(cloud.PLAN, cloud.INVENTORY)
    require(digest(cloud.PLAN) == PLAN_SHA, 'Complete original task plan differs')
    for name, sha in cloud.source_files().items():
        original = subprocess.check_output(['git', 'show', PRODUCER+':'+name], cwd=work.ROOT)
        require(hashlib.sha256(original).hexdigest() == sha, 'Frozen producer file differs: '+name)
    return plan, inventory


def regular(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'Regular original file required: '+str(path))
    return path


def snapshot(root, run_id, attempt):
    require(type(run_id) is int and run_id > 0 and type(attempt) is int and attempt > 0,
            'Exact positive run and attempt required')
    directory = Path(root)/str(run_id)/f'attempt-{attempt}'
    run, jobs, artifacts = [read(regular(directory/(name+'.json'))) for name in ('run', 'jobs', 'artifacts')]
    require(run['id'] == run_id and run['run_attempt'] == attempt and run['head_sha'] == PRODUCER
            and run['path'] == cloud.WORKFLOW and run['event'] == 'workflow_dispatch',
            'Selected workflow run, attempt or frozen source differs')
    for data, field in ((jobs, 'jobs'), (artifacts, 'artifacts')):
        require(type(data['total_count']) is int and data['total_count'] == len(data[field])
                and len({row['id'] for row in data[field]}) == len(data[field]),
                'Complete unique API inventory required: '+field)
    for job in jobs['jobs']:
        require(job['run_id'] == run_id and job['run_attempt'] == attempt and job['head_sha'] == PRODUCER,
                'Job run, attempt or source differs')
    gates = [j for j in jobs['jobs'] if j['name'] == 'marhl-full-precision']
    require(len(gates) == 1 and gates[0]['status'] == 'completed' and gates[0]['conclusion'] == 'success',
            'The matching Linux validation gate must have passed')
    return run, jobs['jobs'], artifacts['artifacts'], directory


def task_binding(index, batch, run, jobs):
    matches = [j for j in jobs if j['name'] == cloud.job_name(index)]
    require(len(matches) == 1 and type(matches[0]['id']) is int and matches[0]['id'] > 0,
            'Exactly one original task job is required')
    return {'index': index, 'batch': batch, 'run_id': run['id'], 'run_attempt': run['run_attempt'],
            'job_id': matches[0]['id'], 'artifact_name': cloud.artifact_name(index, run['run_attempt'])}


def bind(batches, snapshots):
    """Bind all six declared initial batches before examining numerical outcomes."""
    plan, _ = context()
    require(isinstance(batches, list) and len(batches) == len(plan['batches'])
            and [r['batch'] for r in batches] == list(range(len(plan['batches'])))
            and len({r['run_id'] for r in batches}) == len(batches), 'All six unique original batch runs required')
    selected = []
    for batch in batches:
        run, jobs, _, _ = snapshot(snapshots, batch['run_id'], batch['run_attempt'])
        indices = plan['batches'][batch['batch']]
        require({j['name'] for j in jobs} == {'marhl-full-precision', *(cloud.job_name(i) for i in indices)}
                and len(jobs) == len(indices)+1, 'Complete batch job inventory differs')
        selected.extend(task_binding(i, batch['batch'], run, jobs) for i in indices)
    result = {'schema': 1, 'repository': REPOSITORY, 'source_revision': PRODUCER,
              'plan_sha256': PLAN_SHA, 'inventory_sha256': work.INVENTORY_SHA256,
              'task_count': plan['task_count'], 'selected': selected}
    validate_selection(result, plan)
    return result


def validate_selection(selection, plan):
    require({k: selection[k] for k in ('schema', 'repository', 'source_revision', 'plan_sha256',
            'inventory_sha256', 'task_count')} == {'schema': 1, 'repository': REPOSITORY,
            'source_revision': PRODUCER, 'plan_sha256': PLAN_SHA,
            'inventory_sha256': work.INVENTORY_SHA256, 'task_count': plan['task_count']},
            'Selection identity or complete scope differs')
    require([r['index'] for r in selection['selected']] == list(range(plan['task_count'])),
            'Every original task must appear exactly once in order')
    for row in selection['selected']:
        current, seen = row, set()
        while current is not None:
            require(set(current) in (FIELDS, FIELDS | {'previous'})
                    and all(type(current[k]) is int for k in ('index', 'batch', 'run_id', 'run_attempt', 'job_id'))
                    and current['index'] == row['index'] and current['batch'] == row['index']//plan['batch_size']
                    and min(current['run_id'], current['run_attempt'], current['job_id']) > 0
                    and current['artifact_name'] == cloud.artifact_name(row['index'], current['run_attempt']),
                    'Invalid task selection or continuation lineage')
            key = (current['run_id'], current['run_attempt'])
            require(key not in seen, 'Repeated run in checkpoint lineage')
            seen.add(key)
            current = current.get('previous')
    return selection


def rebind(selection, run_id, attempt, indices, snapshots):
    """Explicitly replace only terminal parents; keep their entire fixed lineage."""
    plan, _ = context()
    validate_selection(selection, plan)
    require(isinstance(indices, list) and indices and len(set(indices)) == len(indices)
            and all(type(i) is int and 0 <= i < plan['task_count'] for i in indices)
            and len({i//plan['batch_size'] for i in indices}) == 1, 'One original batch of unique tasks required')
    run, jobs, _, _ = snapshot(snapshots, run_id, attempt)
    require({j['name'] for j in jobs} == {'marhl-full-precision', *(cloud.job_name(i) for i in indices)}
            and len(jobs) == len(indices)+1, 'Explicit continuation task inventory differs')
    result = deepcopy(selection)
    for index in indices:
        old = result['selected'][index]
        _, parents, _, _ = snapshot(snapshots, old['run_id'], old['run_attempt'])
        parent = next(j for j in parents if j['id'] == old['job_id'])
        require(parent['status'] == 'completed', 'Do not replace a live numerical producer')
        result['selected'][index] = {**task_binding(index, old['batch'], run, jobs), 'previous': old}
    return validate_selection(result, plan)


def expected_runtime(request):
    return {'python': '3.12.13', 'system': 'Linux', 'machine': 'x86_64',
            'packages': {'numpy': '2.5.4', 'python-libsbml': '5.21.2',
                         **({'heyoka': '7.13.2'} if request['backend'] == 'heyoka' else {'mpmath': '1.4.1'})}}


def checkpoint_payload(path, report, times, request, trains):
    """Portable payload checks; exact restart-state validation remains in Linux."""
    with np.load(regular(path), allow_pickle=False) as z:
        require(set(z.files) == {'metadata', 'observations'}, 'Checkpoint member inventory differs')
        metadata, values = json.loads(str(z['metadata'])), z['observations'].copy()
    checksum = metadata.pop('payload_sha256')
    ci, ev = metadata['identity'], metadata['evidence']
    require(work.fingerprint(metadata) == checksum and work.fingerprint(ci) == metadata['identity_sha256'],
            'Checkpoint metadata checksum differs')
    require(values.dtype == np.float64 and values.ndim == 2 and values.shape[1] == len(work.NAMES)
            and 0 <= len(values) <= len(times) and np.isfinite(values).all()
            and hashlib.sha256(values.tobytes()).hexdigest() == metadata['observations_sha256'],
            'Checkpoint observation payload differs')
    require(ci['model_sha256'] == work.MODEL_SHA256 and ci['observables'] == work.NAMES
            and ci['trains'] == trains and ev['model_sha256'] == work.MODEL_SHA256
            and ev['precision_bits'] == request['precision'] and ev['sample_count'] == len(times)
            and ev['observables'] == work.NAMES and type(ev['completed']) is bool,
            'Checkpoint model, precision or protocol differs')
    require(isinstance(metadata['state'], list) and len(metadata['state']) == len(work.NAMES)
            and all(isinstance(v, str) and Decimal(v).is_finite() for v in metadata['state']),
            'Checkpoint internal state must be complete finite decimal text')
    grid = hashlib.sha256(times.tobytes()).hexdigest()
    if request['backend'] == 'mpmath':
        require(metadata['schema'] == 1 and ci['precision'] == request['precision']
                and ci['sample_grid_sha256'] == grid and ci['max_chunk_span'] == 1.
                and ci['implementation_sha256'] == {
                    'adapter': report['identity']['sources']['grn_memory/marhl_checkpoints.py'],
                    'equations': report['identity']['sources']['grn_memory/marhl_mpmath.py']},
                'mpmath checkpoint identity differs')
    else:
        require(metadata['schema'] == 2 and ci['precision_bits'] == request['precision']
                and ci['times_sha256'] == grid and ci['samples'] == len(times)
                and ci['checkpoint_steps'] == 1_000_000 and ci['sources'] == {
                    'adapter': report['identity']['sources']['grn_memory/taylor_reference.py'],
                    'checkpoints': report['identity']['sources']['grn_memory/taylor_checkpoints.py']},
                'Heyoka checkpoint identity differs')
    return {'sha256': digest(path), 'saved_samples': len(values), 'completed': ev['completed'],
            'portable_payload_verified': True, 'exact_restart_state_validated': False}


def verify_task(directory, row, plan, inventory):
    execution = read(regular(directory/'execution.json'))
    expected = {'schema': 1, 'repository': REPOSITORY, 'run_id': row['run_id'],
                'run_attempt': row['run_attempt'], 'job_id': row['job_id'], 'head_sha': PRODUCER,
                'workflow_path': cloud.WORKFLOW, 'task_index': row['index'], 'batch': row['batch'],
                'task_count': plan['task_count'], 'plan_sha256': PLAN_SHA,
                'inventory_sha256': work.INVENTORY_SHA256, 'evidence_directory': 'evidence'}
    require(all(execution.get(k) == v for k, v in expected.items()), 'Execution identity differs')
    require(execution['source_provenance'] == {'source_revision': PRODUCER,
            'file_sha256': cloud.source_files(), 'implementation_files_differing_from_revision': []},
            'Producer source provenance differs')
    parent = row.get('previous')
    require(execution.get('requested_parent_run') == (parent['run_id'] if parent else None),
            'Executed parent differs from the fixed selection')
    evidence = directory/'evidence'
    if not (evidence/'report.json').exists():
        require(execution['status'] in ('running', 'restoring', 'restore_failed'), 'Missing task report')
        return {'status': 'preparation_failed', 'complete_array_verified': False, 'checkpoint': None,
                'execution_status': execution['status'], 'error': execution.get('error')}
    report = read(regular(evidence/'report.json'))
    bid, label, spec, times = work.problem(plan, inventory, row['index'])
    request = work.REQUESTS[label]
    expected = work.identity(plan, bid, label, spec, times, row['index'], expected_runtime(request))
    require(report.get('identity') == expected and report.get('fingerprint') == work.fingerprint(expected),
            'Task, complete protocol, runtime or source identity differs')
    status = report['status']
    require(status in ('completed', 'running', 'checkpointed', 'integration_failed'), 'Unknown numerical task status')
    if 'finished_at' in execution:
        require(execution['status'] == status, 'Finished execution and numerical report disagree')
    checkpoint = None
    if (evidence/'checkpoint.npz').exists():
        checkpoint = checkpoint_payload(evidence/'checkpoint.npz', report, times, request, spec['reset_trains'])
        if status != 'running' and report.get('checkpoint_sha256') is not None:
            require(checkpoint['sha256'] == report['checkpoint_sha256'], 'Recorded checkpoint digest differs')
    require(status not in ('completed', 'checkpointed') or checkpoint is not None, 'Missing required checkpoint')
    if status == 'integration_failed':
        require(isinstance(report.get('error'), str) and bool(report['error']), 'Failure requires explicit error evidence')
    if status == 'completed':
        work.load_trace(evidence, report, times, request, spec['reset_trains'])
    return {'status': status, 'report_sha256': digest(evidence/'report.json'), 'branch_id': bid,
            'request_label': label, 'complete_array_verified': status == 'completed', 'checkpoint': checkpoint,
            'unclaimed_orphan_trajectory': (evidence/'trajectory.npz').exists() and status != 'completed',
            'error': report.get('error'), 'interruption': report.get('interruption')}


def validate_artifact(artifact, run, job, row):
    require(artifact['name'] == row['artifact_name'] and not artifact['expired']
            and artifact['workflow_run']['id'] == run['id'] and artifact['workflow_run']['head_sha'] == PRODUCER
            and datetime.fromisoformat(artifact['created_at']) >= datetime.fromisoformat(job['started_at'])
            and type(artifact['id']) is int and artifact['id'] > 0
            and type(artifact['size_in_bytes']) is int and 0 < artifact['size_in_bytes'] <= cloud.MAX_ARCHIVE_BYTES
            and bool(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))),
            'Artifact run, attempt, source, time, size or digest differs')


def check_parent(directory, parent_directory, parent_result):
    history = read(regular(directory/'evidence/restore-provenance.json'))['history']
    previous_path = parent_directory/'evidence/restore-provenance.json'
    previous = read(previous_path)['history'] if previous_path.exists() else []
    require(len(history) == len(previous)+1 and history[:-1] == previous, 'Restoration history was changed')
    last = history[-1]
    for key, value in {'parent_run_id': parent_result['run_id'], 'parent_run_attempt': parent_result['run_attempt'],
            'parent_job_id': parent_result['job_id'], 'artifact_id': parent_result['artifact_id'],
            'archive_sha256': parent_result['archive_sha256'], 'archive_bytes': parent_result['archive_bytes'],
            'archived_file_sha256': parent_result['extracted_file_sha256'], 'parent_revision': PRODUCER,
            'task_index': parent_result['index']}.items():
        require(last.get(key) == value, 'Restoration lineage differs: '+key)
    old = read(parent_directory/'evidence/report.json')
    new = read(directory/'evidence/report.json')
    require(new['attempts'][:len(old['attempts'])] == old['attempts'], 'Earlier numerical attempts were changed')
    old_path, new_path = parent_directory/'evidence/checkpoint.npz', directory/'evidence/checkpoint.npz'
    if old_path.exists():
        require(new_path.exists(), 'Restored checkpoint disappeared')
        with np.load(old_path, allow_pickle=False) as a, np.load(new_path, allow_pickle=False) as b:
            prefix, values = a['observations'], b['observations']
            require(len(values) >= len(prefix) and np.array_equal(prefix, values[:len(prefix)]),
                    'Previously saved observation prefix was changed')
    if old['status'] == 'completed':
        require(new == old and digest(directory/'evidence/trajectory.npz') == digest(parent_directory/'evidence/trajectory.npz'),
                'Completed parent evidence was replaced')


def collect(selection_path, snapshots, archives, output):
    plan, inventory = context()
    selection = validate_selection(read(regular(selection_path)), plan)
    output, snapshots, archives = Path(output), Path(snapshots), Path(archives)
    require(not output.exists() and not output.is_symlink(), 'Use a new collection directory')
    output.mkdir(parents=True)
    shutil.copyfile(selection_path, output/'selection.json')
    memo, preserved = {}, {}
    cached_snapshot = lru_cache(maxsize=None)(lambda run, attempt: snapshot(snapshots, run, attempt))

    def collect_one(row):
        key = (row['run_id'], row['run_attempt'], row['index'])
        if key in memo:
            return memo[key]
        run, jobs, artifacts, source = cached_snapshot(*key[:2])
        require({k: row[k] for k in FIELDS} == task_binding(row['index'], row['batch'], run, jobs),
                'Selected task job differs from the original API inventory')
        stamp = f'{key[0]}/attempt-{key[1]}'
        if stamp not in preserved:
            shutil.copytree(source, output/'api'/stamp)
            preserved[stamp] = {name: digest(source/name) for name in ('run.json', 'jobs.json', 'artifacts.json')}
        job = next(j for j in jobs if j['id'] == row['job_id'])
        result = {**{k: row[k] for k in FIELDS}, 'job_status': job['status'], 'job_conclusion': job['conclusion'],
                  'status': 'pending', 'complete_array_verified': False}
        if job['status'] != 'completed':
            result['pending_reason'] = 'job_'+job['status']
            memo[key] = result
            return result
        matches = [a for a in artifacts if a['name'] == row['artifact_name']]
        require(len(matches) <= 1, 'Ambiguous selected artifact')
        if not matches:
            result['pending_reason'] = 'missing_artifact'
            memo[key] = result
            return result
        artifact = matches[0]
        validate_artifact(artifact, run, job, row)
        archive = regular(archives/f'artifact-{artifact["id"]}.zip')
        require(archive.stat().st_size == artifact['size_in_bytes'] and 'sha256:'+digest(archive) == artifact['digest'],
                'Original archive size or server SHA-256 differs')
        destination = output/'artifacts'/str(artifact['id'])
        destination.mkdir(parents=True)
        try:
            os.link(archive, destination/'download.zip')
        except OSError:
            shutil.copyfile(archive, destination/'download.zip')
        directory = destination/'payload'
        files = cloud.extract(archive, directory)
        result.update(artifact_id=artifact['id'], archive_sha256=artifact['digest'],
                      archive_bytes=artifact['size_in_bytes'], extracted_file_sha256=files,
                      evidence_directory=str((directory/'evidence').resolve()))
        result.update(verify_task(directory, row, plan, inventory))
        if 'previous' in row:
            parent = collect_one(row['previous'])
            require('artifact_id' in parent, 'Original parent artifact is required')
            if result['status'] != 'preparation_failed':
                parent_dir = output/'artifacts'/str(parent['artifact_id'])/'payload'
                check_parent(directory, parent_dir, parent)
                result['parent_archive_verified'] = parent['archive_sha256']
        memo[key] = result
        return result

    tasks, errors = [], []
    for row in selection['selected']:
        try:
            tasks.append(collect_one(row))
        except (ValueError, KeyError, TypeError, OSError, ArithmeticError, zipfile.BadZipFile) as error:
            errors.append({'index': row['index'], 'error': f'{type(error).__name__}: {error}'})
            tasks.append({**row, 'status': 'verification_error', 'complete_array_verified': False})
    branches = []
    for position, bid in enumerate(plan['branches']):
        rows = tasks[4*position:4*position+4]
        if all(row['complete_array_verified'] for row in rows):
            try:
                audited = work.audit_branch(cloud.PLAN, cloud.INVENTORY, bid, [r['evidence_directory'] for r in rows])
                path = output/'branches'/(bid+'.json')
                write_json(path, audited)
                branches.append({'branch_id': bid, 'status': audited['status'], 'verified_arrays': 4,
                                 'file': str(path.relative_to(output)), 'sha256': digest(path)})
            except (ValueError, KeyError, TypeError, OSError) as error:
                errors.append({'branch_id': bid, 'error': f'{type(error).__name__}: {error}'})
                branches.append({'branch_id': bid, 'status': 'verification_error', 'verified_arrays': 0})
        else:
            branches.append({'branch_id': bid, 'status': 'incomplete',
                             'verified_arrays': sum(r['complete_array_verified'] for r in rows)})
    result = {'schema': 1, 'checked_at': work.now(), 'source_revision': PRODUCER,
              'selection_sha256': digest(selection_path), 'plan_sha256': PLAN_SHA,
              'inventory_sha256': work.INVENTORY_SHA256, 'required_tasks': plan['task_count'],
              'required_branches': len(plan['branches']), 'tasks': tasks, 'branches': branches,
              'original_api_snapshot_sha256': preserved, 'verification_errors': errors,
              'complete_arrays': sum(t['complete_array_verified'] for t in tasks),
              'complete_branches': sum(b['status'] in ('agreement', 'mismatch') for b in branches),
              'all_required_arrays_verified': not errors and all(t['complete_array_verified'] for t in tasks),
              'all_required_branches_agree': not errors and all(b['status'] == 'agreement' for b in branches),
              'collector_sha256': digest(__file__), 'array_auditor_sha256': digest(work.__file__),
              'numerical_integrations_performed': 0, 'case_recovery_claimed': False, 'full_model_coverage_claimed': False}
    write_json(output/'collection.json', result)
    return result
