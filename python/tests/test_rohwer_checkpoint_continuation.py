"""Full-grid preservation across two further checkpoint generations; no ODE runs."""
from copy import deepcopy
import shutil
import subprocess

import pytest

from scripts import continue_rohwer_checkpoint as c
from scripts import continue_rohwer_first as first
from test_rohwer_breaking_collection import branch, synthetic
from test_rohwer_first_continuation import setup_parent


def next_generation(parent, plan, checked, generation):
    hashes = {p.relative_to(parent).as_posix(): c.digest(p) for p in parent.rglob('*') if p.is_file()}
    rows = checked['branches']
    part = {'index': 0, 'parent_job_id': 123, 'parent_artifact_id': 456,
            'parent_archive_sha256': 'sha256:'+'a'*64, 'parent_execution_sha256': hashes['execution.json'],
            'parent_evidence_sha256': hashes, 'fixed_branch_ids': [b['record_id'] for b in rows],
            'preserve_complete_branch_ids': [b['record_id'] for b in rows if b['complete_diagnostic']],
            'resume_partial_branch_ids': [b['record_id'] for b in rows if b['status'] in c.RESUMABLE],
            'unattempted_branch_ids': [b['record_id'] for b in rows if b['status'] == 'not_started'],
            'parent_verified_arrays': checked['verified_arrays']}
    context = {'binding': {'generation': generation, 'parent_run_id': 1234},
               'binding_sha256': str(generation)*64, 'requirements': {'partitions': [part]}, 'plan': plan}
    output = parent.parent/f'generation-{generation}'
    c.initialize(parent, output, 0, plan, context)
    return output, context


def setup(branch, **kwargs):
    parent, plan, requirements, inputs = setup_parent(branch, **kwargs)
    checked = first.audit(parent, 0, plan, requirements, inputs)
    output, context = next_generation(parent, plan, checked, 2)
    return output, plan, context, inputs


def test_all_750_branches_bound_to_verified_generation():
    ctx = c.check_bindings(check_runtime=False)
    req = ctx['requirements']
    assert req['generation'] == 2 and req['fixed_branch_count'] == 750
    assert (req['terminal_diagnostics'], req['interrupted_diagnostics'], req['unstarted_diagnostics']) == (318, 61, 371)
    assert req['parent_arrays'] == 1369
    assert sum(len(p['fixed_branch_ids']) for p in req['partitions']) == 750
    assert ctx['binding']['parent_run_id'] == 44950774489


@pytest.mark.parametrize('file', ['binding.json', 'requirements.json', 'selection.json', 'api/jobs.json', 'api/artifacts.json'])
def test_modified_pinned_context_rejected(tmp_path, file):
    destination = tmp_path/'bindings'
    shutil.copytree(c.BINDINGS, destination)
    with (destination/file).open('a') as stream:
        stream.write(' ')
    with pytest.raises(ValueError, match='Pinned'):
        c.check_bindings(destination, check_runtime=False)


@pytest.mark.parametrize('terminal,arrays', [('confirmed', 4), ('mismatch', 4), ('failure', 3)])
def test_terminal_outcomes_preserved_through_two_generations(branch, monkeypatch, terminal, arrays):
    output, plan, ctx, inputs = setup(branch, terminal=terminal)
    original_run = c.subprocess.run
    def forbidden(*args, **kwargs):
        if '--branch' in args[0]:
            raise AssertionError('A terminal diagnostic was reexecuted')
        return original_run(*args, **kwargs)
    monkeypatch.setattr(c.subprocess, 'run', forbidden)
    assert c.compute(output, 0, plan, ctx, 10, inputs) == (0 if terminal == 'confirmed' else 2)
    checked = c.audit(output, 0, plan, ctx, inputs)
    assert checked['parent_arrays_preserved'] == arrays and checked['preserved_terminal_diagnostics'] == 1
    again, next_ctx = next_generation(output, plan, checked, 3)
    assert c.compute(again, 0, plan, next_ctx, 10, inputs) == (0 if terminal == 'confirmed' else 2)
    result = c.audit(again, 0, plan, next_ctx, inputs)
    assert result['complete_selected_diagnostics'] and result['parent_arrays_preserved'] == arrays
    for name, sha in next_ctx['requirements']['partitions'][0]['parent_evidence_sha256'].items():
        if name != 'execution.json':
            assert c.digest(again/name) == sha


def test_untouched_then_partial_requests_and_next_generation_empty_checkpoint(branch, monkeypatch):
    output, plan, ctx, inputs = setup(branch, partial=True, unattempted=True)
    calls = []
    original_run = c.subprocess.run
    def timeout(command, **kwargs):
        if '--branch' not in command:
            return original_run(command, **kwargs)
        calls.append(command)
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
    monkeypatch.setattr(c.subprocess, 'run', timeout)
    assert c.compute(output, 0, plan, ctx, 10, inputs) == 2
    part = ctx['requirements']['partitions'][0]
    assert [cmd[cmd.index('--branch')+1] for cmd in calls] == part['unattempted_branch_ids']+part['resume_partial_branch_ids']
    assert '--resume' not in calls[0] and '--resume' in calls[1]
    for cmd in calls:
        for key, value in c.producer.REQUESTS.items():
            assert cmd[cmd.index('--'+key.replace('_', '-'))+1] == str(value)
    checked = c.audit(output, 0, plan, ctx, inputs)
    assert checked['parent_arrays_preserved'] == 3 and not checked['complete_selected_diagnostics']
    again, next_ctx = next_generation(output, plan, checked, 3)
    assert c.audit(again, 0, plan, next_ctx, inputs)['parent_arrays_preserved'] == 3
    next_part = next_ctx['requirements']['partitions'][0]
    assert len(next_part['resume_partial_branch_ids']) == 2 and not next_part['unattempted_branch_ids']
    assert any(b['status'] == 'no_checkpoint' for b in checked['branches'])
    assert set(next_part['resume_partial_branch_ids']+next_part['unattempted_branch_ids']) == set(part['fixed_branch_ids'])


@pytest.mark.parametrize('mutation', ['array', 'request_metadata', 'partial_record', 'parent_execution',
                                     'ancestor', 'scope', 'work_order', 'source', 'run', 'complete_claim', 'generation'])
def test_corrupted_current_or_ancestor_evidence_rejected(branch, mutation):
    output, plan, ctx, inputs = setup(branch, partial=True, unattempted=True)
    bid = ctx['requirements']['partitions'][0]['resume_partial_branch_ids'][0]
    record_path = output/bid/(bid+'.json')
    record, execution = c.read(record_path), c.read(output/'execution.json')
    kwargs = {}
    if mutation == 'array':
        with (output/bid/record['traces']['roadrunner']['file']).open('ab') as stream: stream.write(b'bad')
    elif mutation == 'request_metadata':
        record['integrations']['roadrunner']['seconds'] = 999
        c.write(record_path, record)
    elif mutation in ('partial_record', 'parent_execution', 'ancestor'):
        path = {'partial_record': output/'generations/2'/(bid+'.json'),
                'parent_execution': output/'generations/2/parent-execution.json',
                'ancestor': output/'lineage/execution.json'}[mutation]
        with path.open('a') as stream: stream.write(' ')
    elif mutation == 'scope': execution['selected_branches'].pop()
    elif mutation == 'work_order': execution['work_order'].reverse()
    elif mutation == 'source': execution['runner_sha256'] = '0'*64
    elif mutation == 'run': kwargs['run_id'] = 'different'
    elif mutation == 'complete_claim': execution['status'] = 'completed'
    else: execution['generation'] += 1
    c.write(output/'execution.json', execution)
    with pytest.raises(ValueError): c.audit(output, 0, plan, ctx, inputs, **kwargs)


def test_repeated_compute_rejected(branch):
    output, plan, ctx, inputs = setup(branch)
    assert c.compute(output, 0, plan, ctx, 10, inputs) == 0
    with pytest.raises(ValueError, match='do not restart'):
        c.compute(output, 0, plan, ctx, 10, inputs)


def test_bad_original_archive_rejected_before_extract(tmp_path):
    ctx = c.check_bindings(check_runtime=False)
    path = tmp_path/'bad.zip'
    path.write_bytes(b'not the selected artifact')
    with pytest.raises(ValueError, match='Original ZIP differs'):
        c.verify_parent(path, tmp_path/'output', 0, ctx)
    assert not (tmp_path/'output').exists()


def test_workflow_preserves_full_scope_and_validation_gate():
    text = (c.ROOT.parent/'.github/workflows/rohwer-first-continuation.yml').read_text()
    assert 'continue_rohwer_checkpoint.py check' in text and 'needs: validation' in text
    assert 'index: ['+', '.join(map(str, range(32)))+']' in text
    assert 'test_rohwer_checkpoint_continuation.py' in text and 'test_rohwer_checkpoint_collection.py' in text
    assert 'retention-days: 90' in text and '--budget 19200' in text


@pytest.mark.parametrize('escape', [False, True])
def test_next_generation_binding_checks_parent_context_and_full_selection(tmp_path, monkeypatch, escape):
    from scripts import collect_rohwer_checkpoint as collector
    from test_rohwer_checkpoint_collection import fixture
    parent = c.check_bindings(check_runtime=False)
    plan, run, jobs = fixture()
    run['status'] = 'completed'
    for job in jobs['jobs']:
        job.update(status='completed', conclusion='success' if job['name'] == 'validation' else 'failure',
                   started_at='2026-11-24T06:00:00Z', completed_at='2026-11-24T07:00:00Z')
    selection = collector.bind(plan, run, jobs, run['head_sha'], parent)
    artifacts = {'total_count': 32, 'artifacts': []}
    requirements = deepcopy(parent['requirements'])
    requirements['generation'] = 3
    for row, part in zip(selection['selected'], requirements['partitions'], strict=True):
        artifact = {'id': 10000+row['index'], 'name': row['artifact_name'], 'expired': False,
                    'workflow_run': {'id': run['id'], 'head_sha': run['head_sha']},
                    'created_at': '2026-11-24T06:59:00Z', 'digest': 'sha256:'+'0'*64, 'size_in_bytes': 1}
        artifacts['artifacts'].append(artifact)
        part.update(parent_job_id=row['job_id'], parent_artifact_id=artifact['id'], parent_archive_sha256=artifact['digest'])
    shutil.copytree(c.BINDINGS, tmp_path/'parent')
    destination = tmp_path/'next'
    (destination/'api').mkdir(parents=True)
    for name, data in [('requirements.json', requirements), ('selection.json', selection),
                       ('api/run.json', run), ('api/jobs.json', jobs), ('api/artifacts.json', artifacts)]:
        c.write(destination/name, data)
    binding = {'schema_version': 1, 'generation': 3, 'parent_format': 'checkpoint',
               'parent_run_id': run['id'], 'parent_revision': run['head_sha'],
               'parent_context': {'path': '../outside' if escape else 'parent', 'sha256': c.BINDING_SHA},
               'files': {name: c.digest(destination/name) for name in
                         ('requirements.json', 'selection.json', 'api/run.json', 'api/jobs.json', 'api/artifacts.json')}}
    c.write(destination/'binding.json', binding)
    monkeypatch.setattr(c, 'ROOT', tmp_path)
    if escape:
        with pytest.raises(ValueError, match='escapes'):
            c.check_bindings(destination, c.digest(destination/'binding.json'), check_runtime=False)
    else:
        checked = c.check_bindings(destination, c.digest(destination/'binding.json'), check_runtime=False)
        assert checked['binding']['generation'] == 3
        assert checked['parent']['binding_sha256'] == c.BINDING_SHA
        assert checked['requirements']['fixed_branch_count'] == 750


def test_cyclic_binding_ancestry_rejected():
    with pytest.raises(ValueError, match='Cyclic'):
        c.check_bindings(check_runtime=False, seen=(c.BINDING_SHA,))
