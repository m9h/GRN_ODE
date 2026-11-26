"""Continue the fixed first Rohwer run without reexecuting terminal diagnostics.

Only orchestration changes. Original numerical sources, requests, full grids,
partition membership and acceptance thresholds remain frozen. Complete parent
arrays and terminal failures are checked before and after computation.
"""

import argparse
from datetime import datetime, timezone
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

from scripts import collect_rohwer_breaking_diagnostics as original
from scripts import run_rohwer_breaking_diagnostics as producer
from scripts.run_rohwer_breaking_diagnostics import digest, read, require, write

INPUTS = ROOT/'results/catalog-breaking-rohwer-diagnostics-20261118'
BINDINGS = ROOT/'results/catalog-breaking-rohwer-first-continuation-20261121'
PINNED = {
    'continuation-requirements.json': '3e70ac005ee49bd004e7d07558183b911935b0c2e8ef99d4d0bbc8a7eedabfb9',
    'selection.json': '36b8ddf3dcb8faf32f78dd972fa44535725509cbdeac60db1fab7b5a2a108057',
    'api/run.json': 'ea26f8f7b9771b711a07c0d458ece191f306472ec1e3215c6258327f2dc8645b',
    'api/jobs.json': 'dffabcb5738c744432b3f0e3b0fdfe359d0cc80cb5a151a9dfcf9900042a0b65',
    'api/artifacts.json': '78c475c1ff69c838ec4644ba9bae7fd9e46916aac9e79120cdc2e4b4b0c90e53',
}


def check_bindings(bindings=BINDINGS, inputs=INPUTS, *, check_runtime=True):
    for name, sha in PINNED.items():
        require(not (bindings/name).is_symlink() and digest(bindings/name) == sha,
                'Pinned parent evidence differs: '+name)
    plan = producer.check(inputs, original.PLAN_SHA, check_runtime=check_runtime)
    selection = read(bindings/'selection.json')
    run, jobs, artifacts = (read(bindings/'api'/(n+'.json')) for n in ('run', 'jobs', 'artifacts'))
    require(original.bind_selection(plan, run, jobs) == selection, 'Original job bindings differ')
    require(artifacts['total_count'] == len(artifacts['artifacts']) == 32, 'All parent artifacts required')
    requirements = read(bindings/'continuation-requirements.json')
    require(requirements['parent_selection_sha256'] == PINNED['selection.json']
            and requirements['original_full_branch_count'] == 750
            and requirements['original_partitions'] == 32
            and requirements['all_completed_parent_arrays_to_preserve'] == 715,
            'Parent scope differs')
    require([p['index'] for p in requirements['partitions']] == list(range(32)), 'All partitions required')
    for part, row in zip(requirements['partitions'], selection['selected'], strict=True):
        job = next(j for j in jobs['jobs'] if j['id'] == row['job_id'])
        artifact = next(a for a in artifacts['artifacts'] if a['id'] == part['parent_artifact_id'])
        original.validate_artifact(row, run, job, artifact)
        require(part['parent_job_id'] == job['id'] and part['parent_archive_sha256'] == artifact['digest'],
                'Parent artifact binding differs')
        require(part['fixed_branch_ids'] == [b['record_id'] for b in row['branches']], 'Full branch scope differs')
        groups = [part[k] for k in ('preserve_complete_branch_ids', 'resume_partial_branch_ids',
                                   'unattempted_branch_ids')]
        combined = sum(groups, [])
        require(len(combined) == len(set(combined)) and set(combined) == set(part['fixed_branch_ids']),
                'Continuation omits or duplicates branches')
    require([sum(len(p[k]) for p in requirements['partitions']) for k in
             ('preserve_complete_branch_ids', 'resume_partial_branch_ids', 'unattempted_branch_ids')]
            == [166, 32, 552], 'Preserved failure or continuation inventory differs')
    return plan, requirements, selection, artifacts


def check_index(index):
    require(type(index) is int and 0 <= index < 32, 'Invalid partition index')


def verify_parent(archive, evidence, index, plan, requirements, selection, artifacts, inputs=INPUTS):
    check_index(index)
    part, row = requirements['partitions'][index], selection['selected'][index]
    artifact = next(a for a in artifacts['artifacts'] if a['id'] == part['parent_artifact_id'])
    require(not archive.is_symlink() and archive.stat().st_size == artifact['size_in_bytes']
            and digest(archive) == artifact['digest'].removeprefix('sha256:'), 'Original ZIP differs')
    files = original.verify_zip(archive, evidence, extract=True)
    require(files == part['parent_evidence_sha256'], 'Original extracted file inventory differs')
    runner = hashlib.sha256(subprocess.check_output(['git', 'show', original.RUN['head_sha']+
        ':python/scripts/run_rohwer_breaking_diagnostics.py'], cwd=ROOT)).hexdigest()
    checked = original.verify_partition(evidence, row, inputs, plan, runner)
    require(checked['execution_sha256'] == part['parent_execution_sha256'], 'Parent execution differs')
    groups = {
        'preserve_complete_branch_ids': [b['record_id'] for b in checked['branches'] if b['complete_diagnostic']],
        'resume_partial_branch_ids': [b['record_id'] for b in checked['branches'] if b['status'] == 'interrupted'],
        'unattempted_branch_ids': [b['record_id'] for b in checked['branches'] if b['status'] == 'not_started'],
    }
    require(all(part[k] == v for k, v in groups.items()), 'Reaudited parent outcomes differ')
    require(not any(b.get('unverified_arrays') for b in checked['branches']), 'Unverified parent array')
    return checked


def preservation(directory, part):
    """Check every terminal byte and completed partial array plus its provenance."""
    hashes = part['parent_evidence_sha256']
    lineage = directory/'lineage'
    require(digest(lineage/'execution.json') == part['parent_execution_sha256'], 'Parent execution bytes changed')
    expected_lineage = {'execution.json'} | {b+'.json' for b in part['resume_partial_branch_ids']}
    require({p.name for p in lineage.iterdir()} == expected_lineage, 'Lineage inventory differs')
    for path in lineage.iterdir():
        require(path.is_file() and not path.is_symlink(), 'Unsafe lineage file')
    complete = set(part['preserve_complete_branch_ids'])
    preserved_arrays = 0
    for name, sha in hashes.items():
        bid = name.split('/')[0]
        if bid in complete:
            path = directory/name
            require(path.is_file() and not path.is_symlink() and digest(path) == sha,
                    'Terminal parent diagnostic changed: '+name)
            preserved_arrays += int(name.endswith('.npz'))
    for bid in part['resume_partial_branch_ids']:
        parent_path = lineage/(bid+'.json')
        require(digest(parent_path) == hashes[bid+'/'+bid+'.json'], 'Partial parent record changed')
        parent, current = read(parent_path), read(directory/bid/(bid+'.json'))
        for key in ('fingerprint', 'record_id', 'specification', 'case_recovery_claimed'):
            require(current[key] == parent[key], 'Partial branch identity changed')
        for label, saved in parent['traces'].items():
            require(parent['integrations'][label]['completed'] is True, 'Parent trace is incomplete')
            require(current['traces'].get(label) == saved
                    and current['integrations'].get(label) == parent['integrations'][label],
                    'Completed parent request metadata changed')
            path = directory/bid/saved['file']
            require(path.is_file() and not path.is_symlink()
                    and digest(path) == saved['sha256'] == hashes[bid+'/'+saved['file']],
                    'Completed parent array changed')
            preserved_arrays += 1
    return preserved_arrays


def initialize(evidence, output, index, plan, requirements):
    """Called only after the complete original partition has been reaudited."""
    require(not output.exists(), 'Use a new continuation output')
    part = requirements['partitions'][index]
    shutil.copytree(evidence, output)
    (output/'lineage').mkdir()
    (output/'execution.json').rename(output/'lineage/execution.json')
    parent = read(output/'lineage/execution.json')
    for bid in part['resume_partial_branch_ids']:
        shutil.copyfile(output/bid/(bid+'.json'), output/'lineage'/(bid+'.json'))
    by_id = {b['record_id']: b for b in parent['branches']}
    # Untouched work goes first so the previously slow request cannot prevent all
    # other branches in its partition from ever being attempted. Scope is fixed.
    order = part['unattempted_branch_ids'] + part['resume_partial_branch_ids']
    execution = {
        'schema_version': 1, 'model_id': producer.MODEL, 'plan_sha256': original.PLAN_SHA,
        'parent_requirements_sha256': PINNED['continuation-requirements.json'],
        'partition_index': index, 'selected_branches': plan['partitions'][index]['branches'],
        'parent_run_id': original.RUN['id'], 'parent_job_id': part['parent_job_id'],
        'parent_artifact_id': part['parent_artifact_id'], 'parent_archive_sha256': part['parent_archive_sha256'],
        'producer_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'runner_sha256': digest(Path(__file__)), 'runtime': plan['runtime'],
        'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'preserved_terminal_ids': part['preserve_complete_branch_ids'], 'work_order': order,
        'attempted_now': [], 'status': 'prepared', 'case_recovery_claimed': False,
        'full_model_coverage_claimed': False, 'started_at': datetime.now(timezone.utc).isoformat(),
        'branches': [by_id.get(b['record_id'], {**b, 'status': 'not_started'})
                     for b in plan['partitions'][index]['branches']],
    }
    execution['parent_arrays_preserved'] = preservation(output, part)
    write(output/'execution.json', execution)
    return execution


def audit(directory, index, plan, requirements, inputs=INPUTS, *, revision=None, run_id=None, run_attempt=None):
    check_index(index)
    part, expected = requirements['partitions'][index], plan['partitions'][index]['branches']
    execution = read(directory/'execution.json')
    require(execution['schema_version'] == 1 and execution['model_id'] == producer.MODEL
            and execution['plan_sha256'] == original.PLAN_SHA
            and execution['parent_requirements_sha256'] == PINNED['continuation-requirements.json']
            and execution['partition_index'] == index and execution['selected_branches'] == expected
            and execution['runtime'] == plan['runtime'] and execution['case_recovery_claimed'] is False
            and execution['full_model_coverage_claimed'] is False, 'Continuation scope or runtime differs')
    require(execution['parent_run_id'] == original.RUN['id']
            and all(execution[k] == part[k] for k in ('parent_job_id', 'parent_artifact_id', 'parent_archive_sha256')),
            'Parent lineage differs')
    require(execution['runner_sha256'] == digest(Path(__file__)), 'Continuation runner differs')
    for key, value in (('producer_revision', revision), ('run_id', run_id), ('run_attempt', run_attempt)):
        if value is not None:
            require(execution[key] == value, 'Selected continuation '+key+' differs')
    order = part['unattempted_branch_ids'] + part['resume_partial_branch_ids']
    attempted = execution['attempted_now']
    require(execution['preserved_terminal_ids'] == part['preserve_complete_branch_ids']
            and execution['work_order'] == order and attempted == order[:len(attempted)],
            'Continuation scheduling or preserved terminal scope differs')
    entries = execution['branches']
    require([{k: e[k] for k in ('record_id', 'source_partition', 'sample_count')} for e in entries] == expected,
            'Original complete partition membership differs')
    parent = {e['record_id']: e for e in read(directory/'lineage/execution.json')['branches']}
    rows = []
    allowed = {'running', 'confirmed', 'numerical_failure', 'time_limit', 'execution_or_audit_failure', 'not_started'}
    for row, entry in zip(expected, entries, strict=True):
        bid = row['record_id']
        require(entry['status'] in allowed, 'Unknown branch outcome')
        if bid not in attempted:
            require(entry == parent.get(bid, {**row, 'status': 'not_started'}), 'Unattempted outcome changed')
        rows.append(original.verify_branch(directory/bid, row,
                    None if entry['status'] == 'not_started' else entry, inputs, plan))
    arrays = preservation(directory, part)
    require(execution['parent_arrays_preserved'] == arrays, 'Parent array count differs')
    require({p.name for p in directory.iterdir()} <= {'execution.json', 'lineage'} | set(part['fixed_branch_ids']),
            'Unexpected continuation evidence')
    require(all(not p.is_symlink() for p in directory.rglob('*')), 'Symlink in continuation evidence')
    complete = all(b['complete_diagnostic'] for b in rows)
    confirmed = sum(b['complete_diagnostic'] and b['status'] == 'confirmed' for b in rows)
    status = 'diagnostics_confirmed' if complete and confirmed == len(expected) else (
        'complete_with_numerical_failures' if complete else 'incomplete')
    require(execution['status'] in ('prepared', 'running', 'completed', 'incomplete'), 'Unknown execution status')
    if execution['status'] == 'completed':
        require(complete, 'False partition completion claim')
    return {'status': status, 'partition_index': index, 'complete_selected_diagnostics': complete,
            'confirmed_branches': confirmed, 'verified_arrays': sum(b['verified_arrays'] for b in rows),
            'parent_arrays_preserved': arrays, 'preserved_terminal_diagnostics': len(part['preserve_complete_branch_ids']),
            'branches': rows, 'execution_sha256': digest(directory/'execution.json'),
            'numerical_integrations_performed': 0, 'case_recovery_claimed': False,
            'full_model_coverage_claimed': False}


def compute(output, index, plan, requirements, budget, inputs=INPUTS):
    require(0 < budget <= 19200, 'Invalid execution budget')
    audit(output, index, plan, requirements, inputs)
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
    checked = audit(output, index, plan, requirements, inputs)
    execution.update(status='completed' if checked['complete_selected_diagnostics'] else 'incomplete',
                     finished_at=datetime.now(timezone.utc).isoformat())
    write(output/'execution.json', execution)
    return 0 if checked['status'] == 'diagnostics_confirmed' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['check', 'restore', 'compute', 'audit', 'artifact'])
    parser.add_argument('--index', type=int)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--audit-output', type=Path)
    parser.add_argument('--budget', type=float, default=19200)
    parser.add_argument('--revision')
    parser.add_argument('--run-id')
    parser.add_argument('--run-attempt')
    args = parser.parse_args()
    plan, requirements, selection, artifacts = check_bindings()
    if args.operation == 'check':
        print({'fixed_branches': 750, 'terminal_to_preserve': 166, 'partial': 32, 'unattempted': 552,
               'parent_arrays': 715, 'numerical_integrations_performed': 0})
        return 0
    check_index(args.index)
    if args.operation == 'artifact':
        print(requirements['partitions'][args.index]['parent_artifact_id'])
        return 0
    require(args.output is not None, 'Output directory required')
    if args.operation == 'restore':
        require(args.archive is not None and not args.output.exists(), 'Original ZIP and new output required')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='rohwer-parent-', dir=args.output.parent) as tmp:
            evidence = Path(tmp)/'evidence'
            verify_parent(args.archive, evidence, args.index, plan, requirements, selection, artifacts)
            initialize(evidence, args.output, args.index, plan, requirements)
        audit(args.output, args.index, plan, requirements)
        return 0
    if args.operation == 'compute':
        return compute(args.output, args.index, plan, requirements, args.budget)
    require(args.audit_output is not None and not args.audit_output.exists(), 'New audit output required')
    result = audit(args.output, args.index, plan, requirements, revision=args.revision,
                   run_id=args.run_id, run_attempt=args.run_attempt)
    write(args.audit_output, result)
    print({k: result[k] for k in ('status', 'partition_index', 'confirmed_branches',
                                 'verified_arrays', 'parent_arrays_preserved')})
    return 0


if __name__ == '__main__':
    sys.exit(main())
