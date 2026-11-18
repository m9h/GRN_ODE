"""Verify the fixed Rohwer diagnostic run from downloaded API snapshots and ZIPs.

This collector makes no network requests or numerical integrations. Every fixed
branch remains required, including mismatches, failed integrations and timeouts.
Branch evidence never changes case or whole-model coverage here.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_jax import source_hashes
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain
from scripts import audit_scipy_breaking as auditor
from scripts.diagnose_scipy_breaking import load_saved, prepare, requests
from scripts import run_rohwer_breaking_diagnostics as producer
from scripts.run_rohwer_breaking_diagnostics import digest, read, require, write

WORKFLOW = '.github/workflows/rohwer-breaking-diagnostics.yml'
RUN = {'id': 44401097371, 'run_attempt': 1, 'workflow_id': 423124827,
       'head_sha': '40fe82344d8dacb2d79ebdc4087ee52beb90a091', 'path': WORKFLOW}
PLAN_SHA = 'ab0f50d411a929a887fdf5132958502ec11a2af620cd577b8fc40f5994b4b9f0'
VALIDATION_JOB = 135144005920


def validate_run(run):
    require(all(run[k] == v for k, v in RUN.items()), 'Fixed workflow run identity differs')
    require(run['event'] == 'workflow_dispatch', 'Explicit compute dispatch required')


def validate_job(row, run, job):
    validate_run(run)
    require(job['id'] == row['job_id'] and job['name'] == row['job_name']
            and job['run_id'] == run['id'] and job['run_attempt'] == run['run_attempt']
            and job['head_sha'] == run['head_sha'], 'Selected job identity differs')


def bind_selection(plan, run, jobs):
    validate_run(run)
    require(jobs['total_count'] == len(jobs['jobs']), 'All job pages are required')
    gates = [j for j in jobs['jobs'] if j['name'] == 'validation']
    require(len(gates) == 1 and gates[0]['id'] == VALIDATION_JOB
            and gates[0]['status'] == 'completed' and gates[0]['conclusion'] == 'success',
            'Fixed Linux validation must pass first')
    validate_job({'job_id': VALIDATION_JOB, 'job_name': 'validation'}, run, gates[0])
    rows = []
    for part in plan['partitions']:
        index = part['index']
        name = f'rohwer-failed-branches-{index}'
        matches = [j for j in jobs['jobs'] if j['name'] == name]
        require(len(matches) == 1, 'Every fixed compute job must exist exactly once')
        row = {'index': index, 'job_id': matches[0]['id'], 'job_name': name,
               'artifact_name': f'rohwer-breaking-{producer.MODEL}-partition-{index}-attempt-1',
               'branches': part['branches']}
        validate_job(row, run, matches[0])
        rows.append(row)
    selection = {'schema_version': 1, 'repository': 'm9h/GRN_ODE', 'run': RUN,
                 'plan_sha256': PLAN_SHA, 'validation_job_id': VALIDATION_JOB,
                 'selected': rows, 'case_recovery_claimed': False}
    validate_selection(selection, plan)
    return selection


def validate_selection(selection, plan):
    require(selection['schema_version'] == 1 and selection['repository'] == 'm9h/GRN_ODE'
            and selection['run'] == RUN and selection['plan_sha256'] == PLAN_SHA
            and selection['validation_job_id'] == VALIDATION_JOB
            and selection['case_recovery_claimed'] is False, 'Immutable selection identity differs')
    rows = selection['selected']
    require([r['index'] for r in rows] == list(range(producer.PARTITIONS))
            and len({r['job_id'] for r in rows}) == producer.PARTITIONS, 'Every fixed partition is required')
    for row, part in zip(rows, plan['partitions'], strict=True):
        i = row['index']
        require(type(row['job_id']) is int and row['job_id'] > 0 and row['job_id'] != VALIDATION_JOB
                and row['job_name'] == f'rohwer-failed-branches-{i}'
                and row['artifact_name'] == f'rohwer-breaking-{producer.MODEL}-partition-{i}-attempt-1'
                and row['branches'] == part['branches'], 'Complete original partition membership differs')


def validate_artifact(row, run, job, artifact):
    validate_job(row, run, job)
    require(type(artifact['id']) is int and artifact['id'] > 0 and artifact['name'] == row['artifact_name']
            and artifact['expired'] is False and artifact['workflow_run']['id'] == run['id']
            and artifact['workflow_run']['head_sha'] == run['head_sha'], 'Artifact producer identity differs')
    require(job['status'] == 'completed' and job['completed_at']
            and datetime.fromisoformat(job['started_at']) <= datetime.fromisoformat(artifact['created_at'])
            <= datetime.fromisoformat(job['completed_at']), 'Artifact is outside selected job attempt')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))
            and type(artifact['size_in_bytes']) is int and artifact['size_in_bytes'] > 0,
            'Original ZIP size and SHA-256 are required')


def archive_members(stream):
    names = set()
    for entry in stream.infolist():
        name = entry.filename.rstrip('/') if entry.is_dir() else entry.filename
        path = PurePosixPath(name)
        kind = stat.S_IFMT(entry.external_attr >> 16)
        require(name and not path.is_absolute() and '..' not in path.parts and str(path) == name
                and '\\' not in name and name not in names
                and kind in ((0, stat.S_IFDIR) if entry.is_dir() else (0, stat.S_IFREG)),
                'Unsafe, duplicate or nonregular artifact member')
        names.add(name)
        yield entry


def verify_zip(archive, evidence, *, extract=False):
    hashes = {}
    if extract:
        evidence.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as stream:
        entries = list(archive_members(stream))
        for entry in entries:
            if entry.is_dir():
                continue
            path = evidence/entry.filename
            if extract:
                path.parent.mkdir(parents=True, exist_ok=True)
                with stream.open(entry) as source, path.open('xb') as target:
                    shutil.copyfileobj(source, target)
            require(path.is_file() and not path.is_symlink() and path.stat().st_size == entry.file_size,
                    'Extracted file inventory differs')
            with stream.open(entry) as source:
                sha = hashlib.file_digest(source, 'sha256').hexdigest()
            require(digest(path) == sha, 'Extracted bytes differ from original ZIP')
            hashes[entry.filename] = sha
    actual = set()
    for path in evidence.rglob('*'):
        require(not path.is_symlink(), 'Symlink in extracted evidence')
        if path.is_file():
            actual.add(path.relative_to(evidence).as_posix())
    require(actual == set(hashes), 'Untracked or missing extracted file')
    return hashes


def verify_branch(directory, row, entry, inputs, plan):
    bid = row['record_id']
    source_entry = plan['source_partitions'][row['source_partition']]
    empty = {**row, 'complete_diagnostic': False, 'verified_arrays': 0, 'status': 'not_started'}
    if entry is None:
        require(not directory.exists(), 'Unattempted branch has unexpected evidence')
        return empty
    if not directory.exists():
        require(entry['status'] not in ('confirmed', 'numerical_failure'), 'Reported complete branch is missing')
        return {**empty, 'status': 'no_checkpoint', 'producer_outcome': entry}
    require(directory.is_dir() and not directory.is_symlink(), 'Unsafe branch directory')
    allowed = {'.diagnostic.lock', 'source-evidence.json', 'report.json', 'audit.json', bid+'.json'}
    allowed |= {bid+'-'+label+'.npz' for label in auditor.LABELS}
    require({p.name for p in directory.iterdir()} <= allowed
            and all(p.is_file() and not p.is_symlink() for p in directory.iterdir()),
            'Unexpected branch evidence file')
    source = directory/'source-evidence.json'
    if source.exists():
        require(digest(source) == source_entry['sha256'], 'Branch source capture differs from fixed inputs')
    report_path = directory/'report.json'
    if not report_path.exists():
        require(entry['status'] not in ('confirmed', 'numerical_failure'), 'Reported complete diagnostic is missing')
        return {**empty, 'status': 'no_report', 'producer_outcome': entry}
    report = read(report_path)
    require(source.is_file() and report['selected_branch_ids'] == [bid]
            and report['source_evidence_sha256'] == source_entry['sha256']
            and report['source_report_sha256'] == source_entry['original_report_sha256']
            and report['requests'] == requests(SimpleNamespace(**producer.REQUESTS))
            and report['versions'] == plan['runtime']['versions'], 'Fixed branch input or numerical requests differ')
    if report['status'] == 'completed':
        checked = auditor.audit(directory)
        require(checked['selected_branch_count'] == 1 and checked['branches'][0]['record_id'] == bid,
                'Audited branch inventory differs')
        confirmed = checked['all_selected_branches_confirmed']
        if entry['status'] in ('confirmed', 'numerical_failure'):
            require(entry['status'] == ('confirmed' if confirmed else 'numerical_failure')
                    and digest(report_path) == entry['report_sha256']
                    and digest(directory/'audit.json') == entry['audit_sha256']
                    and read(directory/'audit.json') == checked, 'Producer audit does not reproduce exactly')
        record = read(directory/(bid+'.json'))
        expected = {'source-evidence.json', 'report.json', bid+'.json'}
        if (directory/'.diagnostic.lock').exists():
            expected.add('.diagnostic.lock')
        expected |= {r['file'] for r in record['traces'].values()}
        if (directory/'audit.json').exists():
            require(read(directory/'audit.json') == checked, 'Available producer audit differs')
            expected.add('audit.json')
        require({p.name for p in directory.iterdir()} == expected, 'Unreferenced completed branch file')
        return {**row, 'complete_diagnostic': True, 'verified_arrays': len(record['traces']),
                'status': checked['branches'][0]['status'], 'report_sha256': digest(report_path),
                'producer_outcome': entry, 'independent_audit': checked}
    require(report['status'] == 'running' and entry['status'] not in ('confirmed', 'numerical_failure'),
            'Producer completion claim differs')
    require(fingerprint({k: report[k] for k in auditor.META_KEYS}) == report['fingerprint']
            and report['case_recovery_claimed'] is False and report['branches'] == []
            and report['expected_branches'] == 1, 'Partial diagnostic metadata differs')
    expected_sources = source_hashes()
    expected_sources.update({name: digest(ROOT/name) for name in auditor.SOURCES})
    require(report['implementation_sha256'] == expected_sources, 'Partial diagnostic implementation differs')
    evidence, _, info, grid, original = prepare(source, [bid])
    require(report['model_id'] == producer.MODEL and report['model_sha256'] == info['sha256']
            and report['source_fingerprint'] == evidence['original_report']['fingerprint']
            and report['sample_grid_sha256'] == hashlib.sha256(grid.tobytes()).hexdigest()
            and report['acceptance'] == plan['acceptance'], 'Partial diagnostic scientific scope differs')
    record_path = directory/(bid+'.json')
    traces = {}
    if record_path.exists():
        record = read(record_path)
        spec = original[bid]['specification']
        require(record['record_id'] == bid and record['specification'] == spec
                and record['fingerprint'] == report['fingerprint'] and record['case_recovery_claimed'] is False
                and set(record['integrations']) <= set(auditor.LABELS), 'Partial branch identity differs')
        times = grid[grid <= spec['stop']]
        trains = [ResetTrain(**t) for t in spec['reset_trains']]
        for label, outcome in record['integrations'].items():
            require(outcome['request'] == report['requests'][label]
                    and type(outcome['completed']) is bool, 'Partial integration request differs')
            if not outcome['completed']:
                continue
            saved = record['traces'][label]
            require(saved['file'] == bid+'-'+label+'.npz', 'Unexpected saved array path')
            if label.startswith('scipy'):
                require(outcome['backend'] == 'scipy.solve_ivp' and outcome['rhs_backend'] == 'Jaxkineticmodel'
                        and outcome['jacobian'] == 'jax.jacfwd', 'Partial Radau backend differs')
            traces[label] = load_saved(directory/saved['file'], saved, times, info['observables'], outcome,
                                       label, report['requests'][label], trains, info['sha256'])
        require(set(traces) == set(record['traces']), 'Partial array inventory differs')
    comparisons = {a+'_vs_'+b: comparison(traces[a], traces[b], **plan['acceptance'])
                   for i, a in enumerate(auditor.LABELS) for b in auditor.LABELS[i+1:] if a in traces and b in traces}
    return {**row, 'complete_diagnostic': False, 'verified_arrays': len(traces), 'status': 'interrupted',
            'producer_outcome': entry, 'comparisons': comparisons,
            'unverified_arrays': sorted(p.name for p in directory.glob('*.npz')
                                        if p.name not in {bid+'-'+label+'.npz' for label in traces})}


def verify_partition(directory, row, inputs, plan, runner_sha):
    execution = read(directory/'execution.json')
    require(execution['model_id'] == producer.MODEL and execution['plan_sha256'] == PLAN_SHA
            and execution['partition_index'] == row['index'] and execution['selected_branches'] == row['branches']
            and execution['expected_branches'] == len(row['branches'])
            and execution['producer_revision'] == RUN['head_sha'] and execution['runner_sha256'] == runner_sha
            and execution['run_id'] == str(RUN['id']) and execution['run_attempt'] == str(RUN['run_attempt'])
            and execution['runtime'] == plan['runtime'] and execution['case_recovery_claimed'] is False,
            'Partition execution lineage differs')
    entries = execution['branches']
    require([{k: entry[k] for k in ('record_id', 'source_partition', 'sample_count')} for entry in entries]
            == row['branches'][:len(entries)], 'Attempted branch prefix differs')
    allowed = ('running', 'confirmed', 'numerical_failure', 'time_limit', 'execution_or_audit_failure')
    require(all(e['status'] in allowed for e in entries) and execution['status'] in ('running', 'completed', 'incomplete'),
            'Unknown execution outcome')
    require({p.name for p in directory.iterdir()} <= {'execution.json'} | {e['record_id'] for e in entries},
            'Evidence lies outside attempted branch prefix')
    if execution['status'] != 'running':
        finished = len(entries) == len(row['branches']) and all(e['status'] in ('confirmed', 'numerical_failure') for e in entries)
        require(execution['status'] == ('completed' if finished else 'incomplete')
                and execution['confirmed_branches'] == sum(e['status'] == 'confirmed' for e in entries),
                'Producer aggregate outcome differs')
    by_id = {e['record_id']: e for e in entries}
    branches = [verify_branch(directory/b['record_id'], b, by_id.get(b['record_id']), inputs, plan)
                for b in row['branches']]
    return {'complete_selected_diagnostics': all(b['complete_diagnostic'] for b in branches),
            'execution_sha256': digest(directory/'execution.json'), 'producer_status': execution['status'],
            'branches': branches}


def collect(inputs, selection_path, snapshots, archives, output):
    plan = producer.check(inputs, PLAN_SHA)
    selection = read(selection_path)
    validate_selection(selection, plan)
    run, jobs, artifacts = (read(snapshots/(name+'.json')) for name in ('run', 'jobs', 'artifacts'))
    require(jobs['total_count'] == len(jobs['jobs']) and artifacts['total_count'] == len(artifacts['artifacts']),
            'All API pages are required')
    require(bind_selection(plan, run, jobs) == selection, 'Live job selection differs from fixed selection')
    runner_sha = hashlib.sha256(subprocess.check_output(['git', 'show', RUN['head_sha']+
        ':python/scripts/run_rohwer_breaking_diagnostics.py'], cwd=ROOT)).hexdigest()
    collected, pending, missing, errors = [], [], [], []
    for row in selection['selected']:
        try:
            job = next(j for j in jobs['jobs'] if j['id'] == row['job_id'])
            validate_job(row, run, job)
            if job['status'] != 'completed':
                pending.append(row['index'])
                continue
            matches = [a for a in artifacts['artifacts'] if a['name'] == row['artifact_name']]
            if not matches:
                missing.append({'index': row['index'], 'reason': 'no_artifact'})
                continue
            require(len(matches) == 1, 'Duplicate selected artifact')
            artifact = matches[0]
            validate_artifact(row, run, job, artifact)
            parent = output/str(RUN['id'])/'attempt-1'
            destination = parent/f'artifact-{artifact["id"]}'
            if not destination.exists():
                archive = archives/f'artifact-{artifact["id"]}.zip'
                if not archive.is_file():
                    missing.append({'index': row['index'], 'reason': 'zip_not_downloaded', 'artifact_id': artifact['id']})
                    continue
                parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='rohwer-collect-', dir=parent) as temporary:
                    stage = Path(temporary)/'artifact'
                    stage.mkdir()
                    shutil.copyfile(archive, stage/'download.zip')
                    require(digest(stage/'download.zip') == artifact['digest'].removeprefix('sha256:')
                            and (stage/'download.zip').stat().st_size == artifact['size_in_bytes'], 'Original ZIP differs')
                    verify_zip(stage/'download.zip', stage/'evidence', extract=True)
                    stage.rename(destination)
            archive, evidence = destination/'download.zip', destination/'evidence'
            require(digest(archive) == artifact['digest'].removeprefix('sha256:')
                    and archive.stat().st_size == artifact['size_in_bytes'], 'Cached ZIP differs')
            files = verify_zip(archive, evidence)
            verified = verify_partition(evidence, row, inputs, plan, runner_sha)
            collected.append({**row, **verified, 'artifact_id': artifact['id'], 'archive_sha256': artifact['digest'],
                              'evidence': str(evidence.resolve()), 'evidence_sha256': files,
                              'job_conclusion': job['conclusion']})
        except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
            errors.append({'index': row['index'], 'error': f'{type(error).__name__}: {error}'})
    branches = [b for p in collected for b in p['branches']]
    complete = len(collected) == producer.PARTITIONS and len(branches) == 750 and all(b['complete_diagnostic'] for b in branches)
    complete = complete and not (pending or missing or errors)
    confirmed = sum(b['complete_diagnostic'] and b['status'] == 'confirmed' for b in branches)
    status = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'status': 'verification_failed' if errors else 'diagnostics_confirmed' if complete and confirmed == 750
                        else 'complete_with_numerical_failures' if complete else 'incomplete',
              'selection_sha256': digest(selection_path), 'complete_selected_diagnostics': complete,
              'confirmed_branches': confirmed, 'verified_arrays': sum(b['verified_arrays'] for b in branches),
              'all_750_branches_confirmed': complete and confirmed == 750, 'partitions': collected,
              'pending_indices': pending, 'missing_artifacts': missing, 'collection_errors': errors,
              'source_snapshot_sha256': {name: digest(snapshots/(name+'.json')) for name in ('run', 'jobs', 'artifacts')},
              'numerical_integrations_performed': 0, 'case_recovery_claimed': False, 'full_model_coverage_claimed': False}
    output.mkdir(parents=True, exist_ok=True)
    write(output/'status.json', status)
    return status


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    bind = sub.add_parser('bind')
    for key in ('inputs', 'run', 'jobs', 'output'):
        bind.add_argument('--'+key, type=Path, required=True)
    capture = sub.add_parser('collect')
    for key in ('inputs', 'selection', 'snapshots', 'archives', 'output'):
        capture.add_argument('--'+key, type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'bind':
        plan = producer.check(args.inputs, PLAN_SHA)
        require(not args.output.exists(), 'Do not overwrite an immutable collection selection')
        selection = bind_selection(plan, read(args.run), read(args.jobs))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write(args.output, selection)
    else:
        result = collect(args.inputs, args.selection, args.snapshots, args.archives, args.output)
        print({k: result[k] for k in ('status', 'confirmed_branches', 'pending_indices', 'missing_artifacts', 'collection_errors')})
        sys.exit(1 if result['collection_errors'] else 0)
