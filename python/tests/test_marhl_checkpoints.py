"""Exact restart, independent solutions, source identity and damaged evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import mpmath
import numpy as np
import pytest

from grn_memory import marhl_checkpoints as adapter


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / 'models/BIOMD0000000039.xml'
TIMES = np.array([0., .09999, .10001, .29999, .30001, .50001, .75, 1.])
TRAINS = [{'start': .1, 'stop': .5, 'interval': .2, 'include_start': True,
           'include_stop': True, 'values': {'Ca_cyt': 10.}}]


@pytest.fixture
def analytic(monkeypatch):
    def equations(context):
        # The last constant contains information that binary64 cannot retain.
        tiny = context.mpf(1) + context.mpf(2)**(-context.prec+5)
        return lambda t, y: [t, t*t, 0, 0, 0], [context.mpf(v) for v in (0, 0, 3, 4, tiny)]
    monkeypatch.setattr(adapter.reference, 'equations', equations)


def unpack(path):
    with np.load(path, allow_pickle=False) as a:
        return json.loads(str(a['metadata'])), a['observations'].copy()


def repack(path, metadata, observations, *, repair_payload=True, repair_observations=False):
    if repair_observations:
        metadata['observations_sha256'] = hashlib.sha256(observations.tobytes()).hexdigest()
    if repair_payload:
        metadata.pop('payload_sha256', None)
        metadata['payload_sha256'] = adapter.signature(metadata)
    with path.open('wb') as f:
        np.savez_compressed(f, metadata=np.asarray(json.dumps(metadata)), observations=observations)


@pytest.mark.parametrize('precision,tolerance,degree', [(128, '1e-30', 32), (192, '1e-45', 48)])
@pytest.mark.parametrize('stop', [1, 2, 3, 5])
def test_resume_matches_uninterrupted_and_analytic_solution(analytic, tmp_path, precision, tolerance, degree, stop):
    args = dict(precision=precision, tolerance=tolerance, degree=degree, max_chunk_span=.11)
    before = mpmath.mp.prec
    full_evidence = {}
    names, full = adapter.trajectory(MODEL, TIMES, TRAINS, evidence=full_evidence, **args)
    path = tmp_path / 'state.npz'
    evidence = {'request': deepcopy(args)}
    with pytest.raises(adapter.MarhlCheckpointStop):
        adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=path, stop_after_chunks=stop, evidence=evidence, **args)
    meta, saved = unpack(path)
    ctx = mpmath.mp.clone(); ctx.prec = precision
    assert ctx.mpf(meta['state'][4]) != ctx.mpf(float(meta['state'][4]))
    assert evidence['request'] == args and not evidence['completed']
    _, resumed = adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=path, resume=True, evidence=evidence, **args)
    np.testing.assert_array_equal(resumed, full)
    np.testing.assert_array_equal(resumed[:len(saved)], saved)
    assert names == adapter.reference.NAMES and mpmath.mp.prec == before
    assert evidence['completed'] and evidence['performed_resets'] == 3
    assert evidence['train_reset_counts'] == [3] and evidence['completed_segments'] == 4
    assert evidence['rhs_evaluations'] == full_evidence['rhs_evaluations']
    expected = [t*t/2 if t < .1 else 10+(t*t-(.1 if t < .3 else .3 if t < .5 else .5)**2)/2 for t in TIMES]
    np.testing.assert_allclose(resumed[:, 0], expected, rtol=0, atol=1e-13)
    np.testing.assert_allclose(resumed[:, 1], TIMES**3/3, rtol=0, atol=1e-13)
    np.testing.assert_array_equal(resumed[:, 2:], np.tile([3., 4., 1.], (len(TIMES), 1)))
    archive_sha = adapter.digest(path)
    _, again = adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=path, resume=True, **args)
    np.testing.assert_array_equal(again, full)
    assert adapter.digest(path) == archive_sha


def test_repeated_restarts_and_simultaneous_disjoint_resets(analytic, tmp_path):
    trains = deepcopy(TRAINS) + [{**TRAINS[0], 'values': {'CaER': 7.}},
                               {'start': 0., 'stop': .5, 'values': {}}]
    path, evidence = tmp_path/'state.npz', {}
    _, expected = adapter.trajectory(MODEL, TIMES, trains, max_chunk_span=.11)
    for i in range(20):
        try:
            _, result = adapter.trajectory(MODEL, TIMES, trains, max_chunk_span=.11,
                checkpoint=path, resume=i > 0, stop_after_chunks=1, evidence=evidence)
            break
        except adapter.MarhlCheckpointStop:
            continue
    else:
        pytest.fail('Did not finish the original full grid')
    np.testing.assert_array_equal(result, expected)
    assert evidence['performed_resets'] == 3 and evidence['train_reset_counts'] == [3, 3, 0]


@pytest.mark.parametrize('change', ['precision', 'tolerance', 'degree', 'chunks', 'times', 'resets', 'source', 'runtime'])
def test_resume_rejects_changed_science_or_runtime(analytic, tmp_path, monkeypatch, change):
    path = tmp_path/'state.npz'
    with pytest.raises(adapter.MarhlCheckpointStop):
        adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=path, max_chunk_span=.11, stop_after_chunks=2)
    args = {'max_chunk_span': .11}
    times, trains = TIMES.copy(), deepcopy(TRAINS)
    if change == 'precision': args['precision'] = 192
    elif change == 'tolerance': args['tolerance'] = '1e-29'
    elif change == 'degree': args['degree'] = 48
    elif change == 'chunks': args['max_chunk_span'] = .2
    elif change == 'times': times[1] = .09998
    elif change == 'resets': trains[0]['values']['Ca_cyt'] = 11.
    elif change == 'source':
        original = adapter.digest
        monkeypatch.setattr(adapter, 'digest', lambda p: 'changed' if str(p) == adapter.__file__ else original(p))
    elif change == 'runtime': monkeypatch.setattr(adapter.platform, 'python_version', lambda: 'different')
    with pytest.raises(ValueError, match='identity'):
        adapter.trajectory(MODEL, times, trains, checkpoint=path, resume=True, **args)


@pytest.mark.parametrize('change', ['metadata_checksum', 'array_byte', 'array_size', 'array_dtype', 'array_nonfinite',
                                   'resets', 'per_train', 'segments', 'chunks', 'completed', 'last_interval',
                                   'last_chunk', 'rhs', 'state_size', 'state_nonfinite', 'state_noncanonical'])
def test_damaged_or_inconsistent_checkpoints_are_rejected(analytic, tmp_path, change):
    path = tmp_path/'state.npz'
    with pytest.raises(adapter.MarhlCheckpointStop):
        adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=path, max_chunk_span=.11, stop_after_chunks=2)
    meta, observations = unpack(path)
    fix_payload, fix_observations = True, False
    if change == 'metadata_checksum': meta['evidence']['performed_resets'] += 1; fix_payload = False
    elif change == 'array_byte': observations[0, 0] += 1
    elif change == 'array_size': observations = observations[:-1]; fix_observations = True
    elif change == 'array_dtype': observations = observations.astype(np.float32); fix_observations = True
    elif change == 'array_nonfinite': observations[0, 0] = np.nan; fix_observations = True
    elif change == 'resets': meta['evidence']['performed_resets'] += 1
    elif change == 'per_train': meta['evidence']['train_reset_counts'] = [0]
    elif change == 'segments': meta['evidence']['completed_segments'] += 1
    elif change == 'chunks': meta['evidence']['completed_chunks'] = 0
    elif change == 'completed': meta['evidence']['completed'] = True
    elif change == 'last_interval': meta['evidence']['last_interval'] = [0, .2]
    elif change == 'last_chunk': meta['evidence']['last_chunk'] = [0, .2]
    elif change == 'rhs': meta['evidence']['rhs_evaluations'] = -1
    elif change == 'state_size': meta['state'].pop()
    elif change == 'state_nonfinite': meta['state'][0] = 'nan'
    elif change == 'state_noncanonical': meta['state'][0] = '0'
    repack(path, meta, observations, repair_payload=fix_payload, repair_observations=fix_observations)
    with pytest.raises(ValueError):
        adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=path, resume=True, max_chunk_span=.11)


def test_atomic_write_failure_preserves_previous_checkpoint(analytic, tmp_path, monkeypatch):
    path = tmp_path/'state.npz'
    with pytest.raises(adapter.MarhlCheckpointStop):
        adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=path, max_chunk_span=.11, stop_after_chunks=1)
    previous = path.read_bytes()
    def fail(*args): raise OSError('simulated atomic replacement failure')
    monkeypatch.setattr(adapter.os, 'replace', fail)
    with pytest.raises(OSError, match='simulated'):
        adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=path, resume=True, max_chunk_span=.11, stop_after_chunks=1)
    assert path.read_bytes() == previous and not list(tmp_path.glob('*.tmp'))


def test_budget_stop_lock_and_existing_path_rules(analytic, tmp_path, monkeypatch):
    path = tmp_path/'state.npz'
    tick = iter([0., 2.])
    monkeypatch.setattr(adapter.time, 'monotonic', lambda: next(tick))
    with pytest.raises(adapter.MarhlCheckpointStop):
        adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=path, max_chunk_span=.11, max_seconds=1.)
    assert unpack(path)[0]['evidence']['completed_chunks'] == 1
    with pytest.raises(ValueError, match='explicit resume'):
        adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=path)
    with adapter.checkpoint_lock(path, True):
        with pytest.raises(BlockingIOError):
            adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=path, resume=True)
    with pytest.raises(ValueError, match='existing checkpoint'):
        adapter.trajectory(MODEL, TIMES, TRAINS, checkpoint=tmp_path/'missing.npz', resume=True)


@pytest.mark.parametrize('precision,tolerance,degree', [(128, '1e-30', 32), (192, '1e-45', 48)])
def test_real_marhl_state_matches_uninterrupted_original_and_published_baseline(tmp_path, precision, tolerance, degree):
    times = np.arange(11, dtype=float)*.01
    args = dict(precision=precision, tolerance=tolerance, degree=degree)
    _, original = adapter.reference.trajectory(MODEL, times, **args)
    path = tmp_path/'state.npz'
    with pytest.raises(adapter.MarhlCheckpointStop):
        adapter.trajectory(MODEL, times, checkpoint=path, max_chunk_span=.03, stop_after_chunks=1, **args)
    _, resumed = adapter.trajectory(MODEL, times, checkpoint=path, resume=True, max_chunk_span=.03, **args)
    np.testing.assert_allclose(resumed, original, rtol=1e-13, atol=1e-13)
    with np.load(ROOT/'results/catalog-paired-taylor-marhl/untreated_baseline-taylor192.npz') as saved:
        np.testing.assert_allclose(resumed, saved['values'][:len(times)], rtol=1e-13, atol=1e-13)
    c, e, m, b, p = resumed.T
    np.testing.assert_allclose(c+4*e+4*m+b, c[0]+4*e[0]+4*m[0]+b[0], rtol=0, atol=1e-13)
    np.testing.assert_allclose(b+p, 120., rtol=0, atol=1e-13)


def test_all_380_breaking_protocols_preserve_full_grid_and_reset_counts():
    inventory = json.loads((ROOT/'results/catalog-breaking-marhl-full-controls-20261118/inventory.json').read_text())
    from grn_memory.catalog_repeated import pulse_schedule, trains_for
    from grn_memory.native_protocols import ResetTrain, sample_times
    possible = trains_for(pulse_schedule(), {}) + [ResetTrain(t, t+100., {}) for t in (1010.,1210.,1410.,1610.,1810.,2010.)]
    grid = sample_times(2210., .01, possible, post_reset_offset=1e-5)
    for bid, spec in inventory['branches'].items():
        times, events, counts, edges, chunks = adapter.protocol(grid[grid <= spec['stop']], spec['reset_trains'], 1.)
        expected = inventory['branch_observations'][bid]
        assert len(times) == expected['samples'] and counts == expected['reset_counts']
        assert hashlib.sha256(times.tobytes()).hexdigest() == expected['sample_grid_sha256']
        assert set(edges) <= set(chunks) and chunks[0] == 0 and chunks[-1] == spec['stop']
        assert max(np.diff(chunks)) <= 1. + 1e-12
    assert len(inventory['branches']) == 380


@pytest.mark.parametrize('precision,tolerance,degree', [(128, '1e-30', 32), (192, '1e-45', 48)])
def test_real_reset_resume_matches_original_without_resetting_other_coordinates(tmp_path, precision, tolerance, degree):
    times = np.array([0., .04999, .05001, .1, .14999, .15001, .2])
    trains = [{'start': .05, 'stop': .15, 'interval': .1, 'include_start': True,
               'include_stop': True, 'values': {'CaM': .45}}]
    args = dict(precision=precision, tolerance=tolerance, degree=degree)
    _, original = adapter.reference.trajectory(MODEL, times, trains, **args)
    path = tmp_path/'forced.npz'
    with pytest.raises(adapter.MarhlCheckpointStop):
        adapter.trajectory(MODEL, times, trains, checkpoint=path, max_chunk_span=.03, stop_after_chunks=2, **args)
    evidence = {}
    _, result = adapter.trajectory(MODEL, times, trains, checkpoint=path, resume=True,
                                   max_chunk_span=.03, evidence=evidence, **args)
    np.testing.assert_allclose(result, original, rtol=1e-13, atol=1e-13)
    assert evidence['performed_resets'] == 2 and evidence['train_reset_counts'] == [2]
    np.testing.assert_allclose(result[:, 3]+result[:, 4], 120., rtol=0, atol=1e-13)


@pytest.mark.parametrize('args', [{'precision': 32}, {'degree': 3}, {'tolerance': 'nan'},
    {'max_chunk_span': 0}, {'checkpoint_every': 0}, {'stop_after_chunks': 0},
    {'max_seconds': -1}, {'max_seconds': 1}, {'resume': True}])
def test_invalid_requests_are_rejected_without_starting_integration(analytic, args):
    with pytest.raises(ValueError):
        adapter.trajectory(MODEL, TIMES, TRAINS, **args)


@pytest.mark.parametrize('kind', ['unknown', 'negative', 'conflict', 'ambiguous', 'fractional_count', 'endpoint_flag'])
def test_invalid_reset_protocols_are_rejected(analytic, kind):
    trains, times = deepcopy(TRAINS), TIMES.copy()
    if kind == 'unknown': trains[0]['values'] = {'unknown': 1.}
    elif kind == 'negative': trains[0]['values'] = {'CaM': -1.}
    elif kind == 'conflict': trains *= 2
    elif kind == 'ambiguous': times[1] = .1
    elif kind == 'fractional_count': trains[0]['interval'] = .3
    elif kind == 'endpoint_flag': trains[0]['include_start'] = 1
    with pytest.raises(ValueError):
        adapter.trajectory(MODEL, times, trains)
