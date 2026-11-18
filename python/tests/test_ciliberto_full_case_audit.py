"""Complete-scope and synthetic transport/replay tests; no ODE integrations."""

from copy import deepcopy
from pathlib import Path
import zipfile

import numpy as np
import pytest

from scripts import audit_ciliberto_full_cases as full
from test_ciliberto_later_controls import context, synthetic, save
from test_ciliberto_later_collection import branch, partition_fixture, api_fixture
from test_scipy_breaking_case_audit import cube, stop_after_first, set_mean


@pytest.fixture
def first_plan():
    return full.read(full.FIRST_INPUTS / 'plan.json')


def test_all_7334_branches_and_74_cases_have_exactly_one_source(context, first_plan):
    result = full.scope(context, first_plan)
    assert len(result['branches']) == 7334 and len(result['selected_case_keys']) == 74
    assert result['stage_counts'] == {'published': 215, 'diagnostics': 260, 'controls': 6859}
    assert result['branches'][result['full_untreated_control']]['stage'] == 'published'
    generated = [b for b in result['branches'].values() if b['origin']['kind'] == 'generated_potential']
    assert len(generated) == 200 and all(b['stage'] == 'controls' for b in generated)
    assert all(b['origin']['original_record_available'] is False for b in generated)
    assert result['original_passing_cases'] == 548 and not result['full_model_coverage_claimed']


@pytest.mark.parametrize('change', ['missing_branch', 'duplicate_stage', 'missing_case', 'missing_generated'])
def test_scope_cannot_shrink_or_change_stages(context, first_plan, change):
    ctx = deepcopy(context)
    if change == 'missing_branch':
        ctx[0]['partitions'][0]['branches'].pop()
    elif change == 'duplicate_stage':
        ctx[0]['partitions'][0]['branches'][0]['record_id'] = first_plan['partitions'][0]['branches'][0]['record_id']
    elif change == 'missing_case':
        ctx[1]['cases'].pop(next(iter(ctx[1]['cases'])))
    else:
        ctx[1]['generated_potential_branch_ids'].pop()
    with pytest.raises(ValueError):
        full.scope(ctx, first_plan)


def test_full_grid_branch_is_reloaded_and_summarized(branch, context):
    directory, _, _ = branch
    report = full.read(directory / 'report.json')
    result = full.published_branch(directory, report['branch'], context, report['metadata'])
    assert result['complete_diagnostic'] and result['verified_arrays'] == 4
    assert result['status'] == 'confirmed' and set(result['windows']) == set(full.LABELS)


@pytest.mark.parametrize('change', ['last_sample', 'truncate', 'reset', 'request', 'missing_outcome', 'record_checksum'])
def test_saved_arrays_and_outcomes_rechecked_not_just_prior_audit(branch, context, change):
    directory, row, _ = branch
    report = full.read(directory / 'report.json')
    record = full.read(directory / (row['record_id'] + '.json'))
    if change in ('last_sample', 'truncate'):
        path = directory / record['traces']['scipy']['file']
        with np.load(path, allow_pickle=False) as data:
            times, values, names = data['times'].copy(), data['values'].copy(), data['observables'].copy()
        if change == 'truncate':
            times, values = times[:-1], values[:-1]
        else:
            values[-1, 0] = 2.
        np.savez_compressed(path, times=times, values=values, observables=names)
        record['traces']['scipy']['sha256'] = full.digest(path)
    elif change == 'reset':
        record['integrations']['scipy']['performed_resets'] -= 1
    elif change == 'request':
        record['integrations']['scipy']['request'] = {'rtol': 1.}
    elif change == 'missing_outcome':
        record['integrations'].pop('scipy_refined')
    save(directory, report, record, context)
    if change == 'record_checksum':
        report['branch']['sha256'] = 'wrong'
    with pytest.raises(ValueError):
        full.published_branch(directory, report['branch'], context, report['metadata'])


def stage_fixture(branch, context, tmp_path):
    root, row, execution, validation, selection, run, jobs = partition_fixture(branch, context, tmp_path)
    job = next(j for j in jobs['jobs'] if j['id'] == row['job_id'])
    job.update(status='completed', conclusion='timed_out', started_at='2026-11-18T23:00:00Z',
               completed_at='2026-11-19T05:00:00Z')
    cache = tmp_path / 'cache'
    destination = cache / str(run['id']) / 'attempt-1/artifact-1'
    destination.mkdir(parents=True)
    import shutil
    shutil.copytree(root, destination / 'evidence')
    archive = destination / 'download.zip'
    with zipfile.ZipFile(archive, 'w') as stream:
        for path in root.rglob('*'):
            if path.is_file():
                stream.write(path, path.relative_to(root))
    artifact = {'id': 1, 'name': row['artifact_name'], 'expired': False, 'workflow_run': {
        'id': run['id'], 'head_sha': run['head_sha']}, 'created_at': '2026-11-19T04:59:00Z',
        'digest': 'sha256:' + full.digest(archive), 'size_in_bytes': archive.stat().st_size}
    snapshots = tmp_path / 'api'
    snapshots.mkdir()
    for name, value in [('run', run), ('jobs', jobs), ('artifacts', {'total_count': 1, 'artifacts': [artifact]})]:
        full.write(snapshots / (name + '.json'), value)
    full.write(tmp_path / 'selection.json', selection)
    output = tmp_path / 'audit'
    output.mkdir()
    (output / 'branches').mkdir()
    store = full.BranchStore(output / 'branches', context[1])
    paths = {'selection': tmp_path / 'selection.json', 'snapshots': snapshots, 'cache': cache}
    return paths, validation, output, store, destination


def test_stage_rechecks_failed_job_zip_and_preserves_all_pending_controls(branch, context, first_plan, tmp_path):
    paths, validation, output, store, _ = stage_fixture(branch, context, tmp_path)
    result = full.verify_stage('controls', paths, context, first_plan, validation, output, store)
    assert not result['verification_errors'] and len(result['pending_partitions']) == 255
    assert len(store) == 7334 and sum(r['complete_diagnostic'] for r in store.index.values()) == 1
    checked = store[branch[1]['record_id']]
    assert checked['job_conclusion'] == 'timed_out' and checked['verified_arrays'] == 4
    assert checked['origin'] == context[1]['branch_origins'][branch[1]['record_id']]
    assert set(checked['windows']) == set(full.LABELS)


@pytest.mark.parametrize('change', ['zip', 'extracted', 'attempt', 'size'])
def test_stage_cannot_trust_modified_cached_evidence(branch, context, first_plan, tmp_path, change):
    paths, validation, output, store, destination = stage_fixture(branch, context, tmp_path)
    if change == 'zip':
        with (destination / 'download.zip').open('ab') as stream:
            stream.write(b'changed')
    elif change == 'extracted':
        (destination / 'evidence/execution.json').write_text('{}')
    elif change == 'attempt':
        jobs = full.read(paths['snapshots'] / 'jobs.json')
        next(j for j in jobs['jobs'] if j['status'] == 'completed' and j['name'] != 'validation')['run_attempt'] = 2
        full.write(paths['snapshots'] / 'jobs.json', jobs)
        with pytest.raises(ValueError):
            full.verify_stage('controls', paths, context, first_plan, validation, output, store)
        return
    else:
        artifacts = full.read(paths['snapshots'] / 'artifacts.json')
        artifacts['artifacts'][0]['size_in_bytes'] += 1
        full.write(paths['snapshots'] / 'artifacts.json', artifacts)
    result = full.verify_stage('controls', paths, context, first_plan, validation, output, store)
    assert result['verification_errors'] and not any(r['complete_diagnostic'] for r in store.index.values())


def replay_fixture(cube):
    plan, reference, config, branches, _ = cube
    inventory = {'branches': {bid: {} for bid in branches}, 'cases': {'case': {'original_plan': plan}},
                 'full_untreated_control': 'baseline'}
    branches['baseline'] = {'status': 'confirmed', 'windows': {}}
    inventory['branches']['baseline'] = {}
    original = full.case_math.replay_case(plan, reference, config, branches, full.case_math.PRIMARY)
    captured = {'case': {'case': {'trials': original['trials']}}}
    return inventory, branches, captured, reference, config


def test_replay_keeps_all_three_paths_and_uses_original_case_math(cube):
    args = replay_fixture(cube)
    baseline, cases = full.replay(*args)
    assert baseline and cases['case']['passed']
    assert cases['case']['primary_matches_original_path'] and cases['case']['refined_matches_original_path']
    assert len(cases['case']['primary_search']['trials']) == 4


def test_failed_unreached_control_still_prevents_recovery(cube):
    stop_after_first(cube)
    args = replay_fixture(cube)
    cube[3][cube[4]['third__C__up']['history_breaker_cue']]['status'] = 'mismatch'
    baseline, cases = full.replay(*args)
    assert baseline and cases['case']['primary_search']['passed']
    assert not cases['case']['passed']


def test_original_path_remains_distinct_after_new_replay(cube):
    args = replay_fixture(cube)
    stop_after_first(cube)
    _, cases = full.replay(*args)
    assert cases['case']['passed'] and not cases['case']['primary_matches_original_path']
    assert len(cases['case']['original_path']) == 4 and len(cases['case']['primary_search']['trials']) == 1


@pytest.mark.parametrize('change', ['missing_case', 'extra_case', 'missing_branch', 'extra_branch'])
def test_replay_requires_exact_case_and_branch_inventory(cube, change):
    args = replay_fixture(cube)
    if change == 'missing_case': args[2].clear()
    elif change == 'extra_case': args[2]['extra'] = args[2]['case']
    elif change == 'missing_branch': args[1].pop(next(iter(args[1])))
    else: args[1]['extra'] = {'status': 'confirmed', 'windows': {}}
    with pytest.raises(ValueError):
        full.replay(*args)


def test_store_rejects_duplicate_and_changed_audits(tmp_path):
    store = full.BranchStore(tmp_path, {'branches': {'a': {}}})
    row = {'record_id': 'a', 'complete_diagnostic': True, 'verified_arrays': 4, 'status': 'confirmed', 'windows': {}}
    store.add('a', row)
    with pytest.raises(ValueError): store.add('a', row)
    (tmp_path / 'a.json').write_text('{}')
    with pytest.raises(ValueError, match='changed'): store['a']


def test_unavailable_sources_keep_all_7334_branches_pending(context, first_plan, tmp_path, monkeypatch):
    monkeypatch.setattr(full, 'load_context', lambda: (context, first_plan))
    monkeypatch.setattr(full.producer.inputs, 'validate', lambda *a: {'synthetic_test_fixture': True})
    full.write(tmp_path / 'sources.json', dict.fromkeys(('published', 'diagnostics', 'controls')))
    result = full.audit(tmp_path / 'inputs', tmp_path / 'sources.json', tmp_path / 'output')
    assert result['status'] == 'incomplete' and not result['complete_selected_control_inventory']
    assert len(result['missing_or_incomplete_branches']) == 7334
    assert result['selected_cases'] == 74 and result['recovered_selected_cases'] == 0 and result['cases'] == {}
    assert result['verified_arrays'] == 0 and result['baseline_passed'] is None
    assert not result['full_model_coverage_claimed']


def test_existing_audit_is_not_overwritten(tmp_path):
    with pytest.raises(ValueError, match='new full-case audit'):
        full.audit(tmp_path, tmp_path / 'sources.json', tmp_path)


@pytest.mark.parametrize('missing_last', [False, True])
def test_complete_stage_wiring_requires_every_last_control(context, first_plan, tmp_path, monkeypatch, missing_last):
    """Synthetic audit summaries exercise orchestration; scoring has separate cube tests."""
    monkeypatch.setattr(full, 'load_context', lambda: (context, first_plan))
    monkeypatch.setattr(full.producer.inputs, 'validate', lambda *a: {'synthetic_test_fixture': True})
    selected = full.scope(context, first_plan)['branches']
    missing = next(reversed([bid for bid, row in selected.items() if row['stage'] == 'controls']))
    def insert(stage, store):
        for bid, row in selected.items():
            if row['stage'] == stage and not (missing_last and bid == missing):
                store.add(bid, {'record_id': bid, 'status': 'confirmed', 'complete_diagnostic': True,
                               'verified_arrays': 4, 'windows': {}, 'synthetic_test_fixture': True})
    def published(directory, ctx, store):
        insert('published', store)
        return {'status': 'synthetic_fixture'}
    def stage(name, paths, ctx, first, validation, output, store):
        insert(name, store)
        return {'verification_errors': [], 'status': 'synthetic_fixture'}
    calls = []
    def replay(inv, store, captured, reference, config):
        assert len(store) == 7334 and len(inv['cases']) == 74
        assert all(row['complete_diagnostic'] for row in store.index.values())
        calls.append(True)
        return True, {key: {'passed': True, 'synthetic_test_fixture': True} for key in inv['cases']}
    monkeypatch.setattr(full, 'verify_published', published)
    monkeypatch.setattr(full, 'verify_stage', stage)
    monkeypatch.setattr(full, 'replay', replay)
    monkeypatch.setattr(full, 'discrepancies', lambda *a: [])
    bundle = tmp_path / 'inputs'
    bundle.mkdir()
    full.write(bundle / 'original-cases.json', {})
    source = {'published': 'published', **{name: {'selection': name + '/selection.json',
        'snapshots': name + '/api', 'cache': name + '/cache'} for name in ('diagnostics', 'controls')}}
    full.write(tmp_path / 'sources.json', source)
    result = full.audit(bundle, tmp_path / 'sources.json', tmp_path / 'output')
    assert result['complete_branch_outcomes'] == 7334 - int(missing_last)
    assert result['complete_selected_control_inventory'] is not missing_last
    assert result['recovered_selected_cases'] == (0 if missing_last else 74)
    assert calls == ([] if missing_last else [True])
    assert result['missing_or_incomplete_branches'] == ([missing] if missing_last else [])


def test_original_summary_disagreements_keep_partition_identity(cube, tmp_path, monkeypatch):
    branch = next(iter(cube[3].values()))
    old = {'record_id': 'same', 'passed': True, 'windows': {'roadrunner': deepcopy(branch['windows']['roadrunner'])}}
    set_mean(branch, 'scipy_refined', 'prefix', 2.)
    store = full.BranchStore(tmp_path, {'branches': {'same': {}}})
    store.add('same', {**branch, 'record_id': 'same', 'complete_diagnostic': True, 'verified_arrays': 4})
    monkeypatch.setattr(full.producer.inputs, 'read_records', lambda path:
        {'same': old} if path.name in ('original-branches-00.jsonl.gz', 'original-branches-01.jsonl.gz') else {})
    result = full.discrepancies(tmp_path, store)
    assert [row['partition'] for row in result] == [0, 1]
    assert all(row['max_scaled_error'] > 1 and row['record_id'] == 'same' for row in result)


def test_published_top_level_identity_is_pinned(tmp_path, context):
    full.write(tmp_path / 'report.json', {'status': 'completed', 'branches': []})
    store = full.BranchStore(tmp_path, context[1])
    with pytest.raises(ValueError, match='Pinned published'):
        full.verify_published(tmp_path, context, store)


@pytest.mark.parametrize('protected', ['inputs', 'published', 'cache', 'api'])
def test_audit_output_cannot_modify_input_evidence(context, first_plan, tmp_path, monkeypatch, protected):
    monkeypatch.setattr(full, 'load_context', lambda: (context, first_plan))
    monkeypatch.setattr(full.producer.inputs, 'validate', lambda *a: {})
    full.write(tmp_path / 'sources.json', {'published': 'published', 'diagnostics': None,
        'controls': {'selection': 'selection.json', 'snapshots': 'api', 'cache': 'cache'}})
    with pytest.raises(ValueError, match='outside the input evidence'):
        full.audit(tmp_path / 'inputs', tmp_path / 'sources.json', tmp_path / protected / 'new-audit')
