"""Resume all 750 Rohwer diagnostics through explicitly pinned checkpoint generations.

Only orchestration changes. Terminal outcomes, including numerical failures,
completed request metadata, arrays and earlier lineage remain byte-identical.
The frozen numerical producer retains every original request and full grid.
"""
import argparse
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import continue_rohwer_first as first
from scripts import collect_rohwer_first_continuation as first_collector
from scripts.run_rohwer_breaking_diagnostics import digest, read, require, write

original, producer, INPUTS = first.original, first.producer, first.INPUTS
BINDINGS = ROOT/'results/catalog-breaking-rohwer-checkpoint-continuation-20261124'
BINDING_SHA = 'ac2be132f47739184dccdb9a6efcdeb8853710d8f8ac4390be231029296089f4'
SCRIPT = 'scripts/continue_rohwer_checkpoint.py'
RESUMABLE = {'interrupted', 'no_checkpoint', 'no_report'}


@lru_cache(None)
def source_hash(revision):
    return hashlib.sha256(subprocess.check_output(['git', 'show', revision+':python/'+SCRIPT], cwd=ROOT)).hexdigest()


def check_bindings(bindings=BINDINGS, binding_sha=BINDING_SHA, *, check_runtime=True, seen=()):
    require(binding_sha not in seen and len(seen) < 32, 'Cyclic or excessive checkpoint ancestry')
    require(not (bindings/'binding.json').is_symlink() and digest(bindings/'binding.json') == binding_sha,
            'Pinned checkpoint binding differs')
    binding = read(bindings/'binding.json')
    require(binding['schema_version'] == 1 and type(binding['generation']) is int
            and binding['generation'] >= 2, 'Unsupported checkpoint generation')
    require(set(binding['files']) == {'requirements.json', 'selection.json', 'api/run.json',
                                     'api/jobs.json', 'api/artifacts.json'}, 'Binding file inventory differs')
    for name, sha in binding['files'].items():
        require(not (bindings/name).is_symlink() and digest(bindings/name) == sha, 'Pinned parent file differs: '+name)
    plan, first_requirements, _, _ = first.check_bindings(check_runtime=check_runtime)
    run, jobs, artifacts = (read(bindings/'api'/(name+'.json')) for name in ('run', 'jobs', 'artifacts'))
    selection, requirements = read(bindings/'selection.json'), read(bindings/'requirements.json')
    require(run['id'] == binding['parent_run_id'] and run['head_sha'] == binding['parent_revision']
            and run['status'] == 'completed', 'Parent run identity or terminal state differs')
    parent = None
    if binding['parent_format'] == 'first_continuation':
        require(binding['generation'] == 2 and binding['parent_context'] is None, 'First continuation ancestry differs')
        require(first_collector.bind(plan, run, jobs, binding['parent_revision']) == selection, 'Parent job selection differs')
        validate_artifact = first_collector.validate_artifact
    else:
        require(binding['parent_format'] == 'checkpoint', 'Unknown parent format')
        parent_ref = binding['parent_context']
        parent_path = (ROOT/parent_ref['path']).resolve()
        require(parent_path.is_relative_to(ROOT.resolve()), 'Parent context escapes source tree')
        parent = check_bindings(parent_path, parent_ref['sha256'], check_runtime=False, seen=(*seen, binding_sha))
        require(parent['binding']['generation']+1 == binding['generation'], 'Generation sequence differs')
        from scripts import collect_rohwer_checkpoint as collector
        require(collector.bind(plan, run, jobs, binding['parent_revision'], parent) == selection, 'Parent job selection differs')
        validate_artifact = collector.validate_artifact
    require(requirements['generation'] == binding['generation'] and requirements['fixed_branch_count'] == 750
            and requirements['partition_count'] == 32, 'Full diagnostic scope differs')
    parts = requirements['partitions']
    require([p['index'] for p in parts] == list(range(32)), 'All original partitions required')
    require(artifacts['total_count'] == len(artifacts['artifacts']) == 32, 'All parent artifacts required')
    for part, row in zip(parts, selection['selected'], strict=True):
        matches = [j for j in jobs['jobs'] if j['id'] == row['job_id']]
        saved = [a for a in artifacts['artifacts'] if a['id'] == part['parent_artifact_id']]
        require(len(matches) == len(saved) == 1, 'Ambiguous parent identity')
        validate_artifact(row, run, matches[0], saved[0])
        require(part['parent_job_id'] == row['job_id'] and part['parent_archive_sha256'] == saved[0]['digest'],
                'Parent artifact binding differs')
        expected = [b['record_id'] for b in plan['partitions'][part['index']]['branches']]
        require(part['fixed_branch_ids'] == expected == [b['record_id'] for b in row['branches']], 'Original branch selection differs')
        groups = sum((part[k] for k in ('preserve_complete_branch_ids', 'resume_partial_branch_ids', 'unattempted_branch_ids')), [])
        require(len(groups) == len(set(groups)) and set(groups) == set(expected), 'Omitted or duplicated branch')
    for field, group in [('terminal_diagnostics', 'preserve_complete_branch_ids'),
                         ('interrupted_diagnostics', 'resume_partial_branch_ids'), ('unstarted_diagnostics', 'unattempted_branch_ids')]:
        require(requirements[field] == sum(len(p[group]) for p in parts), 'Checkpoint outcome count differs')
    require(requirements['parent_arrays'] == sum(p['parent_verified_arrays'] for p in parts), 'Parent array count differs')
    return {'binding': binding, 'binding_sha256': binding_sha, 'requirements': requirements,
            'plan': plan, 'selection': selection, 'artifacts': artifacts, 'parent': parent,
            'first_requirements': first_requirements}


def check_index(index):
    first.check_index(index)


def verify_parent(archive, evidence, index, context, inputs=INPUTS):
    check_index(index)
    part = context['requirements']['partitions'][index]
    artifact = next(a for a in context['artifacts']['artifacts'] if a['id'] == part['parent_artifact_id'])
    require(not archive.is_symlink() and archive.stat().st_size == artifact['size_in_bytes']
            and digest(archive) == artifact['digest'].removeprefix('sha256:'), 'Original ZIP differs')
    require(original.verify_zip(archive, evidence, extract=True) == part['parent_evidence_sha256'],
            'Original parent file inventory differs')
    binding = context['binding']
    kwargs = {'revision': binding['parent_revision'], 'run_id': str(binding['parent_run_id']), 'run_attempt': '1'}
    if binding['parent_format'] == 'first_continuation':
        checked = first.audit(evidence, index, context['plan'], context['first_requirements'], inputs, **kwargs)
    else:
        checked = audit(evidence, index, context['plan'], context['parent'], inputs, **kwargs)
    require(checked['execution_sha256'] == part['parent_execution_sha256'], 'Parent execution differs')
    for key, rows in [('preserve_complete_branch_ids', [b for b in checked['branches'] if b['complete_diagnostic']]),
                      ('resume_partial_branch_ids', [b for b in checked['branches'] if b['status'] in RESUMABLE]),
                      ('unattempted_branch_ids', [b for b in checked['branches'] if b['status'] == 'not_started'])]:
        require(part[key] == [b['record_id'] for b in rows], 'Reaudited parent outcomes differ')
    require(checked['verified_arrays'] == part['parent_verified_arrays']
            and not any(b.get('unverified_arrays') for b in checked['branches']), 'Parent arrays differ')
    return checked


def generation_directory(directory, context):
    return directory/'generations'/str(context['binding']['generation'])


def preservation(directory, part, context):
    hashes = part['parent_evidence_sha256']
    lineage = generation_directory(directory, context)
    require(digest(lineage/'parent-execution.json') == part['parent_execution_sha256'], 'Parent execution bytes changed')
    partial = [bid for bid in part['resume_partial_branch_ids'] if bid+'/'+bid+'.json' in hashes]
    expected = {'parent-execution.json'} | {bid+'.json' for bid in partial}
    require({p.name for p in lineage.iterdir()} == expected, 'Current lineage inventory differs')
    ancestors = {name: sha for name, sha in hashes.items() if name.split('/')[0] in ('lineage', 'generations')}
    actual_ancestors = {p.relative_to(directory).as_posix() for top in ('lineage', 'generations')
                        for p in (directory/top).rglob('*') if p.is_file() and not p.is_relative_to(lineage)}
    require(actual_ancestors == set(ancestors), 'Ancestor lineage inventory differs')
    for name, sha in ancestors.items():
        require(digest(directory/name) == sha, 'Ancestor lineage bytes changed')
    complete = set(part['preserve_complete_branch_ids'])
    arrays = 0
    for name, sha in hashes.items():
        if name.split('/')[0] in complete:
            path = directory/name
            require(path.is_file() and not path.is_symlink() and digest(path) == sha, 'Terminal diagnostic changed: '+name)
            arrays += int(name.endswith('.npz'))
    for bid in partial:
        require(digest(lineage/(bid+'.json')) == hashes[bid+'/'+bid+'.json'], 'Partial checkpoint bytes changed')
        parent, current = read(lineage/(bid+'.json')), read(directory/bid/(bid+'.json'))
        for key in ('fingerprint', 'record_id', 'specification', 'case_recovery_claimed'):
            require(current[key] == parent[key], 'Partial branch identity changed')
        for label, saved in parent['traces'].items():
            require(parent['integrations'][label]['completed'] is True, 'Parent trace is incomplete')
            require(current['traces'].get(label) == saved and current['integrations'].get(label) == parent['integrations'][label],
                    'Completed parent request metadata changed')
            path = directory/bid/saved['file']
            require(path.is_file() and not path.is_symlink() and digest(path) == saved['sha256'] == hashes[bid+'/'+saved['file']],
                    'Completed parent array changed')
            arrays += 1
    require(arrays == part['parent_verified_arrays'], 'Not every parent array was preserved')
    return arrays


def initialize(evidence, output, index, plan, context):
    require(not output.exists(), 'Use a new continuation output')
    part, binding = context['requirements']['partitions'][index], context['binding']
    shutil.copytree(evidence, output)
    lineage = generation_directory(output, context)
    lineage.mkdir(parents=True, exist_ok=False)
    (output/'execution.json').rename(lineage/'parent-execution.json')
    parent = read(lineage/'parent-execution.json')
    for bid in part['resume_partial_branch_ids']:
        if bid+'/'+bid+'.json' in part['parent_evidence_sha256']:
            shutil.copyfile(output/bid/(bid+'.json'), lineage/(bid+'.json'))
    by_id = {b['record_id']: b for b in parent['branches']}
    execution = {'schema_version': 2, 'generation': binding['generation'], 'binding_sha256': context['binding_sha256'],
        'model_id': producer.MODEL, 'plan_sha256': original.PLAN_SHA, 'partition_index': index,
        'selected_branches': plan['partitions'][index]['branches'], 'runtime': plan['runtime'],
        'parent_run_id': binding['parent_run_id'], 'parent_job_id': part['parent_job_id'],
        'parent_artifact_id': part['parent_artifact_id'], 'parent_archive_sha256': part['parent_archive_sha256'],
        'producer_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'runner_sha256': digest(Path(__file__)), 'run_id': os.environ.get('GITHUB_RUN_ID'),
        'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'), 'preserved_terminal_ids': part['preserve_complete_branch_ids'],
        'work_order': part['unattempted_branch_ids']+part['resume_partial_branch_ids'], 'attempted_now': [],
        'status': 'prepared', 'case_recovery_claimed': False, 'full_model_coverage_claimed': False,
        'started_at': datetime.now(timezone.utc).isoformat(),
        'branches': [by_id.get(b['record_id'], {**b, 'status': 'not_started'}) for b in plan['partitions'][index]['branches']]}
    execution['parent_arrays_preserved'] = preservation(output, part, context)
    write(output/'execution.json', execution)
    return execution


def audit(directory, index, plan, context, inputs=INPUTS, *, revision=None, run_id=None, run_attempt=None):
    check_index(index)
    part, binding = context['requirements']['partitions'][index], context['binding']
    expected = plan['partitions'][index]['branches']
    execution = read(directory/'execution.json')
    require(execution['schema_version'] == 2 and execution['generation'] == binding['generation']
            and execution['binding_sha256'] == context['binding_sha256'] and execution['model_id'] == producer.MODEL
            and execution['plan_sha256'] == original.PLAN_SHA and execution['partition_index'] == index
            and execution['selected_branches'] == expected and execution['runtime'] == plan['runtime']
            and execution['case_recovery_claimed'] is False and execution['full_model_coverage_claimed'] is False,
            'Checkpoint continuation scope or runtime differs')
    require(execution['parent_run_id'] == binding['parent_run_id']
            and all(execution[k] == part[k] for k in ('parent_job_id', 'parent_artifact_id', 'parent_archive_sha256')),
            'Parent identity differs')
    require(execution['runner_sha256'] == (source_hash(revision) if revision else digest(Path(__file__))), 'Checkpoint runner differs')
    for key, value in [('producer_revision', revision), ('run_id', run_id), ('run_attempt', run_attempt)]:
        if value is not None:
            require(execution[key] == value, 'Selected continuation '+key+' differs')
    order = part['unattempted_branch_ids']+part['resume_partial_branch_ids']
    attempted = execution['attempted_now']
    require(execution['preserved_terminal_ids'] == part['preserve_complete_branch_ids']
            and execution['work_order'] == order and attempted == order[:len(attempted)], 'Continuation scheduling differs')
    entries = execution['branches']
    require([{k: e[k] for k in ('record_id', 'source_partition', 'sample_count')} for e in entries] == expected,
            'Original partition membership differs')
    parent = {b['record_id']: b for b in read(generation_directory(directory, context)/'parent-execution.json')['branches']}
    rows = []
    allowed = {'running', 'confirmed', 'numerical_failure', 'time_limit', 'execution_or_audit_failure', 'not_started'}
    for row, entry in zip(expected, entries, strict=True):
        bid = row['record_id']
        require(entry['status'] in allowed, 'Unknown branch outcome')
        if bid not in attempted:
            require(entry == parent.get(bid, {**row, 'status': 'not_started'}), 'Unattempted outcome changed')
        rows.append(original.verify_branch(directory/bid, row, None if entry['status'] == 'not_started' else entry, inputs, plan))
    arrays = preservation(directory, part, context)
    require(execution['parent_arrays_preserved'] == arrays, 'Parent array count differs')
    require({p.name for p in directory.iterdir()} <= {'execution.json', 'lineage', 'generations'} | set(part['fixed_branch_ids']),
            'Unexpected continuation evidence')
    require(all(not p.is_symlink() for p in directory.rglob('*')), 'Symlink in continuation evidence')
    complete = all(b['complete_diagnostic'] for b in rows)
    confirmed = sum(b['complete_diagnostic'] and b['status'] == 'confirmed' for b in rows)
    require(execution['status'] in ('prepared', 'running', 'completed', 'incomplete'), 'Unknown execution status')
    require(execution['status'] != 'completed' or complete, 'False partition completion claim')
    status = 'diagnostics_confirmed' if complete and confirmed == len(expected) else (
        'complete_with_numerical_failures' if complete else 'incomplete')
    return {'status': status, 'partition_index': index, 'generation': binding['generation'],
        'complete_selected_diagnostics': complete, 'confirmed_branches': confirmed,
        'verified_arrays': sum(b['verified_arrays'] for b in rows), 'parent_arrays_preserved': arrays,
        'preserved_terminal_diagnostics': len(part['preserve_complete_branch_ids']), 'branches': rows,
        'execution_sha256': digest(directory/'execution.json'), 'numerical_integrations_performed': 0,
        'case_recovery_claimed': False, 'full_model_coverage_claimed': False}


def compute(output, index, plan, context, budget, inputs=INPUTS):
    require(0 < budget <= 19200, 'Invalid execution budget')
    audit(output, index, plan, context, inputs)
    execution = read(output/'execution.json')
    require(execution['status'] == 'prepared' and execution['attempted_now'] == [],
            'Use a new verified parent continuation; do not restart this execution')
    entries = {b['record_id']: b for b in execution['branches']}
    deadline = time.monotonic()+budget
    for bid in execution['work_order']:
        if time.monotonic() >= deadline:
            break
        entry = entries[bid]
        directory = output/bid
        command = [sys.executable, str(ROOT/'scripts/diagnose_scipy_breaking.py'),
                   '--evidence', str((inputs/f'source-partition-{entry["source_partition"]:02d}.json').resolve()),
                   '--branch', bid, '--output', str(directory.resolve())]
        if directory.exists():
            command.append('--resume')
        for key, value in producer.REQUESTS.items():
            command.extend(['--'+key.replace('_', '-'), str(value)])
        entry.clear()
        entry.update(next(b for b in plan['partitions'][index]['branches'] if b['record_id'] == bid), status='running')
        execution['attempted_now'].append(bid)
        execution['status'] = 'running'
        write(output/'execution.json', execution)
        try:
            result = subprocess.run(command, cwd=ROOT, timeout=max(.001, deadline-time.monotonic()))
            require(result.returncode == 0, f'Diagnostic process exited {result.returncode}')
            checked = original.auditor.audit(directory)
            write(directory/'audit.json', checked)
            entry.update(status='confirmed' if checked['all_selected_branches_confirmed'] else 'numerical_failure',
                         audit_sha256=digest(directory/'audit.json'), report_sha256=digest(directory/'report.json'))
        except subprocess.TimeoutExpired:
            entry.update(status='time_limit', error='Execution budget exhausted; partial files retained')
        except Exception as error:
            entry.update(status='execution_or_audit_failure', error=f'{type(error).__name__}: {error}')
        write(output/'execution.json', execution)
        print({'record_id': bid, 'status': entry['status']}, flush=True)
    checked = audit(output, index, plan, context, inputs)
    execution.update(status='completed' if checked['complete_selected_diagnostics'] else 'incomplete',
                     finished_at=datetime.now(timezone.utc).isoformat())
    write(output/'execution.json', execution)
    return 0 if checked['status'] == 'diagnostics_confirmed' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['check', 'restore', 'compute', 'audit', 'artifact'])
    parser.add_argument('--bindings', type=Path, default=BINDINGS)
    parser.add_argument('--binding-sha', default=BINDING_SHA)
    parser.add_argument('--index', type=int)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--audit-output', type=Path)
    parser.add_argument('--budget', type=float, default=19200)
    parser.add_argument('--revision')
    parser.add_argument('--run-id')
    parser.add_argument('--run-attempt')
    args = parser.parse_args()
    context = check_bindings(args.bindings, args.binding_sha)
    plan, requirements = context['plan'], context['requirements']
    if args.operation == 'check':
        print({k: requirements[k] for k in ('generation', 'fixed_branch_count', 'terminal_diagnostics',
                                          'interrupted_diagnostics', 'unstarted_diagnostics', 'parent_arrays')})
        return 0
    check_index(args.index)
    if args.operation == 'artifact':
        print(requirements['partitions'][args.index]['parent_artifact_id'])
        return 0
    require(args.output is not None, 'Output directory required')
    if args.operation == 'restore':
        require(args.archive is not None and not args.output.exists(), 'Original ZIP and new output required')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='rohwer-generation-parent-', dir=args.output.parent) as tmp:
            evidence = Path(tmp)/'evidence'
            verify_parent(args.archive, evidence, args.index, context)
            initialize(evidence, args.output, args.index, plan, context)
        audit(args.output, args.index, plan, context)
        return 0
    if args.operation == 'compute':
        return compute(args.output, args.index, plan, context, args.budget)
    require(args.audit_output is not None and not args.audit_output.exists(), 'New audit output required')
    result = audit(args.output, args.index, plan, context, revision=args.revision,
                   run_id=args.run_id, run_attempt=args.run_attempt)
    write(args.audit_output, result)
    print({k: result[k] for k in ('status', 'partition_index', 'confirmed_branches',
                                 'verified_arrays', 'parent_arrays_preserved')})
    return 0


if __name__ == '__main__':
    sys.exit(main())
