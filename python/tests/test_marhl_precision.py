"""Full-scope task orchestration and independent array audits.

Synthetic arrays exercise transport, completion and audit failures. They are
not biological results. The separate adapter suites test actual integration.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip('mpmath')
from grn_memory import marhl_precision as work

INVENTORY = work.ROOT/'results/catalog-breaking-marhl-full-controls-20261118/inventory.json'

@pytest.fixture
def setup(tmp_path, monkeypatch):
    plan = tmp_path/'plan.json'
    work.write_json(plan, work.make_plan(INVENTORY))
    monkeypatch.setattr(work, 'runtime', lambda backend: {'test_runtime': backend})
    return plan, tmp_path

def evidence(request, times, trains):
    _, events, counts, edges, chunks = work.marhl_checkpoints.protocol(times, trains, 1.)
    return {'completed': True, 'model_sha256': work.MODEL_SHA256,
            'precision_bits': request['precision'], 'tolerance': request['tolerance'],
            'numeric_inputs': 'binary64 values promoted exactly', 'absolute_time_preserved': True,
            'observables': work.NAMES, 'sample_count': len(times), 'expected_resets': len(events),
            'performed_resets': len(events), 'expected_train_reset_counts': counts,
            'train_reset_counts': counts.copy(), 'expected_segments': len(edges)-1,
            'completed_segments': len(edges)-1, 'last_interval': list(map(float, edges[-2:])),
            'backend': 'mpmath.odefun', 'degree': request.get('degree'),
            'expected_chunks': len(chunks)-1, 'completed_chunks': len(chunks)-1,
            'rhs_evaluations': 10, 'high_accuracy': True, 'integration_steps': 10}

def checkpoint(path, request, times, trains, values, integration):
    sources = {name: work.digest(work.ROOT/name) for name in work.FILES}
    ci = {'model_sha256': work.MODEL_SHA256, 'trains': trains, 'observables': work.NAMES}
    grid = hashlib.sha256(times.tobytes()).hexdigest()
    if request['backend'] == 'mpmath':
        schema = 1
        ci.update(precision=request['precision'], sample_grid_sha256=grid, max_chunk_span=1.,
                  implementation_sha256={'adapter': sources['grn_memory/marhl_checkpoints.py'],
                                         'equations': sources['grn_memory/marhl_mpmath.py']})
    else:
        schema = 2
        ci.update(precision_bits=request['precision'], times_sha256=grid, samples=len(times),
                  checkpoint_steps=1_000_000,
                  sources={'adapter': sources['grn_memory/taylor_reference.py'],
                           'checkpoints': sources['grn_memory/taylor_checkpoints.py']})
    metadata = {'schema': schema, 'identity': ci, 'identity_sha256': work.fingerprint(ci),
                'state': ['0']*len(work.NAMES), 'evidence': deepcopy(integration),
                'observations_sha256': hashlib.sha256(values.tobytes()).hexdigest()}
    metadata['payload_sha256'] = work.fingerprint(metadata)
    with Path(path).open('wb') as stream:
        np.savez_compressed(stream, metadata=np.asarray(json.dumps(metadata)), observations=values)

@pytest.fixture
def fake(monkeypatch):
    calls = []
    def integrate(path, times, trains, **kwargs):
        backend = 'mpmath' if 'degree' in kwargs else 'heyoka'
        request = next(r for r in work.REQUESTS.values() if r['backend'] == backend and r['precision'] == kwargs['precision'])
        calls.append({'times': times.copy(), 'trains': deepcopy(trains), 'kwargs': dict(kwargs)})
        values = np.broadcast_to(np.arange(1., 6.), (len(times), 5)).copy()
        kwargs['evidence'].update(evidence(request, times, trains))
        checkpoint(kwargs['checkpoint'], request, times, trains, values, kwargs['evidence'])
        return work.NAMES.copy(), values
    monkeypatch.setattr(work.marhl_checkpoints, 'trajectory', integrate)
    monkeypatch.setattr(work.taylor_reference, 'taylor_trajectory', integrate)
    return calls

def complete(setup, indices=range(4)):
    plan, root = setup
    paths = []
    for index in indices:
        output = root/f'task-{index}'
        report = work.run_task(plan, INVENTORY, index, output)
        assert report['status'] == 'completed', report.get('error')
        paths.append(output)
    return paths

def test_all_tasks_and_full_original_protocols(setup):
    plan, inventory = work.check_plan(setup[0], INVENTORY, rebuild_inventory=True)
    assert plan['task_count'] == 1520
    assert [len(b) for b in plan['batches']] == [256]*5+[240]
    assert sum(plan['batches'], []) == list(range(1520))
    assert plan['branches'][0] == inventory['full_untreated_control']
    assert set(plan['branches'][1:30]) == set(inventory['diagnostic_branch_ids'])
    assert set(plan['branches']) == inventory['branches'].keys()
    assert set(inventory['generated_potential_branch_ids']) <= set(plan['branches'])
    assert len(inventory['generated_potential_branch_ids']) == 88
    seen, horizons = set(), set()
    for branch_index in range(380):
        bid, label, spec, times = work.problem(plan, inventory, branch_index*4)
        seen.add(bid); horizons.add(times[-1])
        assert len(times) == round(spec['stop']/.01)+1
        assert label == 'taylor128'
        assert work.marhl_checkpoints.protocol(times, spec['reset_trains'], 1.)[2] == inventory['branch_observations'][bid]['reset_counts']
    assert len(seen) == 380 and horizons == {1410., 1810., 2210.}

@pytest.mark.parametrize('mutation', ['drop_control', 'shorten_batch', 'acceptance', 'request', 'source'])
def test_plan_changes_are_rejected(setup, mutation):
    path, _ = setup
    plan = work.read(path)
    if mutation == 'drop_control': plan['branches'].pop()
    if mutation == 'shorten_batch': plan['batches'][-1].pop()
    if mutation == 'acceptance': plan['acceptance']['rtol'] = 1.
    if mutation == 'request': plan['requests']['mpmath192']['precision'] = 128
    if mutation == 'source': plan['sources']['grn_memory/marhl_mpmath.py'] = '0'*64
    work.write_json(path, plan)
    with pytest.raises(ValueError, match='Plan does not reproduce'):
        work.check_plan(path, INVENTORY)

@pytest.mark.parametrize('task', [-1, 1520, True, 1.5])
def test_invalid_tasks(setup, task):
    plan, inventory = work.check_plan(setup[0], INVENTORY)
    with pytest.raises(ValueError, match='Invalid task'):
        work.problem(plan, inventory, task)

@pytest.mark.parametrize('index', [0, 1, 2, 3, 4, 7, 1516, 1519])
def test_worker_preserves_full_inputs_and_reuses_completed_task(setup, fake, index):
    paths = complete(setup, [index])
    output = paths[0]
    before = {p.name: work.digest(p) for p in output.iterdir() if p.is_file()}
    old = work.read(output/'report.json')
    assert old['identity']['request'] == work.REQUESTS[old['identity']['request_label']]
    assert fake[-1]['times'][-1] == old['identity']['specification']['stop']
    assert fake[-1]['trains'] == old['identity']['specification']['reset_trains']
    assert fake[-1]['kwargs']['resume'] is False
    assert len(fake) == 1
    result = work.run_task(setup[0], INVENTORY, index, output, resume=True)
    assert result == old and len(fake) == 1
    assert before == {p.name: work.digest(p) for p in output.iterdir() if p.is_file()}
    with pytest.raises(ValueError, match='explicit resume'):
        work.run_task(setup[0], INVENTORY, index, output)

def test_resume_rejects_other_task_runtime_or_changed_checkpoint(setup, fake, monkeypatch):
    output = complete(setup, [2])[0]
    with pytest.raises(ValueError, match='changed on resume'):
        work.run_task(setup[0], INVENTORY, 3, output, resume=True)
    old_runtime = work.runtime
    monkeypatch.setattr(work, 'runtime', lambda backend: {'changed': True})
    with pytest.raises(ValueError, match='changed on resume'):
        work.run_task(setup[0], INVENTORY, 2, output, resume=True)
    monkeypatch.setattr(work, 'runtime', old_runtime)
    (output/'checkpoint.npz').write_bytes(b'changed')
    with pytest.raises(ValueError, match='checkpoint was changed'):
        work.run_task(setup[0], INVENTORY, 2, output, resume=True)
    assert len(fake) == 1

@pytest.mark.parametrize('index', [0, 2])
def test_budget_stop_then_explicit_resume_keeps_history(setup, fake, monkeypatch, index):
    backend = work.taylor_reference if index == 0 else work.marhl_checkpoints
    name = 'taylor_trajectory' if index == 0 else 'trajectory'
    original = getattr(backend, name)
    stop = work.taylor_checkpoints.TaylorCheckpointStop if index == 0 else work.marhl_checkpoints.MarhlCheckpointStop
    def interrupted(path, times, trains, **kwargs):
        names, values = original(path, times, trains, **kwargs)
        kwargs['evidence']['completed'] = False
        raise stop('Synthetic cooperative stop')
    monkeypatch.setattr(backend, name, interrupted)
    output = setup[1]/'partial'
    first = work.run_task(setup[0], INVENTORY, index, output)
    assert first['status'] == 'checkpointed' and first['trace'] is None
    assert not (output/'trajectory.npz').exists()
    saved = work.digest(output/'checkpoint.npz')
    monkeypatch.setattr(backend, name, original)
    final = work.run_task(setup[0], INVENTORY, index, output, resume=True)
    assert final['status'] == 'completed' and len(final['attempts']) == 2
    assert final['attempts'][1]['parent_checkpoint_sha256'] == saved
    assert fake[-1]['kwargs']['resume'] is True
    assert final['attempts'][0]['status'] == 'checkpointed'
    assert 'interruption' not in final

def test_numerical_failure_is_explicit_and_retained_on_retry(setup, fake, monkeypatch):
    original = work.marhl_checkpoints.trajectory
    def fail(*args, **kwargs):
        raise RuntimeError('Synthetic numerical failure')
    monkeypatch.setattr(work.marhl_checkpoints, 'trajectory', fail)
    output = setup[1]/'failed'
    first = work.run_task(setup[0], INVENTORY, 2, output)
    assert first['status'] == 'integration_failed' and first['trace'] is None
    monkeypatch.setattr(work.marhl_checkpoints, 'trajectory', original)
    final = work.run_task(setup[0], INVENTORY, 2, output, resume=True)
    assert final['status'] == 'completed' and 'error' not in final
    assert 'Synthetic numerical failure' in final['attempts'][0]['error']

def test_four_full_arrays_and_all_six_pairs_are_independently_audited(setup, fake):
    paths = complete(setup)
    before = {str(p): work.digest(p) for root in paths for p in root.iterdir() if p.is_file()}
    bid = work.read(setup[0])['branches'][0]
    result = work.audit_branch(setup[0], INVENTORY, bid, paths)
    assert result['status'] == 'agreement' and result['verified_arrays'] == 4
    assert len(result['comparisons']) == 6 and all(c['samples'] == 221001 for c in result['comparisons'].values())
    assert set(result['windows']) == set(work.REQUESTS)
    assert not result['case_recovery_claimed'] and not result['internal_states_compared']
    assert before == {str(p): work.digest(p) for root in paths for p in root.iterdir() if p.is_file()}
    assert len(fake) == 4

@pytest.mark.parametrize('kind', ['duplicate', 'missing', 'partial', 'other_branch'])
def test_partial_or_mixed_task_sets_are_rejected(setup, fake, kind):
    paths = complete(setup)
    bid = work.read(setup[0])['branches'][0]
    if kind == 'duplicate': paths[-1] = paths[0]
    if kind == 'missing': paths.pop()
    if kind == 'other_branch': paths[-1] = complete(setup, [7])[0]
    if kind == 'partial':
        report = work.read(paths[-1]/'report.json'); report['status'] = 'checkpointed'
        work.write_json(paths[-1]/'report.json', report)
    with pytest.raises(ValueError):
        work.audit_branch(setup[0], INVENTORY, bid, paths)

@pytest.mark.parametrize('field,value', [('sample_count', 2), ('performed_resets', True),
    ('precision_bits', 64), ('absolute_time_preserved', False), ('completed', False),
    ('tolerance', '1e-6'), ('completed_chunks', 1), ('degree', 16)])
def test_forged_completion_counters_do_not_pass(setup, fake, field, value):
    output = complete(setup, [2])[0]
    report = work.read(output/'report.json')
    report['integration'][field] = value
    work.write_json(output/'report.json', report)
    with pytest.raises(ValueError):
        work.run_task(setup[0], INVENTORY, 2, output, resume=True)
    assert len(fake) == 1

@pytest.mark.parametrize('kind', ['checksum', 'truncate', 'nan', 'grid', 'observables', 'checkpoint'])
def test_damaged_arrays_and_checkpoints_are_rejected(setup, fake, kind):
    output = complete(setup, [2])[0]
    report = work.read(output/'report.json')
    path = output/'trajectory.npz'
    with np.load(path, allow_pickle=False) as z:
        arrays = {k: z[k].copy() for k in z.files}
    if kind == 'checksum': path.write_bytes(b'damaged')
    elif kind == 'checkpoint':
        (output/'checkpoint.npz').write_bytes(b'damaged')
        report['checkpoint_sha256'] = work.digest(output/'checkpoint.npz')
    else:
        if kind == 'truncate': arrays['values'] = arrays['values'][:-1]
        if kind == 'nan': arrays['values'][-1, -1] = np.nan
        if kind == 'grid': arrays['times'][-1] -= .001
        if kind == 'observables': arrays['observables'] = arrays['observables'][::-1]
        np.savez_compressed(path, **arrays)
        report['trace']['sha256'] = work.digest(path)
    work.write_json(output/'report.json', report)
    with pytest.raises((ValueError, OSError)):
        work.run_task(setup[0], INVENTORY, 2, output, resume=True)

def test_a_late_single_sample_disagreement_is_retained(setup, fake):
    paths = complete(setup)
    output = paths[-1]
    report = work.read(output/'report.json')
    with np.load(output/'trajectory.npz', allow_pickle=False) as z:
        times, values = z['times'].copy(), z['values'].copy()
    values[-7, 3] += 1.
    work.save_trace(output/'trajectory.npz', times, work.NAMES, values)
    checkpoint(output/'checkpoint.npz', work.REQUESTS['mpmath192'], times, [], values, report['integration'])
    report['trace']['sha256'] = work.digest(output/'trajectory.npz')
    report['checkpoint_sha256'] = work.digest(output/'checkpoint.npz')
    work.write_json(output/'report.json', report)
    result = work.audit_branch(setup[0], INVENTORY, report['identity']['branch_id'], paths)
    assert result['status'] == 'mismatch' and not result['high_precision_agreement']
    bad = [c for c in result['comparisons'].values() if not c['passed']]
    assert len(bad) == 3 and all(c['worst_time'] == times[-7] for c in bad)
    assert result['acceptance'] == {'rtol': 2e-5, 'atol': 1e-7}

@pytest.mark.parametrize('index', [0, 1, 2, 3])
def test_real_adapter_checkpoint_and_completed_task_round_trip(setup, monkeypatch, index):
    # Short numerical regression of the wrapper, not a full breaking result.
    if index < 2:
        pytest.importorskip('heyoka')
    times = np.array([0., .09999, .10001, .29999, .30001, .50001, .75, 1.])
    trains = [{'start': .1, 'stop': .5, 'interval': .2, 'include_start': True,
               'include_stop': True, 'values': {'Ca_cyt': 10.}}]
    spec = {'reset_trains': trains, 'stop': 1., 'integration_settings': {}}
    label = list(work.REQUESTS)[index]
    monkeypatch.setattr(work, 'problem', lambda plan, inventory, task: (work.fingerprint(spec), label, spec, times))
    output = setup[1]/'real-short-regression'
    report = work.run_task(setup[0], INVENTORY, index, output, max_seconds=60.)
    assert report['status'] == 'completed', report.get('error')
    assert report['integration']['train_reset_counts'] == [3]
    first = work.load_trace(output, report, times, work.REQUESTS[label], trains)
    assert np.isfinite(first).all()
    resumed = work.run_task(setup[0], INVENTORY, index, output, resume=True)
    assert resumed == report
    assert np.array_equal(work.load_trace(output, resumed, times, work.REQUESTS[label], trains), first)
