"""Resumable mpmath reference for the complete Marhl breaking protocols.

The original independent equations and binary64 inputs are unchanged. Fixed
integration chunks bound lost work; their endpoints are not physical resets or
new observations. Internal state is saved with verified exact decimal round trips.
Only observations are rounded to binary64. No pickle or executable state is used.
"""

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import tempfile
import time

import numpy as np

from . import marhl_mpmath as reference


class MarhlCheckpointStop(RuntimeError):
    """The requested budget ended after an exact checkpoint was saved."""


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def protocol(times, trains, max_chunk_span):
    times = np.asarray(times, dtype=np.float64)
    if (times.ndim != 1 or len(times) < 2 or times[0] != 0
            or not np.isfinite(times).all() or np.any(np.diff(times) <= 0)):
        raise ValueError('Finite increasing observation times must start at zero')
    if not math.isfinite(max_chunk_span) or max_chunk_span <= 0:
        raise ValueError('Positive finite chunk span required')
    events, counts = {}, []
    for index, train in enumerate(trains):
        start, stop, interval = train['start'], train['stop'], train.get('interval', .1)
        if (not np.isfinite([start, stop, interval]).all() or start < 0 or stop <= start
                or stop > times[-1] or interval <= 0):
            raise ValueError('Invalid reset interval')
        if any(type(train.get(key, False)) is not bool for key in ('include_start', 'include_stop')):
            raise ValueError('Reset endpoint flags must be booleans')
        n = round((stop-start)/interval)
        if n < 1 or not np.isclose(n*interval, stop-start, rtol=0, atol=1e-9):
            raise ValueError('Reset duration must be an integer multiple of interval')
        values = train['values']
        if set(values)-set(reference.NAMES) or any(not math.isfinite(v) or v < 0 for v in values.values()):
            raise ValueError('Only model species can receive finite nonnegative resets')
        indices = range(0 if train.get('include_start', False) else 1,
                        n+int(train.get('include_stop', False)))
        counts.append(len(indices) if values else 0)
        if not values:
            continue
        for when in start+np.asarray(list(indices))*interval:
            event = events.setdefault(float(when), {'values': {}, 'trains': []})
            if set(event['values']) & values.keys():
                raise ValueError('Conflicting simultaneous resets')
            event['values'].update(values)
            event['trains'].append(index)
    resets = np.asarray(sorted(events), dtype=np.float64)
    if len(resets):
        if resets[0] <= 0 or resets[-1] >= times[-1] or np.any(np.diff(resets) <= 1e-10):
            raise ValueError('Distinct resets strictly inside the observation window are required')
        positions = np.searchsorted(times, resets)
        if np.any(np.minimum(abs(times[positions]-resets), abs(times[positions-1]-resets)) <= 1e-10):
            raise ValueError('Samples must avoid ambiguous reset instants')
    edges = np.r_[0., resets, times[-1]]
    chunks = [0.]
    for start, end in zip(edges[:-1], edges[1:]):
        # Keep every physical endpoint exact; subdivide only within its interval.
        count = max(1, math.ceil((end-start)/max_chunk_span))
        chunks.extend(np.linspace(start, end, count+1)[1:])
    chunks = np.asarray(chunks, dtype=np.float64)
    if not np.isfinite(chunks).all() or np.any(np.diff(chunks) <= 0):
        raise ValueError('Chunk boundaries must be distinct and increasing')
    return times, events, counts, edges, chunks


def encode_state(context, state):
    digits = math.ceil(context.prec * math.log10(2)) + 10
    encoded = [context.nstr(v, digits, strip_zeros=False) for v in state]
    if any(not context.isfinite(v) or context.mpf(s) != v for s, v in zip(encoded, state)):
        raise ValueError('Decimal checkpoint does not preserve exact internal state')
    return encoded


@contextmanager
def checkpoint_lock(path, resume):
    if path is None:
        if resume:
            raise ValueError('Resume requires a checkpoint path')
        yield
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('Checkpoint must be a regular file')
    with path.with_name(path.name+'.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists() != resume:
            raise ValueError('Existing checkpoints require explicit resume; resume requires an existing checkpoint')
        yield


def save(path, identity, context, state, observations, evidence):
    observations = np.asarray(observations, dtype=np.float64)
    if not np.isfinite(observations).all():
        raise ValueError('Checkpoint observations must be finite')
    metadata = {'schema': 1, 'identity': identity, 'identity_sha256': signature(identity),
                'state': encode_state(context, state), 'evidence': evidence,
                'observations_sha256': hashlib.sha256(observations.tobytes()).hexdigest()}
    metadata['payload_sha256'] = signature(metadata)
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+'.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            np.savez_compressed(stream, metadata=np.asarray(json.dumps(metadata, sort_keys=True, allow_nan=False)),
                                observations=observations)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def counters(end, events, counts, edges, chunks):
    reached = [when for when in events if when < end]
    segments = int(np.searchsorted(edges, end, side='right')-1)
    k = int(np.searchsorted(chunks, end))
    return {'completed_chunks': k, 'completed_segments': segments,
            'performed_resets': len(reached),
            'train_reset_counts': [sum(i in events[t]['trains'] for t in reached) for i in range(len(counts))],
            'last_chunk': [float(chunks[k-1]), float(end)],
            'last_interval': [float(edges[segments-1]), float(edges[segments])] if segments else None,
            'completed': bool(end == edges[-1])}


def load(path, identity, context, times, events, counts, edges, chunks, base):
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != {'metadata', 'observations'}:
            raise ValueError('Checkpoint member inventory differs')
        metadata = json.loads(str(archive['metadata']))
        observations = archive['observations'].copy()
    checksum = metadata.pop('payload_sha256')
    if (signature(metadata) != checksum or metadata['schema'] != 1
            or metadata['identity'] != identity or metadata['identity_sha256'] != signature(identity)):
        raise ValueError('Checkpoint identity or metadata checksum differs')
    evidence = metadata['evidence']
    k = evidence['completed_chunks']
    if type(k) is not int or not 1 <= k < len(chunks):
        raise ValueError('Invalid checkpoint chunk count')
    expected = counters(chunks[k], events, counts, edges, chunks)
    mutable = set(expected) | {'rhs_evaluations'}
    if (set(evidence) != set(base) | mutable
            or any(evidence.get(key) != value for key, value in base.items() if key not in mutable)
            or any(evidence.get(key) != value for key, value in expected.items())
            or type(evidence['rhs_evaluations']) is not int or evidence['rhs_evaluations'] < 0):
        raise ValueError('Checkpoint protocol counters or integration evidence differ')
    if (type(evidence['completed']) is not bool
            or any(type(evidence[key]) is not int for key in ('performed_resets', 'completed_segments'))
            or any(type(v) is not int for v in evidence['train_reset_counts'])):
        raise ValueError('Checkpoint counter types differ')
    last = int(np.searchsorted(times, chunks[k], side='right' if expected['completed'] else 'left'))
    if (observations.dtype != np.float64 or observations.shape != (last, len(reference.NAMES))
            or not np.isfinite(observations).all()
            or hashlib.sha256(observations.tobytes()).hexdigest() != metadata['observations_sha256']):
        raise ValueError('Checkpoint observation prefix differs')
    encoded = metadata['state']
    if not isinstance(encoded, list) or len(encoded) != len(reference.NAMES) or not all(isinstance(s, str) for s in encoded):
        raise ValueError('Checkpoint internal state is incomplete')
    state = [context.mpf(s) for s in encoded]
    if encode_state(context, state) != encoded:
        raise ValueError('Checkpoint state is not a canonical exact round trip')
    return state, observations, evidence


def trajectory(path, times, trains=(), *, precision=128, tolerance='1e-30', degree=32,
               max_chunk_span=1., checkpoint=None, resume=False, checkpoint_every=10,
               stop_after_chunks=None, max_seconds=None, evidence=None, progress=None):
    """Integrate the full supplied grid, or save exact state before a budget stop.

Uninterrupted and resumed execution use the same fixed integration chunks.
The time budget is cooperative: a single mpmath chunk must return before it
can be checked. An external termination can lose work since the last save.
"""
    import mpmath
    if digest(path) != reference.MODEL_SHA256:
        raise ValueError('The independently transcribed equations require the original BioModel 39')
    if type(precision) is not int or precision < 64 or type(degree) is not int or degree < 4:
        raise ValueError('Require at least 64 precision bits and Taylor degree at least four')
    if type(checkpoint_every) is not int or checkpoint_every < 1:
        raise ValueError('Positive integer checkpoint interval required')
    if stop_after_chunks is not None and (type(stop_after_chunks) is not int or stop_after_chunks < 1):
        raise ValueError('Positive integer stopping chunk count required')
    if max_seconds is not None and (not math.isfinite(max_seconds) or max_seconds <= 0):
        raise ValueError('Positive finite time budget required')
    if checkpoint is None and (stop_after_chunks is not None or max_seconds is not None):
        raise ValueError('A cooperative stop requires a checkpoint')
    context = mpmath.mp.clone()
    context.prec = precision
    tolerance_value = context.mpf(tolerance)
    if not context.isfinite(tolerance_value) or tolerance_value <= 0:
        raise ValueError('Positive finite truncation tolerance required')
    trains = deepcopy(list(trains))
    times, events, counts, edges, chunks = protocol(times, trains, max_chunk_span)
    base = {'model_sha256': reference.MODEL_SHA256, 'backend': 'mpmath.odefun',
            'mpmath_version': mpmath.__version__, 'precision_bits': precision,
            'tolerance': str(tolerance_value), 'degree': degree,
            'numeric_inputs': 'binary64 values promoted exactly', 'absolute_time_preserved': True,
            'expected_resets': len(events), 'expected_train_reset_counts': counts,
            'expected_segments': len(edges)-1, 'expected_chunks': len(chunks)-1,
            'sample_count': len(times), 'observables': reference.NAMES.copy(),
            'completed': False, 'rhs_evaluations': 0}
    identity = {'model_sha256': reference.MODEL_SHA256, 'precision': precision,
                'tolerance': str(tolerance_value), 'degree': degree, 'trains': trains,
                'sample_grid_sha256': hashlib.sha256(times.tobytes()).hexdigest(),
                'chunk_grid_sha256': hashlib.sha256(chunks.tobytes()).hexdigest(),
                'max_chunk_span': float(max_chunk_span), 'observables': reference.NAMES.copy(),
                'implementation_sha256': {'adapter': digest(__file__), 'equations': digest(reference.__file__)},
                'runtime': {'python': platform.python_version(), 'system': platform.system(),
                            'machine': platform.machine(), 'mpmath': mpmath.__version__,
                            'numpy': np.__version__, 'mpmath_backend': mpmath.libmp.BACKEND}}
    with checkpoint_lock(checkpoint, resume):
        supplied = {} if evidence is None else evidence
        evidence = dict(base, performed_resets=0, train_reset_counts=[0]*len(counts),
                        completed_chunks=0, completed_segments=0, last_chunk=None, last_interval=None)
        raw_rhs, state = reference.equations(context)
        values = np.full((len(times), len(reference.NAMES)), np.nan)
        completed = 0
        if resume:
            state, observed, saved = load(checkpoint, identity, context, times, events, counts, edges, chunks, base)
            evidence.update(saved)
            completed = saved['completed_chunks']
            values[:len(observed)] = observed
        supplied.update(evidence)
        def rhs(t, y):
            evidence['rhs_evaluations'] += 1
            return raw_rhs(t, y)
        positions = {name: i for i, name in enumerate(reference.NAMES)}
        began, executed = time.monotonic(), 0
        for k in range(completed, len(chunks)-1):
            start, end = float(chunks[k]), float(chunks[k+1])
            if start in events:
                for name, value in events[start]['values'].items():
                    state[positions[name]] = context.mpf(float(value))
                evidence['performed_resets'] += 1
                for index in events[start]['trains']:
                    evidence['train_reset_counts'][index] += 1
            solution = context.odefun(rhs, context.mpf(start), state, tol=tolerance_value, degree=degree)
            first = int(np.searchsorted(times, start))
            last = int(np.searchsorted(times, end, side='right' if end == times[-1] else 'left'))
            for i in range(first, last):
                values[i] = [float(v) for v in solution(context.mpf(float(times[i])))]
            state = list(solution(context.mpf(end)))
            if not all(context.isfinite(v) for v in state) or not np.isfinite(values[first:last]).all():
                raise RuntimeError('Nonfinite internal state or observation')
            segments = int(np.searchsorted(edges, end, side='right')-1)
            evidence.update(completed_chunks=k+1, completed_segments=segments,
                            last_chunk=[start, end], completed=bool(end == times[-1]),
                            last_interval=[float(edges[segments-1]), float(edges[segments])] if segments else None)
            supplied.update(evidence)
            executed += 1
            stopping = ((stop_after_chunks is not None and executed >= stop_after_chunks)
                        or (max_seconds is not None and time.monotonic()-began >= max_seconds))
            if checkpoint is not None and (stopping or evidence['completed'] or (k+1) % checkpoint_every == 0):
                save(checkpoint, identity, context, state, values[:last], evidence)
            if progress is not None:
                progress(supplied)
            if stopping and not evidence['completed']:
                raise MarhlCheckpointStop(f'Saved exact mpmath checkpoint after chunk {k+1} at time {end}')
        if (not np.isfinite(values).all() or not evidence.get('completed')
                or evidence['performed_resets'] != len(events) or evidence['train_reset_counts'] != counts):
            raise RuntimeError('The complete trajectory and every reset are required')
        return reference.NAMES.copy(), values
