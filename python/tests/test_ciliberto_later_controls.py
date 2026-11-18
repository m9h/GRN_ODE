"""Synthetic full-grid arrays and mocked workers test auditing, not convergence."""

from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain
from grn_memory.scipy_breaking_recovery import LABELS
from scripts import audit_ciliberto_later_controls as auditor
from scripts import run_ciliberto_later_controls as runner
from scripts.audit_scipy_breaking import trajectory


@pytest.fixture(scope='module')
def context():
    inventory, model, info, grid = runner.inputs.prepare_inventory()
    # Array/transport tests must also run in the native CI environment without
    # optional JAX packages. The workflow's separate real-plan check verifies
    # the actual installed source hashes and package versions.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, 'runtime', lambda: {
            'source_hashes': {'synthetic_test_fixture': 'no numerical integration'},
            'versions': {'synthetic_test_fixture': 'not a scientific result'}})
        plan = runner.make_plan(inventory, info, grid)
    return plan, inventory, model, info, grid


def test_all_6859_controls_partition_once_including_200_generated(context):
    plan, inventory, _, _, _ = context
    rows = [row for part in plan['partitions'] for row in part['branches']]
    ids = [row['record_id'] for row in rows]
    assert len(ids) == len(set(ids)) == 6859
    assert set(inventory['generated_potential_branch_ids']) <= set(ids)
    assert sum(row['origin'] == 'generated_potential' for row in rows) == 200
    assert {len(part['branches']) for part in plan['partitions']} == {26, 27}
    assert len(plan['partitions']) == 256
    assert max(p['uncompressed_numeric_payload_bytes'] for p in plan['partitions']) < 4.1e9
    assert plan['expected_integrations'] == 27436
    assert plan['full_case_audit_required'] and not plan['case_recovery_claimed']
    source = runner.read(runner.original.SOURCE / 'inventory.json')
    first = runner.read(runner.original.SOURCE / 'computation-plan.json')['stage_1']['branches']
    assert not (set(ids) & set(first)) and not (set(ids) & set(source['reusable_verified_branches']))
    assert set(ids) | set(first) | set(source['reusable_verified_branches']) == set(inventory['branches'])


@pytest.mark.parametrize('index', [-1, 256, True, 1.5, None])
def test_invalid_partition_rejected(context, index):
    with pytest.raises(ValueError, match='partition'):
        runner.selected(context[0], index)


@pytest.fixture(scope='module')
def synthetic(context, tmp_path_factory):
    plan, inventory, _, info, grid = context
    root = tmp_path_factory.mktemp('synthetic-ciliberto-generated-control')
    bid = inventory['generated_potential_branch_ids'][0]
    spec = inventory['branches'][bid]
    times = grid[grid <= spec['stop']]
    assert len(times) == 221001
    trains = [ResetTrain(**train) for train in spec['reset_trains']]
    resets = sorted({float(v) for t in trains if t.values for v in t.times()})
    counts = [len(t.indices()) if t.values else 0 for t in trains]
    metadata = runner.metadata_for(plan)
    record = {'record_id': bid, 'fingerprint': metadata['fingerprint'], 'specification': spec,
              'integrations': {}, 'traces': {}, 'comparisons': {}, 'status': 'confirmed',
              'case_recovery_claimed': False}
    for label in LABELS:
        path = root / (bid + '-' + label + '.npz')
        np.savez_compressed(path, times=times, values=np.ones((len(times), len(info['observables']))),
                            observables=np.asarray(info['observables']))
        record['traces'][label] = {'file': path.name, 'sha256': runner.digest(path)}
        outcome = {'request': plan['requests'][label], 'completed': True,
                   'sample_count': len(times), 'observables': info['observables']}
        if label.startswith('scipy'):
            outcome.update(backend='scipy.solve_ivp', rhs_backend='Jaxkineticmodel', jacobian='jax.jacfwd',
                model_sha256=info['sha256'], method='Radau', rtol=plan['requests'][label]['rtol'],
                atol=plan['requests'][label]['atol'], x64=True, absolute_time_preserved=True,
                expected_resets=len(resets), performed_resets=len(resets),
                expected_train_reset_counts=counts, train_reset_counts=counts,
                expected_segments=len(resets)+1, completed_segments=len(resets)+1,
                last_interval=[resets[-1] if resets else 0., float(times[-1])])
        record['integrations'][label] = outcome
    report = {'metadata': metadata, 'plan_sha256': 'synthetic-plan-file-hash', 'record_id': bid,
              'status': 'completed', 'synthetic_test_fixture': True}
    save(root, report, record, context, recompute=True)
    return root


def save(directory, report, record, context, *, recompute=False):
    plan, _, _, info, grid = context
    bid = record['record_id']
    if recompute:
        times = grid[grid <= record['specification']['stop']]
        traces = {label: trajectory(directory, bid, label, saved, times, info['observables'])
                  for label, saved in record['traces'].items()}
        record['comparisons'] = {a + '_vs_' + b: comparison(traces[a], traces[b], **plan['acceptance'])
            for i, a in enumerate(LABELS) for b in LABELS[i+1:] if a in traces and b in traces}
        record['status'] = ('incomplete' if len(record['comparisons']) != 6 else
            'confirmed' if all(v['passed'] for v in record['comparisons'].values()) else 'mismatch')
    runner.write(directory / (bid + '.json'), record)
    report['branch'] = {'record_id': bid, 'file': bid + '.json',
                        'sha256': runner.digest(directory / (bid + '.json')), 'status': record['status']}
    runner.write(directory / 'report.json', report)


@pytest.fixture
def branch(synthetic, tmp_path):
    directory = tmp_path / 'evidence'
    shutil.copytree(synthetic, directory)
    report = runner.read(directory / 'report.json')
    return directory, report, runner.read(directory / report['branch']['file'])


def audit(branch, context):
    plan, inventory, _, info, grid = context
    return auditor.audit(branch[0], plan, inventory, info, grid, 'synthetic-plan-file-hash')


def test_generated_control_full_grid_audited_without_original_result(branch, context):
    result = audit(branch, context)
    assert result['status'] == 'confirmed' and result['verified_arrays'] == 4
    assert len(result['comparisons']) == 6 and result['samples'] == 221001
    assert result['origin'] == {'kind': 'generated_potential', 'original_record_available': False}
    assert not result['case_recovery_claimed'] and not result['full_model_coverage_claimed']


def test_honest_last_sample_disagreement_is_retained(branch, context):
    directory, report, record = branch
    saved = record['traces']['scipy_refined']
    path = directory / saved['file']
    with np.load(path) as data:
        arrays = {key: data[key].copy() for key in data.files}
    arrays['values'][-1, -1] += 1
    np.savez_compressed(path, **arrays)
    saved['sha256'] = runner.digest(path)
    save(directory, report, record, context, recompute=True)
    result = audit(branch, context)
    assert result['status'] == 'mismatch' and result['verified_arrays'] == 4


def test_failed_integration_and_uncheckpointed_array_stay_explicit(branch, context):
    directory, report, record = branch
    outcome = record['integrations']['scipy_refined']
    outcome.update(completed=False, error='Synthetic solver failure')
    orphan = record['traces'].pop('scipy_refined')['file']
    save(directory, report, record, context, recompute=True)
    result = audit(branch, context)
    assert result['status'] == 'incomplete' and result['complete_requested_outcomes']
    assert result['verified_arrays'] == 3 and result['unverified_arrays'] == [orphan]


@pytest.mark.parametrize('change', ['missing_outcome', 'request', 'resets', 'source', 'plan', 'spec',
                                   'false_status', 'unexpected_reuse', 'unknown_file', 'unfinished_report'])
def test_audit_rejects_changed_evidence(branch, context, change):
    directory, report, record = branch
    if change == 'missing_outcome': record['integrations'].pop('scipy')
    elif change == 'request': record['integrations']['scipy']['request'] = {'rtol': 1.}
    elif change == 'resets': record['integrations']['scipy']['performed_resets'] -= 1
    elif change == 'source': report['metadata']['runtime']['versions']['jax'] = 'wrong'
    elif change == 'plan': report['plan_sha256'] = 'wrong'
    elif change == 'spec': record['specification']['stop'] -= 400
    elif change == 'false_status': record['status'] = 'mismatch'
    elif change == 'unexpected_reuse': record['reused_from'] = {}
    elif change == 'unknown_file': (directory / 'surprise.tmp').write_text('untrusted')
    elif change == 'unfinished_report': report['status'] = 'running'
    save(directory, report, record, context)
    with pytest.raises(ValueError):
        audit(branch, context)


def test_incomplete_array_rejected_even_with_updated_checksum(branch, context):
    directory, report, record = branch
    saved = record['traces']['roadrunner']
    path = directory / saved['file']
    with np.load(path) as data:
        arrays = {key: data[key].copy() for key in data.files}
    arrays['times'] = arrays['times'][:-1]
    arrays['values'] = arrays['values'][:-1]
    np.savez_compressed(path, **arrays)
    saved['sha256'] = runner.digest(path)
    save(directory, report, record, context)
    with pytest.raises(ValueError, match='observation inventory'):
        audit(branch, context)


def test_temporary_checkpoint_is_preserved_without_being_read(branch, context):
    (branch[0] / 'report.json.tmp').write_bytes(b'not valid JSON')
    result = audit(branch, context)
    assert result['status'] == 'confirmed'
    assert result['unverified_checkpoint_files'] == ['report.json.tmp']


def mock_runner(context, monkeypatch, mode):
    plan = context[0]
    monkeypatch.setattr(runner, 'load_plan', lambda *a: context)
    monkeypatch.setattr(runner, 'selected', lambda *a: plan['partitions'][0]['branches'][:2])
    monkeypatch.setattr(runner.inputs, 'validate', lambda *a: {'complete_input_scope_verified': True})
    monkeypatch.setattr(runner.shutil, 'disk_usage', lambda *a: SimpleNamespace(free=0 if mode == 'disk' else 10**12))
    monkeypatch.setattr(auditor, 'audit', lambda *a: {'status': 'mismatch' if mode == 'mismatch' else 'confirmed'})
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=runner.ROOT, text=True).strip()
    monkeypatch.setattr(runner.subprocess, 'check_output', lambda *a, **kw: head + '\n')
    calls = []
    def child(command, **kwargs):
        calls.append(command)
        if mode == 'timeout': raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        if mode == 'exit': return SimpleNamespace(returncode=1)
        directory = Path(command[command.index('--output')+1])
        directory.mkdir()
        runner.write(directory / 'report.json', {'source_revision': head,
            'run_id': runner.os.environ.get('GITHUB_RUN_ID'), 'run_attempt': runner.os.environ.get('GITHUB_RUN_ATTEMPT')})
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner.subprocess, 'run', child)
    return calls


@pytest.mark.parametrize('mode,status,entry_status', [('pass', 'completed', 'confirmed'),
    ('mismatch', 'completed', 'numerical_failure'), ('timeout', 'incomplete', 'time_limit'),
    ('exit', 'incomplete', 'execution_or_audit_failure'), ('disk', 'incomplete', None)])
def test_runner_retains_all_outcomes_and_pending_work(context, tmp_path, monkeypatch, mode, status, entry_status):
    calls = mock_runner(context, monkeypatch, mode)
    out = tmp_path / 'partition'
    code = runner.compute(tmp_path / 'plan.json', 'sha', tmp_path / 'inputs', 0, out, 60)
    result = runner.read(out / 'execution.json')
    assert result['status'] == status and result['expected_branches'] == 2
    assert code == (0 if mode == 'pass' else 2)
    if mode == 'disk':
        assert not calls and not result['branches'] and result['stop_reason'] == 'disk_limit'
    else:
        assert len(calls) == 2 and all(row['status'] == entry_status for row in result['branches'])
    assert not result['case_recovery_claimed'] and result['full_case_audit_required']


@pytest.mark.parametrize('budget', [0, -1, 19801])
def test_invalid_budget_rejected_without_starting(context, tmp_path, budget):
    with pytest.raises(ValueError, match='budget'):
        runner.compute(tmp_path / 'plan', 'sha', tmp_path / 'inputs', 0, tmp_path / 'output', budget)


def test_existing_output_is_never_implicitly_resumed(tmp_path):
    with pytest.raises(ValueError, match='new output'):
        runner.compute(tmp_path / 'plan', 'sha', tmp_path / 'inputs', 0, tmp_path, 60)


def test_budget_stop_keeps_unattempted_controls_pending(context, tmp_path, monkeypatch):
    calls = mock_runner(context, monkeypatch, 'pass')
    clock = iter([0., 61.])
    monkeypatch.setattr(runner, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
    out = tmp_path / 'partition'
    assert runner.compute(tmp_path / 'plan', 'sha', tmp_path / 'inputs', 0, out, 60) == 2
    result = runner.read(out / 'execution.json')
    assert result['stop_reason'] == 'time_limit' and result['status'] == 'incomplete'
    assert result['expected_branches'] == 2 and not result['branches'] and not calls


@pytest.mark.parametrize('outcome', ['confirmed', 'incomplete'])
def test_child_preserves_original_producer_outcome(context, tmp_path, monkeypatch, outcome):
    plan, inventory, _, _, _ = context
    bid = inventory['generated_potential_branch_ids'][0]
    monkeypatch.setattr(runner, 'load_plan', lambda *a: context)
    def numerical(selected, spec, directory, metadata, grid, model, info):
        assert selected == bid and spec == inventory['branches'][bid]
        assert metadata == runner.metadata_for(plan)
        assert len(grid) == 221001 and len(info['observables']) == 20
        row = {'record_id': bid, 'status': outcome, 'file': bid + '.json'}
        runner.write(directory / row['file'], {'synthetic_worker_result': True})
        return {**row, 'sha256': runner.digest(directory / row['file'])}
    monkeypatch.setattr(runner, 'compute_branch', numerical)
    out = tmp_path / 'branch'
    assert runner.child(tmp_path / 'plan', 'test-sha', bid, out) == 0
    report = runner.read(out / 'report.json')
    assert report['status'] == 'completed' and report['branch']['status'] == outcome
    assert report['metadata']['case_recovery_claimed'] is False


def test_child_cannot_compute_an_excluded_published_control(context, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'load_plan', lambda *a: context)
    with pytest.raises(ValueError, match='outside'):
        runner.child(tmp_path / 'plan', 'test-sha', context[1]['full_untreated_control'], tmp_path / 'out')


def test_child_cannot_overwrite_existing_evidence(context, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'load_plan', lambda *a: context)
    with pytest.raises(ValueError, match='new child directory'):
        runner.child(tmp_path / 'plan', 'test-sha', context[1]['generated_potential_branch_ids'][0], tmp_path)
