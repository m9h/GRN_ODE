"""Authenticated cloud execution and exact checkpoint restoration for Marhl.

Scheduling never reduces the 1,520-task inventory. Each restored input is bound
to its original workflow, attempt, terminal job, artifact digest, source revision
and complete numerical identity. State is validated in the matching runtime
before a restored directory is published. Restoration performs no integration.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import re
import stat
import subprocess
import tempfile
import zipfile

import numpy as np

from . import marhl_precision as work
from .marhl_precision import digest, read, require, write_json

ROOT = work.ROOT
PLAN = ROOT/'results/catalog-breaking-marhl-full-precision-20261119/plan.json'
INVENTORY = ROOT/'results/catalog-breaking-marhl-full-controls-20261118/inventory.json'
WORKFLOW = '.github/workflows/marhl-full-precision.yml'
MAX_ARCHIVE_BYTES = 256*1024*1024
CLOUD_FILES = ('python/grn_memory/marhl_cloud.py', 'python/scripts/run_marhl_cloud.py', WORKFLOW,
               'python/environments/marhl-full-precision-requirements.txt',
               'python/environments/marhl-checkpoint-requirements.txt',
               'python/results/catalog-breaking-marhl-full-precision-20261119/plan.json',
               'python/results/catalog-breaking-marhl-full-controls-20261118/inventory.json',
               'python/models/BIOMD0000000039.xml')
ALLOWED = {'execution.json', 'evidence/report.json', 'evidence/checkpoint.npz',
           'evidence/trajectory.npz', 'evidence/restore-provenance.json'}

class GitHub:
    def __init__(self, repository):
        require(bool(re.fullmatch(r'[\w.-]+/[\w.-]+', repository)), 'Specify owner/repository')
        self.repository = repository

    def api(self, endpoint):
        result = subprocess.run(['gh', 'api', f'repos/{self.repository}/{endpoint}'],
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def rows(self, endpoint, field):
        rows, page = [], 1
        while True:
            data = self.api(endpoint + f'?per_page=100&page={page}')
            require(isinstance(data.get(field), list), 'Invalid paginated GitHub inventory')
            rows.extend(data[field])
            if len(data[field]) < 100:
                require(len(rows) == data['total_count'], 'Incomplete GitHub inventory')
                return rows
            page += 1

    def download(self, artifact_id, output):
        require(type(artifact_id) is int and artifact_id > 0, 'Positive artifact ID required')
        with Path(output).open('wb') as stream:
            subprocess.run(['gh', 'api', '--allow-escape-sequences',
                            f'repos/{self.repository}/actions/artifacts/{artifact_id}/zip'],
                           check=True, stdout=stream, stderr=subprocess.PIPE)

def source_files():
    names = {*(f'python/{name}' for name in work.FILES), *CLOUD_FILES}
    return {name: digest(ROOT.parent/name) for name in sorted(names)}

def verify_sources(revision):
    require(bool(re.fullmatch(r'[0-9a-f]{40}', revision)), 'Exact producer revision required')
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT.parent, text=True).strip()
    require(actual == revision, 'Checkout revision differs from the workflow')
    files = source_files()
    for name, sha in files.items():
        original = subprocess.check_output(['git', 'show', revision+':'+name], cwd=ROOT.parent)
        require(hashlib.sha256(original).hexdigest() == sha, 'Uncommitted producer source differs: '+name)
    return {'source_revision': revision, 'file_sha256': files, 'implementation_files_differing_from_revision': []}

def select_tasks(plan, batch, requested='', resume_run=None):
    require(type(batch) is int and 0 <= batch < len(plan['batches']), 'Select one original batch')
    require(isinstance(requested, str), 'Task subset must be encoded as JSON text')
    require(resume_run is None or type(resume_run) is int and resume_run > 0, 'Positive parent run ID required')
    if requested.strip():
        require(type(resume_run) is int and resume_run > 0, 'Subset selection is only available for explicit continuation')
        selected = json.loads(requested)
    else:
        selected = plan['batches'][batch]
    require(isinstance(selected, list) and bool(selected)
            and all(type(i) is int and i in plan['batches'][batch] for i in selected)
            and len(selected) == len(set(selected)), 'Select unique tasks from the complete original batch')
    return sorted(selected)

def job_name(index):
    return f'marhl-precision-task-{index}'

def artifact_name(index, attempt):
    return f'{job_name(index)}-attempt-{attempt}'

def binding(github, run_id, index, *, terminal):
    require(type(run_id) is int and run_id > 0 and type(index) is int and 0 <= index < 1520,
            'Positive run ID and original task index required')
    run = github.api(f'actions/runs/{run_id}')
    require(run['id'] == run_id and run['path'] == WORKFLOW
            and type(run['run_attempt']) is int and run['run_attempt'] > 0
            and bool(re.fullmatch(r'[0-9a-f]{40}', run['head_sha'])), 'Unexpected workflow identity')
    rows = github.rows(f"actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs", 'jobs')
    jobs = [j for j in rows if j['name'] == job_name(index)]
    require(len(jobs) == 1 and type(jobs[0]['id']) is int and jobs[0]['id'] > 0
            and jobs[0]['run_id'] == run_id, 'Unique matching task job required')
    job = jobs[0]
    require(job['status'] == 'completed' if terminal else job['status'] == 'in_progress',
            'Parent task must be terminal' if terminal else 'Current task job must be running')
    return run, job

def checkpoint_context(times, trains, request):
    """Rebuild the exact adapter identity and protocol without solving the ODE."""
    _, events, counts, edges, chunks = work.marhl_checkpoints.protocol(times, trains, 1.)
    common = {'model_sha256': work.MODEL_SHA256, 'precision_bits': request['precision'],
              'numeric_inputs': 'binary64 values promoted exactly', 'absolute_time_preserved': True,
              'expected_resets': len(events), 'expected_train_reset_counts': counts,
              'expected_segments': len(edges)-1, 'sample_count': len(times), 'observables': work.NAMES.copy()}
    grid_sha = hashlib.sha256(times.tobytes()).hexdigest()
    if request['backend'] == 'mpmath':
        import mpmath
        context = mpmath.mp.clone()
        context.prec = request['precision']
        tolerance = str(context.mpf(request['tolerance']))
        base = {**common, 'backend': 'mpmath.odefun', 'mpmath_version': mpmath.__version__,
                'tolerance': tolerance, 'degree': request['degree'], 'expected_chunks': len(chunks)-1,
                'completed': False, 'rhs_evaluations': 0}
        identity = {'model_sha256': work.MODEL_SHA256, 'precision': request['precision'],
                    'tolerance': tolerance, 'degree': request['degree'], 'trains': trains,
                    'sample_grid_sha256': grid_sha,
                    'chunk_grid_sha256': hashlib.sha256(chunks.tobytes()).hexdigest(),
                    'max_chunk_span': 1., 'observables': work.NAMES.copy(),
                    'implementation_sha256': {'adapter': digest(work.marhl_checkpoints.__file__),
                                             'equations': digest(work.marhl_checkpoints.reference.__file__)},
                    'runtime': {'python': platform.python_version(), 'system': platform.system(),
                                'machine': platform.machine(), 'mpmath': mpmath.__version__,
                                'numpy': np.__version__, 'mpmath_backend': mpmath.libmp.BACKEND}}
        return identity, base, (context, events, counts, edges, chunks)
    import heyoka as hy
    import libsbml
    real = lambda value: hy.real(value, request['precision'])
    tolerance = str(real(request['tolerance']))
    base = {**common, 'tolerance': tolerance, 'high_accuracy': True}
    identity = {'model_sha256': work.MODEL_SHA256, 'precision_bits': request['precision'],
                'tolerance': tolerance, 'observables': work.NAMES.copy(), 'times_sha256': grid_sha,
                'samples': len(times), 'trains': trains, 'high_accuracy': True, 'compact_mode': True,
                'checkpoint_steps': 1_000_000, 'numeric_inputs': common['numeric_inputs'],
                'sources': {'adapter': digest(work.taylor_reference.__file__),
                            'checkpoints': digest(work.taylor_checkpoints.__file__)},
                'environment': {'heyoka': hy.__version__, 'numpy': np.__version__,
                                'libsbml': libsbml.getLibSBMLDottedVersion(),
                                'python': platform.python_version(), 'system': platform.system(),
                                'machine': platform.machine()}}
    return identity, base, (real, events, edges)

def validate_checkpoint(path, times, trains, request):
    identity, base, context = checkpoint_context(times, trains, request)
    if request['backend'] == 'mpmath':
        mp, events, counts, edges, chunks = context
        state, observations, evidence = work.marhl_checkpoints.load(
            path, identity, mp, times, events, counts, edges, chunks, base)
    else:
        real, events, edges = context
        state, observations, evidence = work.taylor_checkpoints.load(
            path, identity, times, edges, events, base, real)
        with np.load(path, allow_pickle=False) as z:
            metadata = json.loads(str(z['metadata']))
        require([str(v) for v in state] == metadata['state'], 'MPFR state is not a canonical exact round trip')
    return {'sha256': digest(path), 'saved_samples': len(observations),
            'completed_segments': evidence['completed_segments'], 'completed': evidence['completed'],
            'state_validated_in_matching_runtime': True, 'numerical_integrations_performed': 0}

def validate_evidence(directory, plan, inventory, index):
    bid, label, spec, times = work.problem(plan, inventory, index)
    request = work.REQUESTS[label]
    report_path = directory/'report.json'
    require(report_path.is_file() and not report_path.is_symlink(), 'Regular task report required')
    report = read(report_path)
    expected = work.identity(plan, bid, label, spec, times, index, work.runtime(request['backend']))
    require(report.get('identity') == expected and report.get('fingerprint') == work.fingerprint(expected),
            'Parent task, protocol, source or runtime differs')
    require(report.get('status') in ('running', 'checkpointed', 'completed', 'integration_failed'),
            'Unknown producer status')
    checkpoint = directory/'checkpoint.npz'
    validated = None
    if checkpoint.exists():
        require(not checkpoint.is_symlink(), 'Regular state checkpoint required')
        if report['status'] != 'running' and report.get('checkpoint_sha256') is not None:
            require(digest(checkpoint) == report['checkpoint_sha256'], 'Recorded checkpoint digest differs')
        validated = validate_checkpoint(checkpoint, times, spec['reset_trains'], request)
    if report['status'] in ('checkpointed', 'completed'):
        require(validated is not None, 'A saved or completed task requires its exact checkpoint')
    if report['status'] == 'completed':
        work.load_trace(directory, report, times, request, spec['reset_trains'])
    return {'report_sha256': digest(report_path), 'reported_status': report['status'],
            'checkpoint': validated, 'complete_array_verified': report['status'] == 'completed',
            'unclaimed_orphan_trajectory': (directory/'trajectory.npz').exists() and report['status'] != 'completed',
            'numerical_integrations_performed': 0}

def extract(archive, output):
    with zipfile.ZipFile(archive) as z:
        names, size = set(), 0
        for entry in z.infolist():
            require(entry.filename not in names and not stat.S_ISLNK(entry.external_attr >> 16)
                    and not entry.flag_bits & 1, 'Duplicate, linked or encrypted artifact member')
            names.add(entry.filename)
            require(entry.filename in ALLOWED or entry.is_dir() and entry.filename == 'evidence/',
                    'Unexpected artifact member: '+entry.filename)
            size += entry.file_size
        require(size <= MAX_ARCHIVE_BYTES, 'Artifact expands beyond the fixed task payload bound')
        z.extractall(output)
    return {str(p.relative_to(output)): digest(p) for p in output.rglob('*') if p.is_file()}

def restore(github, parent_run, index, revision, output, plan_path=PLAN, inventory_path=INVENTORY):
    plan, inventory = work.check_plan(plan_path, inventory_path)
    output = Path(output)
    require(not output.exists() and not output.is_symlink(), 'Restore destination must not exist')
    run, job = binding(github, parent_run, index, terminal=True)
    require(run['head_sha'] == revision, 'Parent and child source revisions must match exactly')
    name = artifact_name(index, run['run_attempt'])
    matches = [a for a in github.rows(f'actions/runs/{parent_run}/artifacts', 'artifacts') if a['name'] == name]
    require(len(matches) == 1, 'Unique artifact from the exact parent attempt required')
    artifact = matches[0]
    require(not artifact['expired'] and artifact['workflow_run']['id'] == parent_run
            and artifact['workflow_run']['head_sha'] == revision
            and datetime.fromisoformat(artifact['created_at']) >= datetime.fromisoformat(job['started_at']),
            'Artifact does not belong to the selected job attempt')
    require(type(artifact['id']) is int and artifact['id'] > 0
            and type(artifact['size_in_bytes']) is int and 0 < artifact['size_in_bytes'] <= MAX_ARCHIVE_BYTES
            and bool(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))),
            'Bounded artifact size and server SHA-256 required')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='marhl-restore-', dir=output.parent) as temporary:
        staging = Path(temporary)
        archive = staging/'download.zip'
        github.download(artifact['id'], archive)
        require(archive.stat().st_size == artifact['size_in_bytes']
                and 'sha256:'+digest(archive) == artifact['digest'], 'Original artifact size or SHA-256 differs')
        members = extract(archive, staging/'payload')
        execution = read(staging/'payload/execution.json')
        expected = {'schema': 1, 'repository': github.repository, 'run_id': parent_run,
                    'run_attempt': run['run_attempt'], 'job_id': job['id'], 'head_sha': revision,
                    'workflow_path': WORKFLOW, 'task_index': index, 'batch': index//plan['batch_size'],
                    'task_count': plan['task_count'], 'plan_sha256': digest(plan_path),
                    'inventory_sha256': work.INVENTORY_SHA256, 'evidence_directory': 'evidence'}
        require(all(execution.get(k) == v for k, v in expected.items()), 'Artifact execution identity differs')
        require(execution.get('source_provenance') == {'source_revision': revision,
                'file_sha256': source_files(), 'implementation_files_differing_from_revision': []},
                'Artifact producer source provenance differs')
        source = staging/'payload/evidence'
        validation = validate_evidence(source, plan, inventory, index)
        if 'finished_at' in execution:
            require(execution['status'] == validation['reported_status'], 'Final execution and task status differ')
        history_path = source/'restore-provenance.json'
        history = read(history_path)['history'] if history_path.exists() else []
        require(isinstance(history, list), 'Invalid checkpoint restoration history')
        provenance = {'restored_at': work.now(), 'repository': github.repository,
                      'parent_run_id': parent_run, 'parent_run_attempt': run['run_attempt'],
                      'parent_job_id': job['id'], 'parent_job_conclusion': job['conclusion'],
                      'parent_revision': revision, 'task_index': index, 'artifact_id': artifact['id'],
                      'archive_sha256': artifact['digest'], 'archive_bytes': artifact['size_in_bytes'],
                      'archived_file_sha256': members, 'validation': validation,
                      'api_snapshots': {'run': run, 'job': job, 'artifact': artifact},
                      'restore_script_sha256': digest(__file__), 'numerical_integrations_performed': 0}
        write_json(history_path, {'history': [*history, provenance]})
        source.rename(output)
    return provenance

def execute(github, run_id, attempt, revision, batch, index, output, *, parent_run=None,
            plan_path=PLAN, inventory_path=INVENTORY):
    """Execute one original task, preserving evidence even when it cannot finish."""
    plan, inventory = work.check_plan(plan_path, inventory_path)
    require(index in select_tasks(plan, batch), 'Task is outside the selected original batch')
    require(parent_run != run_id, 'A run cannot restore itself')
    run, job = binding(github, run_id, index, terminal=False)
    require(run['run_attempt'] == attempt and run['head_sha'] == revision, 'Current GitHub execution identity differs')
    provenance = verify_sources(revision)
    output = Path(output)
    require(not output.exists() and not output.is_symlink(), 'Cloud output must be a new directory')
    output.mkdir(parents=True)
    execution = {'schema': 1, 'repository': github.repository, 'run_id': run_id, 'run_attempt': attempt,
                 'job_id': job['id'], 'head_sha': revision, 'workflow_path': WORKFLOW,
                 'task_index': index, 'batch': batch, 'task_count': plan['task_count'],
                 'plan_sha256': digest(plan_path), 'inventory_sha256': work.INVENTORY_SHA256,
                 'evidence_directory': 'evidence', 'source_provenance': provenance,
                 'started_at': work.now(), 'status': 'restoring' if parent_run else 'running',
                 'requested_parent_run': parent_run, 'max_seconds': 14400.,
                 'case_recovery_claimed': False, 'full_model_coverage_claimed': False}
    write_json(output/'execution.json', execution)
    if parent_run is not None:
        try:
            restore(github, parent_run, index, revision, output/'evidence', plan_path, inventory_path)
        except Exception as error:
            execution.update(status='restore_failed', error=f'{type(error).__name__}: {error}', finished_at=work.now())
            write_json(output/'execution.json', execution)
            raise
    execution['status'] = 'running'
    write_json(output/'execution.json', execution)
    report = work.run_task(plan_path, inventory_path, index, output/'evidence',
                           resume=parent_run is not None, max_seconds=14400.)
    execution.update(status=report['status'], finished_at=work.now(),
                     report_sha256=digest(output/'evidence/report.json'))
    write_json(output/'execution.json', execution)
    return {'task_index': index, 'status': report['status'], 'execution_sha256': digest(output/'execution.json'),
            'report_sha256': execution['report_sha256'], 'case_recovery_claimed': False}
