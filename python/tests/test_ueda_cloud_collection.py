"""Synthetic transport fixtures: these are not experimental results."""

from copy import deepcopy
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import pytest

from grn_memory.catalog_memory import write_json
from grn_memory.catalog_validation import comparison
from scripts import collect_ueda_continuation as c

INPUTS = Path(__file__).parents[1]/'results/catalog-breaking-ueda-continuation-20261118'


def selection_fixture():
    plan = c.read(INPUTS/'continuation-plan.json')
    run = {'id': 123, 'run_attempt': 1, 'workflow_id': 456, 'head_sha': 'a'*40, 'path': c.WORKFLOW}
    jobs = [{'id': 1, 'name': 'validation', 'conclusion': 'success',
             'run_id': run['id'], 'run_attempt': 1, 'head_sha': run['head_sha']}]
    for i in range(32):
        jobs.append({'id': i+2, 'name': f'ueda-case-partition-{i}', 'conclusion': None, 'status': 'queued',
                     'run_id': run['id'], 'run_attempt': 1, 'head_sha': run['head_sha']})
    api = {'total_count': len(jobs), 'jobs': jobs}
    return plan, run, api


def test_binding_requires_successful_gate_and_every_original_job():
    plan, run, jobs = selection_fixture()
    s = c.bind_selection(plan, c.digest(INPUTS/'continuation-plan.json'), run, jobs)
    assert len(s['selected']) == 32
    assert len({bid for row in s['selected'] for bid in row['branch_ids']}) == 153
    for change in ('gate', 'gate_source', 'missing', 'duplicate'):
        bad = deepcopy(jobs)
        if change == 'gate':
            bad['jobs'][0]['conclusion'] = 'failure'
        elif change == 'gate_source':
            bad['jobs'][0]['head_sha'] = 'b'*40
        elif change == 'missing':
            bad['jobs'].pop(); bad['total_count'] -= 1
        else:
            bad['jobs'][-1]['name'] = bad['jobs'][-2]['name']
        with pytest.raises(ValueError):
            c.bind_selection(plan, 'plan', run, bad)


def test_fixed_selection_rejects_omitted_control_or_duplicate_job():
    plan, run, jobs = selection_fixture()
    s = c.bind_selection(plan, 'plan', run, jobs)
    for change in ('control', 'job'):
        bad = deepcopy(s)
        if change == 'control':
            bad['selected'][0]['branch_ids'].pop()
        else:
            bad['selected'][1]['job_id'] = bad['selected'][0]['job_id']
        with pytest.raises(ValueError):
            c.validate_selection(bad, plan)


def test_failed_job_artifacts_retained_but_wrong_attempt_rejected():
    plan, run, jobs = selection_fixture()
    s = c.bind_selection(plan, 'plan', run, jobs)
    row, job = s['selected'][0], jobs['jobs'][1]
    job.update(status='completed', conclusion='failure', started_at='2026-11-18T20:00:00Z',
               completed_at='2026-11-18T20:05:00Z')
    artifact = {'name': row['artifact_name'], 'expired': False,
                'workflow_run': {'id': 123, 'head_sha': run['head_sha']},
                'created_at': '2026-11-18T20:04:00Z', 'digest': 'sha256:'+'0'*64}
    c.validate_artifact(s, row, run, job, artifact)
    for change in ('time', 'source', 'attempt'):
        bad_job, bad_artifact = deepcopy(job), deepcopy(artifact)
        if change == 'time': bad_artifact['created_at'] = '2026-11-18T19:00:00Z'
        if change == 'source': bad_artifact['workflow_run']['head_sha'] = 'b'*40
        if change == 'attempt': bad_job['run_attempt'] = 2
        with pytest.raises(ValueError):
            c.validate_artifact(s, row, run, bad_job, bad_artifact)


def test_extraction_rejects_traversal_and_rechecks_cached_bytes(tmp_path):
    archive, output = tmp_path/'source.zip', tmp_path/'evidence'
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr('../outside.json', '{}')
    with pytest.raises(ValueError, match='Unsafe'):
        c.extract(archive, output)
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr('record.json', '{}')
    c.extract(archive, output)
    c.verify_extraction(archive, output)
    (output/'record.json').write_text('{"changed":true}')
    with pytest.raises(ValueError, match='bytes differ'):
        c.verify_extraction(archive, output)


def test_unfinished_partitions_cannot_start_assembly(tmp_path):
    with pytest.raises(ValueError, match='All fixed partitions'):
        c.assemble(INPUTS, tmp_path, tmp_path, tmp_path/'assembled',
                   {'complete_selected_attempts': False}, None)
    assert not (tmp_path/'assembled').exists()


@pytest.fixture
def branch(tmp_path):
    bid, grid = 'b'*64, np.array([0., .5, 1.])
    info = {'observables': ['A'], 'sha256': 'model'}
    inventory = {'branches': {bid: {'stop': 1., 'reset_trains': []}}}
    requests = {label: {'rtol': 1e-10, 'atol': 1e-12,
                       **({'method': 'Radau'} if label.startswith('scipy') else {})} for label in c.LABELS}
    original = {'fingerprint': 'signature', 'requests': requests, 'acceptance': {'rtol': 2e-5, 'atol': 1e-7},
                'implementation_sha256': {'synthetic': 'source'}, 'versions': {'synthetic': '1'}}
    record = {'record_id': bid, 'specification': inventory['branches'][bid], 'fingerprint': 'signature',
              'case_recovery_claimed': False, 'integrations': {}, 'traces': {}, 'comparisons': {}}
    for label in c.LABELS:
        path = tmp_path/(bid+'-'+label+'.npz')
        np.savez_compressed(path, times=grid, values=np.array([[1.], [2.], [3.]]), observables=['A'])
        record['traces'][label] = {'file': path.name, 'sha256': c.digest(path)}
        outcome = {'request': requests[label], 'completed': True, 'sample_count': 3, 'observables': ['A']}
        if label.startswith('scipy'):
            outcome.update(backend='scipy.solve_ivp', rhs_backend='Jaxkineticmodel', jacobian='jax.jacfwd',
                model_sha256='model', method='Radau', rtol=1e-10, atol=1e-12, x64=True,
                absolute_time_preserved=True, expected_resets=0, performed_resets=0,
                expected_train_reset_counts=[], train_reset_counts=[], expected_segments=1,
                completed_segments=1, last_interval=[0., 1.])
        record['integrations'][label] = outcome
    entry = {}

    def save(recompute=True):
        if recompute:
            traces = {}
            for label, saved in record['traces'].items():
                with np.load(tmp_path/saved['file']) as array:
                    traces[label] = pd.DataFrame({'time': array['times'], 'A': array['values'][:, 0]})
            record['comparisons'] = {a+'_vs_'+b: comparison(traces[a], traces[b], **original['acceptance'])
                for i, a in enumerate(c.LABELS) for b in c.LABELS[i+1:] if a in traces and b in traces}
            record['status'] = ('incomplete' if len(traces) != 4 else 'confirmed'
                if all(v['passed'] for v in record['comparisons'].values()) else 'mismatch')
        path = tmp_path/(bid+'.json')
        write_json(path, record)
        entry.update(record_id=bid, file=path.name, sha256=c.digest(path), status=record['status'])

    save()
    return (tmp_path, bid, entry, original, inventory, info, grid), record, save


def test_all_six_comparisons_reproduced_from_every_sample(branch):
    args, _, _ = branch
    result = c.verify_branch(*args)
    assert result['attempt_finished'] and result['arrays_verified'] == 4
    assert result['status'] == 'confirmed' and len(result['comparisons']) == 6


@pytest.mark.parametrize('recompute', [False, True])
def test_changed_last_observation_is_detected_and_honest_mismatch_retained(branch, recompute):
    args, record, save = branch
    saved = record['traces']['scipy_refined']
    path = args[0]/saved['file']
    np.savez_compressed(path, times=args[-1], values=np.array([[1.], [2.], [4.]]), observables=['A'])
    saved['sha256'] = c.digest(path)
    save(recompute=recompute)
    if recompute:
        result = c.verify_branch(*args)
        assert result['attempt_finished'] and result['status'] == 'mismatch'
    else:
        with pytest.raises(ValueError, match='does not reproduce'):
            c.verify_branch(*args)


def test_failed_integration_retained_as_incomplete(branch):
    args, record, save = branch
    saved = record['traces'].pop('scipy_refined')
    (args[0]/saved['file']).unlink()
    record['integrations']['scipy_refined'] = {'request': args[3]['requests']['scipy_refined'],
                                             'completed': False, 'error': 'Synthetic solver failure'}
    save()
    result = c.verify_branch(*args)
    assert result['attempt_finished'] and result['status'] == 'incomplete' and result['arrays_verified'] == 3


def test_complete_arrays_without_finished_checkpoint_do_not_finish_attempt(branch):
    args, _, _ = branch
    modified = (*args[:2], None, *args[3:])
    result = c.verify_branch(*modified)
    assert not result['attempt_finished'] and result['arrays_verified'] == 4


def partition_fixture(branch):
    args, _, _ = branch
    directory, bid, entry, original, inventory, info, grid = args
    selection = {'plan_sha256': 'plan', 'original_report_sha256': 'original', 'head_sha': 'a'*40,
                 'run_id': 123, 'run_attempt': 1}
    row, plan = {'index': 0, 'branch_ids': [bid]}, {'selected_branch_ids': [bid]}
    lineage = {'schema_version': 1, 'plan_sha256': 'plan', 'original_report_sha256': 'original',
        'partition_index': 0, 'selected_branch_ids': [bid], 'full_selected_branch_ids': [bid],
        'source_revision': 'a'*40, 'wrapper_sha256': 'wrapper', 'github_run_id': '123',
        'github_run_attempt': '1', 'github_job': 'compute', 'numerical_implementation_sha256': original['implementation_sha256'],
        'versions': original['versions'], 'platform': 'synthetic', 'machine': 'synthetic', 'python': 'synthetic',
        'case_recovery_claimed': False, 'full_model_coverage_claimed': False,
        'byte_identical_restoration_claimed': False, 'status': 'completed', 'branches': [entry]}
    write_json(directory/'lineage.json', lineage)
    return (directory, selection, row, plan, original, inventory, info, grid, 'wrapper'), lineage


def test_partition_requires_every_branch_and_exact_lineage(branch):
    args, lineage = partition_fixture(branch)
    result = c.verify_partition(*args)
    assert result['complete_selected_attempts']
    for mutation in ('omitted', 'source', 'scope'):
        changed = deepcopy(lineage)
        if mutation == 'omitted': changed['branches'] = []
        if mutation == 'source': changed['source_revision'] = 'b'*40
        if mutation == 'scope': changed['selected_branch_ids'] = []
        write_json(args[0]/'lineage.json', changed)
        with pytest.raises(ValueError):
            c.verify_partition(*args)


def test_running_partition_never_finishes_even_if_all_arrays_exist(branch):
    args, lineage = partition_fixture(branch)
    lineage.update(status='running', active_branch=lineage['selected_branch_ids'][0])
    write_json(args[0]/'lineage.json', lineage)
    assert not c.verify_partition(*args)['complete_selected_attempts']


def test_pending_snapshot_records_no_coverage(tmp_path, monkeypatch):
    plan, run, jobs = selection_fixture()
    selection = c.bind_selection(plan, 'plan', run, jobs)
    selection_path = tmp_path/'selection.json'
    write_json(selection_path, selection)
    snapshots = tmp_path/'api'
    snapshots.mkdir()
    for name, value in [('run', run), ('jobs', jobs), ('artifacts', {'total_count': 0, 'artifacts': []})]:
        write_json(snapshots/(name+'.json'), value)
    monkeypatch.setattr(c, 'load_inputs', lambda *_: (plan, {}, {}, None, {}, np.array([0.])))
    monkeypatch.setattr(c.subprocess, 'check_output', lambda *_args, **_kwargs: b'synthetic-wrapper')
    result, _ = c.collect(INPUTS, selection_path, snapshots, tmp_path, tmp_path/'collected')
    assert result['pending_indices'] == list(range(32))
    assert not result['complete_selected_attempts'] and not result['case_recovery_claimed']
    assert result['partitions'] == [] and result['collection_errors'] == []
    assert result['numerical_integrations_performed'] == 0


def test_assembly_keeps_failed_new_result_and_never_uses_old_partial_array(tmp_path, monkeypatch):
    # Byte fixtures exercise assembly only; array mathematics is tested above.
    inputs, preserved, restored, cloud = [tmp_path/n for n in ('inputs', 'preserved', 'restored', 'cloud')]
    for p in (inputs, preserved, restored, cloud): p.mkdir()
    ids = [f'{i:064x}' for i in range(4)]

    def record(directory, bid, status, labels, value):
        traces = {}
        for label in labels:
            path = directory/(bid+'-'+label+'.npz')
            path.write_bytes(value)
            traces[label] = {'file': path.name, 'sha256': c.digest(path)}
        path = directory/(bid+'.json')
        write_json(path, {'record_id': bid, 'traces': traces, 'status': status})
        return {'record_id': bid, 'file': path.name, 'sha256': c.digest(path), 'status': status}

    old = record(preserved, ids[0], 'confirmed', c.LABELS, b'preserved')
    imported = record(restored, ids[1], 'confirmed', c.LABELS, b'published')
    mismatch = record(cloud, ids[2], 'mismatch', c.LABELS, b'new-mismatch')
    failed = record(cloud, ids[3], 'incomplete', c.LABELS[:-1], b'new-incomplete')
    stale = preserved/(ids[3]+'-'+c.LABELS[-1]+'.npz')
    stale.write_bytes(b'old-successful-array-must-not-be-used')
    original = {'branches': [old, imported], 'status': 'running'}
    for root in (inputs, preserved): write_json(root/'report.json', original)
    plan = {'selected_branch_ids': ids[2:], 'preserved_complete_branch_ids': [ids[0]],
            'imported_branch_ids': [ids[1]], 'original_report_sha256': c.digest(inputs/'report.json')}
    inventory = {'branches': {bid: {} for bid in ids}, 'full_untreated_control': ids[0]}
    write_json(inputs/'restoration-proof.json', {'branches': [imported]})
    write_json(inputs/'preservation-manifest.json', {'files': [
        {'path': p.name, 'bytes': p.stat().st_size, 'sha256': c.digest(p)} for p in preserved.iterdir()]})
    for name in ('source-evidence.json', 'original-case-plan.json', 'source-branches.jsonl.gz',
                 'source-branches-provenance.json', 'inventory.json', 'reused-report.json', 'reused-audit.json'):
        (inputs/name).write_text('{}')
    write_json(cloud/'lineage.json', {'synthetic': True})
    partition = {'index': 0, 'evidence': str(cloud), 'lineage_sha256': c.digest(cloud/'lineage.json'),
                 'artifact_id': 123, 'archive_sha256': 'synthetic',
                 'branches': [{**r, 'record_sha256': r['sha256']} for r in (mismatch, failed)]}
    status = {'complete_selected_attempts': True, 'partitions': [partition],
              'selection_sha256': 'synthetic', 'source_snapshot_sha256': {}}
    calls = []

    def inspect(stage):
        report = c.read(stage/'report.json')
        assert [r['record_id'] for r in report['branches']] == ids
        assert [r['status'] for r in report['branches']] == ['confirmed', 'confirmed', 'mismatch', 'incomplete']
        assert report['confirmed_branches'] == 2
        assert not (stage/stale.name).exists()
        assert c.digest(stage/'historical-report.json') == plan['original_report_sha256']
        assert c.digest(stage/old['file']) == old['sha256']
        calls.append(True)
        return {'selected_cases': 4, 'recovered_selected_cases': 0, 'baseline_passed': True}

    monkeypatch.setattr(c, 'audit_cases', inspect)
    result = c.assemble(inputs, preserved, restored, tmp_path/'assembled', status,
                        (plan, original, inventory, None, None, None))
    assert calls == [True] and result['recovered_selected_cases'] == 0
    assert stale.read_bytes() == b'old-successful-array-must-not-be-used'
    assert c.digest(preserved/'report.json') == plan['original_report_sha256']
