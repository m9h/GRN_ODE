"""Full Marhl breaking protocols at two precisions in two implementations.

The immutable inventory contains every potential control for all twelve failed
cases. A task is one complete original trajectory in one implementation and
precision; a checkpoint is never counted as a finished trajectory. Independent
array audits compare all six pairs without changing the original acceptance.
Both implementations use Taylor methods; different solver families are not
claimed. Observation arrays use binary64, while restart states retain precision.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
from importlib.metadata import version
import itertools
import json
import math
import os
from pathlib import Path
import platform
import tempfile
import time

import numpy as np
import pandas as pd

from . import marhl_checkpoints, taylor_reference, taylor_checkpoints
from .catalog_breaking import trial_windows
from .catalog_repeated import pulse_schedule, trains_for, summarize
from .catalog_runner import fingerprint
from .catalog_validation import comparison
from .marhl_mpmath import MODEL_SHA256, NAMES
from .native_protocols import ResetTrain, sample_times

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_SHA256 = 'a17f4c58c46e11aa890521874dd2dfb821f40dfacc3446bf0ba695e20afeaa42'
REQUESTS = {
    'taylor128': {'backend': 'heyoka', 'precision': 128, 'tolerance': '1e-30'},
    'taylor192': {'backend': 'heyoka', 'precision': 192, 'tolerance': '1e-45'},
    'mpmath128': {'backend': 'mpmath', 'precision': 128, 'tolerance': '1e-30', 'degree': 32},
    'mpmath192': {'backend': 'mpmath', 'precision': 192, 'tolerance': '1e-45', 'degree': 48},
}
FILES = ('grn_memory/marhl_precision.py', 'grn_memory/marhl_checkpoints.py',
         'grn_memory/marhl_mpmath.py', 'grn_memory/taylor_reference.py',
         'grn_memory/taylor_checkpoints.py', 'grn_memory/native_protocols.py',
         'grn_memory/catalog_repeated.py', 'grn_memory/catalog_validation.py',
         'grn_memory/breaking_scores.py', 'grn_memory/catalog_breaking.py',
         'scripts/prepare_marhl_full_controls.py')

def require(condition, message):
    if not condition:
        raise ValueError(message)

def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            sha.update(block)
    return sha.hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

def now():
    return datetime.now(timezone.utc).isoformat()

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix=path.name+'.', suffix='.tmp', delete=False) as f:
        temporary = Path(f.name)
        json.dump(data, f, indent=2, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def make_plan(inventory_path):
    require(digest(inventory_path) == INVENTORY_SHA256, 'The complete pinned inventory is required')
    inventory = read(inventory_path)
    baseline = inventory['full_untreated_control']
    diagnostics = sorted(set(inventory['diagnostic_branch_ids']) - {baseline})
    branches = [baseline] + diagnostics
    branches += sorted(inventory['branches'].keys() - set(branches))
    require(len(branches) == len(set(branches)) == 380 and len(diagnostics) == 29,
            'All 380 controls and all 29 diagnostic branches are required')
    require(inventory['selected_cases'] == 12 and inventory['model_sha256'] == MODEL_SHA256,
            'Original model and twelve-case scope differ')
    require(inventory['acceptance'] == {'rtol': 2e-5, 'atol': 1e-7}, 'Acceptance differs')
    tasks = len(branches)*len(REQUESTS)
    return {'schema': 1, 'model_id': inventory['model_id'], 'model_sha256': MODEL_SHA256,
            'inventory_sha256': INVENTORY_SHA256, 'branches': branches, 'requests': REQUESTS,
            'task_count': tasks, 'batch_size': 256,
            'batches': [list(range(start, min(tasks, start+256))) for start in range(0, tasks, 256)],
            'diagnostic_priority_tasks': 120, 'remaining_required_tasks': tasks-120,
            'selected_cases': 12, 'observables': NAMES, 'acceptance': inventory['acceptance'],
            'checkpoint_every': 10, 'heyoka_checkpoint_steps': 1_000_000, 'mpmath_max_chunk_span': 1.,
            'sources': {name: digest(ROOT/name) for name in FILES},
            'numerical_integrations_performed': 0, 'case_recovery_claimed': False}

def check_plan(plan_path, inventory_path, *, rebuild_inventory=False):
    if rebuild_inventory:
        from scripts.prepare_marhl_full_controls import check
        check(Path(inventory_path))
    plan = read(plan_path)
    require(plan == make_plan(inventory_path), 'Plan does not reproduce the complete pinned scope and sources')
    require(digest(ROOT/'models/BIOMD0000000039.xml') == MODEL_SHA256, 'Model bytes differ')
    return plan, read(inventory_path)

def problem(plan, inventory, task_index):
    require(type(task_index) is int and 0 <= task_index < plan['task_count'], 'Invalid task index')
    branch_index, request_index = divmod(task_index, len(REQUESTS))
    bid, label = plan['branches'][branch_index], list(REQUESTS)[request_index]
    spec = inventory['branches'][bid]
    require(fingerprint(spec) == bid, 'Branch identity differs from its original specification')
    possible = trains_for(pulse_schedule(), {}) + [ResetTrain(t, t+100., {})
                for t in (1010., 1210., 1410., 1610., 1810., 2010.)]
    full = sample_times(2210., .01, possible, post_reset_offset=1e-5)
    times = full[full <= spec['stop']]
    observations = inventory['branch_observations'][bid]
    require(len(times) == observations['samples'] and
            hashlib.sha256(times.tobytes()).hexdigest() == observations['sample_grid_sha256'],
            'Original complete observation grid differs')
    counts = [len(ResetTrain(**t).indices()) if t['values'] else 0 for t in spec['reset_trains']]
    require(counts == observations['reset_counts'], 'Original reset counts differ')
    return bid, label, spec, times

def runtime(backend):
    packages = ['numpy', 'python-libsbml'] + (['heyoka'] if backend == 'heyoka' else ['mpmath'])
    return {'python': platform.python_version(), 'system': platform.system(), 'machine': platform.machine(),
            'packages': {name: version(name) for name in packages}}

def identity(plan, bid, label, spec, times, task_index, environment):
    return {'schema': 1, 'plan_sha256': fingerprint(plan), 'inventory_sha256': plan['inventory_sha256'],
            'task_index': task_index, 'branch_id': bid, 'request_label': label,
            'request': REQUESTS[label], 'specification': spec, 'model_sha256': MODEL_SHA256,
            'sample_grid_sha256': hashlib.sha256(times.tobytes()).hexdigest(),
            'sample_count': len(times), 'observables': NAMES, 'sources': plan['sources'],
            'runtime': environment}

def validate_integration(evidence, request, times, trains):
    _, events, counts, edges, chunks = marhl_checkpoints.protocol(times, trains, 1.)
    require(evidence.get('completed') is True and evidence.get('model_sha256') == MODEL_SHA256,
            'Completed integration of the original model is required')
    require(evidence.get('precision_bits') == request['precision'] and
            float(evidence.get('tolerance', 'nan')) == float(request['tolerance']) and
            evidence.get('numeric_inputs') == 'binary64 values promoted exactly' and
            evidence.get('absolute_time_preserved') is True and evidence.get('observables') == NAMES,
            'Integration precision, clock or observable identity differs')
    expected = {'sample_count': len(times), 'expected_resets': len(events), 'performed_resets': len(events),
                'expected_segments': len(edges)-1, 'completed_segments': len(edges)-1}
    for name, value in expected.items():
        require(type(evidence.get(name)) is int and evidence[name] == value, 'Incomplete protocol counter: '+name)
    for name in ('expected_train_reset_counts', 'train_reset_counts'):
        require(evidence.get(name) == counts and all(type(n) is int for n in evidence[name]),
                'Per-train reset counts differ')
    require(evidence.get('last_interval', [None, None])[-1] == float(times[-1]), 'Original horizon was not reached')
    if request['backend'] == 'mpmath':
        require(evidence.get('backend') == 'mpmath.odefun' and evidence.get('degree') == request['degree']
                and evidence.get('expected_chunks') == evidence.get('completed_chunks') == len(chunks)-1
                and evidence.get('rhs_evaluations', 0) > 0, 'Incomplete mpmath computation')
    else:
        require(evidence.get('high_accuracy') is True and evidence.get('integration_steps', 0) > 0,
                'Incomplete Heyoka computation')

@contextmanager
def task_lock(output):
    output.mkdir(parents=True, exist_ok=True)
    require(not output.is_symlink(), 'Task output must be a regular directory')
    with (output/'.task.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield

def save_trace(path, times, names, values):
    require(names == NAMES and np.asarray(values).shape == (len(times), len(NAMES))
            and np.isfinite(values).all(), 'Complete finite model observations are required')
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+'.', suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        np.savez_compressed(stream, times=times, observables=np.asarray(names), values=np.asarray(values, dtype=np.float64))
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def load_trace(output, report, times, request, trains):
    require(report.get('status') == 'completed', 'A partial task is not a complete trajectory')
    validate_integration(report['integration'], request, times, trains)
    trace = report['trace']
    require(trace['file'] == 'trajectory.npz' and not (output/trace['file']).is_symlink(), 'Unexpected trajectory path')
    require(digest(output/trace['file']) == trace['sha256'], 'Trajectory digest differs')
    with np.load(output/trace['file'], allow_pickle=False) as z:
        require(set(z.files) == {'times', 'observables', 'values'}, 'Trajectory member inventory differs')
        values, saved_times = z['values'].copy(), z['times'].copy()
        require(z['observables'].tolist() == NAMES and saved_times.dtype == values.dtype == np.float64
                and np.array_equal(saved_times, times) and values.shape == (len(times), len(NAMES))
                and np.isfinite(values).all(), 'Complete original finite observation grid is required')
    checkpoint = output/'checkpoint.npz'
    require(not checkpoint.is_symlink() and digest(checkpoint) == report['checkpoint_sha256'],
            'Final exact-state checkpoint is missing or changed')
    with np.load(checkpoint, allow_pickle=False) as z:
        require(set(z.files) == {'metadata', 'observations'}, 'Checkpoint member inventory differs')
        metadata, observed = json.loads(str(z['metadata'])), z['observations'].copy()
    checksum = metadata.pop('payload_sha256')
    require(fingerprint(metadata) == checksum and fingerprint(metadata['identity']) == metadata['identity_sha256'],
            'Checkpoint metadata checksum differs')
    require(hashlib.sha256(observed.tobytes()).hexdigest() == metadata['observations_sha256']
            and observed.dtype == np.float64 and np.array_equal(observed, values),
            'Final checkpoint observations differ from the complete trajectory')
    validate_integration(metadata['evidence'], request, times, trains)
    ci = metadata['identity']
    sources = report['identity']['sources']
    require(ci['model_sha256'] == MODEL_SHA256 and ci['trains'] == trains and ci['observables'] == NAMES,
            'Checkpoint model or protocol differs')
    grid_sha = hashlib.sha256(times.tobytes()).hexdigest()
    if request['backend'] == 'mpmath':
        require(metadata['schema'] == 1 and ci['precision'] == request['precision']
                and ci['sample_grid_sha256'] == grid_sha and ci['max_chunk_span'] == 1.
                and ci['implementation_sha256'] == {'adapter': sources['grn_memory/marhl_checkpoints.py'],
                    'equations': sources['grn_memory/marhl_mpmath.py']}, 'mpmath checkpoint source or grid differs')
    else:
        require(metadata['schema'] == 2 and ci['precision_bits'] == request['precision']
                and ci['times_sha256'] == grid_sha and ci['samples'] == len(times)
                and ci['checkpoint_steps'] == 1_000_000
                and ci['sources'] == {'adapter': sources['grn_memory/taylor_reference.py'],
                    'checkpoints': sources['grn_memory/taylor_checkpoints.py']}, 'Heyoka checkpoint source or grid differs')
    return values

def run_task(plan_path, inventory_path, task_index, output, *, resume=False, max_seconds=14400.):
    require(math.isfinite(max_seconds) and max_seconds > 0, 'Positive finite task budget required')
    plan, inventory = check_plan(plan_path, inventory_path)
    bid, label, spec, times = problem(plan, inventory, task_index)
    request = REQUESTS[label]
    expected = identity(plan, bid, label, spec, times, task_index, runtime(request['backend']))
    output = Path(output)
    with task_lock(output):
        destination, checkpoint = output/'report.json', output/'checkpoint.npz'
        require(destination.exists() == resume, 'Existing task reports require explicit resume')
        require(not destination.is_symlink() and not checkpoint.is_symlink(), 'Regular task evidence required')
        if resume:
            report = read(destination)
            require(report.get('identity') == expected and report.get('fingerprint') == fingerprint(expected),
                    'Task, original protocol, source or runtime changed on resume')
            if report['status'] != 'running' and report.get('checkpoint_sha256') is not None:
                require(checkpoint.is_file() and digest(checkpoint) == report['checkpoint_sha256'],
                        'Recorded restart checkpoint was changed')
            if report['status'] == 'completed':
                load_trace(output, report, times, request, spec['reset_trains'])
                return report
        else:
            require(not checkpoint.exists() and not (output/'trajectory.npz').exists(), 'Unbound previous task files')
            report = {'identity': expected, 'fingerprint': fingerprint(expected), 'attempts': [],
                      'status': 'running', 'case_recovery_claimed': False, 'full_model_coverage_claimed': False}
        report.pop('error', None)
        report.pop('interruption', None)
        report.update(status='running', integration={}, trace=None)
        attempt = {'started_at': now(), 'resume': resume, 'max_seconds': max_seconds,
                   'parent_checkpoint_sha256': digest(checkpoint) if checkpoint.exists() else None}
        report['attempts'].append(attempt)
        write_json(destination, report)
        backend = request['backend']
        function = taylor_reference.taylor_trajectory if backend == 'heyoka' else marhl_checkpoints.trajectory
        kwargs = {k: v for k, v in request.items() if k != 'backend'}
        kwargs.update(checkpoint=checkpoint, resume=checkpoint.exists(), checkpoint_every=plan['checkpoint_every'],
                      max_seconds=max_seconds, evidence=report['integration'])
        if backend == 'heyoka':
            kwargs['checkpoint_steps'] = plan['heyoka_checkpoint_steps']
        else:
            kwargs['max_chunk_span'] = plan['mpmath_max_chunk_span']
        began = time.monotonic()
        try:
            names, values = function(ROOT/'models/BIOMD0000000039.xml', times, spec['reset_trains'], **kwargs)
            validate_integration(report['integration'], request, times, spec['reset_trains'])
            require(checkpoint.is_file(), 'Final exact-state checkpoint is required')
            save_trace(output/'trajectory.npz', times, names, values)
            report.update(status='completed', trace={'file': 'trajectory.npz', 'sha256': digest(output/'trajectory.npz')})
        except (marhl_checkpoints.MarhlCheckpointStop, taylor_checkpoints.TaylorCheckpointStop) as error:
            require(checkpoint.is_file(), 'Budget stop did not save a checkpoint')
            report.update(status='checkpointed', interruption=str(error))
        except Exception as error:
            report.update(status='integration_failed', error=f'{type(error).__name__}: {error}')
        report['checkpoint_sha256'] = digest(checkpoint) if checkpoint.exists() else None
        attempt.update(finished_at=now(), elapsed_seconds=time.monotonic()-began, status=report['status'],
                       checkpoint_sha256=report['checkpoint_sha256'])
        if report.get('error'):
            attempt['error'] = report['error']
        if report.get('interruption'):
            attempt['interruption'] = report['interruption']
        write_json(destination, report)
        return report

def audit_branch(plan_path, inventory_path, branch_id, directories):
    plan, inventory = check_plan(plan_path, inventory_path)
    require(branch_id in plan['branches'] and len(directories) == len(REQUESTS), 'Exactly four selected task directories required')
    frames, reports, windows = {}, {}, {}
    for directory in map(Path, directories):
        require(not directory.is_symlink(), 'Regular evidence directory required')
        report = read(directory/'report.json')
        actual = report['identity']
        bid, label, spec, times = problem(plan, inventory, actual['task_index'])
        expected = identity(plan, bid, label, spec, times, actual['task_index'], actual['runtime'])
        require(bid == branch_id and label not in frames and actual == expected
                and report['fingerprint'] == fingerprint(expected), 'Mismatched or duplicate task identity')
        values = load_trace(directory, report, times, REQUESTS[label], spec['reset_trains'])
        frame = pd.DataFrame(values, columns=NAMES)
        frame.insert(0, 'time', times)
        frames[label] = frame
        windows[label] = summarize(frame, trial_windows(round((spec['stop']-1010.)/400)))
        reports[label] = {'report_sha256': digest(directory/'report.json'), 'trace': report['trace'],
                          'checkpoint_sha256': report['checkpoint_sha256'], 'runtime': actual['runtime']}
    require(set(frames) == set(REQUESTS), 'Both implementations and both precisions are required')
    comparisons = {a+'_vs_'+b: comparison(frames[a], frames[b], **plan['acceptance'])
                   for a, b in itertools.combinations(REQUESTS, 2)}
    passed = all(c['passed'] for c in comparisons.values())
    return {'schema': 1, 'plan_sha256': fingerprint(plan), 'inventory_sha256': INVENTORY_SHA256,
            'branch_id': branch_id, 'original_specification': spec, 'samples': len(times),
            'observables': NAMES, 'verified_arrays': 4, 'reports': reports, 'comparisons': comparisons,
            'windows': windows, 'acceptance': plan['acceptance'], 'status': 'agreement' if passed else 'mismatch',
            'high_precision_agreement': passed, 'full_grid_compared': True,
            'different_integrator_family_claimed': False, 'internal_states_compared': False,
            'case_recovery_claimed': False, 'full_model_coverage_claimed': False,
            'numerical_integrations_performed': 0}
