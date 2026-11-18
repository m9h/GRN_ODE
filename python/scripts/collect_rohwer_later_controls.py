"""Collect the two fixed Rohwer control batches and all 512 partitions from offline evidence.

All 10,924 controls remain required. Original ZIPs, API snapshots, partial arrays,
failures and temporary checkpoints are preserved without promoting incomplete
work. This collector performs no network requests or numerical integrations.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain
from grn_memory.scipy_breaking_recovery import LABELS
from scripts import audit_rohwer_later_controls as auditor
from scripts.audit_scipy_breaking import trajectory
from scripts.audit_scipy_breaking_cases import check_outcome
from scripts.collect_rohwer_breaking_diagnostics import verify_zip
from scripts import run_rohwer_later_controls as producer
from scripts.run_rohwer_later_controls import digest, read, require, write

SOURCE = '0dc31af29f4ff9c5e0e610d7c473cc1382fb7dda'
RUNS = [{'id': run, 'run_attempt': 1, 'workflow_id': 423215372, 'head_sha': SOURCE,
         'path': '.github/workflows/rohwer-later-controls.yml'}
        for run in (44419997278, 44420020715)]
PLAN_SHA = '571526958023ac93789c4e48924ceb44106e378a1520339569e9bb818e84d98e'
GATES = [135210148117, 135210227397]


def fixed_run(batch):
    require(type(batch) is int and 0 <= batch < 2, 'Invalid fixed batch')
    return RUNS[batch]


def validate_run(run, batch):
    require(all(run[k] == value for k, value in fixed_run(batch).items())
            and run['event'] == 'workflow_dispatch', 'Fixed explicitly dispatched workflow identity differs')


def validate_job(row, run, job):
    expected = fixed_run(row['batch_index'])
    validate_run(run, row['batch_index'])
    require(job['id'] == row['job_id'] and job['name'] == row['job_name']
            and job['run_id'] == expected['id'] and job['run_attempt'] == expected['run_attempt']
            and job['head_sha'] == expected['head_sha'], 'Fixed job identity differs')


def bind_selection(plan, runs, jobs_by_batch):
    require(len(runs) == len(jobs_by_batch) == 2, 'Both complete batch snapshots are required')
    rows = []
    for batch, (run, jobs) in enumerate(zip(runs, jobs_by_batch, strict=True)):
        validate_run(run, batch)
        require(jobs['total_count'] == len(jobs['jobs']), 'All job pages are required')
        gates = [j for j in jobs['jobs'] if j['name'] == 'validation']
        require(len(gates) == 1 and gates[0]['id'] == GATES[batch] and gates[0]['status'] == 'completed'
                and gates[0]['conclusion'] == 'success', 'Fixed Linux validation must pass first')
        validate_job({'batch_index': batch, 'job_id': GATES[batch], 'job_name': 'validation'}, run, gates[0])
        indices = list(range(batch * 256, (batch + 1) * 256))
        require(plan['batches'][batch]['partition_indices'] == indices, 'Complete batch membership differs')
        names = {'validation'} | {f'rohwer-later-controls-batch-{batch}-partition-{i}' for i in indices}
        require(jobs['total_count'] == 257 and {j['name'] for j in jobs['jobs']} == names
                and len({j['id'] for j in jobs['jobs']}) == 257, 'Every fixed job is required exactly once')
        for index in indices:
            part = plan['partitions'][index]
            name = f'rohwer-later-controls-batch-{batch}-partition-{index}'
            job = next(j for j in jobs['jobs'] if j['name'] == name)
            row = {'batch_index': batch, 'index': index, 'run_id': run['id'], 'run_attempt': 1,
                   'job_id': job['id'], 'job_name': name,
                   'artifact_name': f'rohwer-controls-BIOMD0000000038-batch-{batch}-partition-{index}-attempt-1',
                   'branches': deepcopy(part['branches'])}
            validate_job(row, run, job)
            rows.append(row)
    selection = {'schema_version': 1, 'repository': 'm9h/GRN_ODE', 'runs': deepcopy(RUNS),
                 'plan_sha256': PLAN_SHA, 'validation_job_ids': list(GATES), 'selected': rows,
                 'required_stage_branches': 10924, 'required_full_branches': 11674,
                 'required_full_cases': 123, 'case_recovery_claimed': False,
                 'full_model_coverage_claimed': False, 'full_case_audit_required': True}
    validate_selection(selection, plan)
    return selection


def validate_selection(selection, plan):
    require(selection['schema_version'] == 1 and selection['repository'] == 'm9h/GRN_ODE'
            and selection['runs'] == RUNS and selection['plan_sha256'] == PLAN_SHA
            and selection['validation_job_ids'] == GATES and selection['required_stage_branches'] == 10924
            and selection['required_full_branches'] == 11674 and selection['required_full_cases'] == 123
            and selection['case_recovery_claimed'] is False and selection['full_model_coverage_claimed'] is False
            and selection['full_case_audit_required'] is True, 'Immutable selection identity or scope differs')
    rows = selection['selected']
    require([r['index'] for r in rows] == list(range(512)) and len({r['job_id'] for r in rows}) == 512
            and sum(len(r['branches']) for r in rows) == 10924, 'All 512 fixed partitions are required')
    for row, part in zip(rows, plan['partitions'], strict=True):
        index, batch = row['index'], row['batch_index']
        run = fixed_run(batch)
        require(type(index) is int and batch == part['batch_index'] == index // 256
                and row['run_id'] == run['id'] and row['run_attempt'] == run['run_attempt']
                and type(row['job_id']) is int and row['job_id'] > 0 and row['job_id'] not in GATES
                and row['job_name'] == f'rohwer-later-controls-batch-{batch}-partition-{index}'
                and row['artifact_name'] == f'rohwer-controls-BIOMD0000000038-batch-{batch}-partition-{index}-attempt-1'
                and row['branches'] == part['branches'], 'Complete original partition membership differs')


def validate_artifact(row, run, job, artifact):
    validate_job(row, run, job)
    expected = fixed_run(row['batch_index'])
    require(type(artifact['id']) is int and artifact['id'] > 0 and artifact['name'] == row['artifact_name']
            and artifact['expired'] is False and artifact['workflow_run']['id'] == expected['id']
            and artifact['workflow_run']['head_sha'] == expected['head_sha'], 'Artifact producer identity differs')
    require(job['status'] == 'completed' and job['completed_at']
            and datetime.fromisoformat(job['started_at']) <= datetime.fromisoformat(artifact['created_at'])
            <= datetime.fromisoformat(job['completed_at']), 'Artifact is outside the fixed job attempt')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))
            and type(artifact['size_in_bytes']) is int and artifact['size_in_bytes'] > 0,
            'Original ZIP digest and size are required')


def verify_branch(directory, row, entry, context, partition):
    plan, inventory, _, info, grid = context
    bid = row['record_id']
    run = fixed_run(partition['batch_index'])
    require(row in producer.selected(plan, partition['batch_index'], partition['index']),
            'Branch is outside the fixed batch and partition')
    empty = {**row, 'complete_diagnostic': False, 'verified_arrays': 0, 'status': 'not_started'}
    if entry is None:
        require(not directory.exists(), 'Unattempted branch has unexpected evidence')
        return empty
    if not directory.exists():
        require(entry['status'] not in ('confirmed', 'numerical_failure'), 'Complete branch evidence is missing')
        return {**empty, 'status': 'no_checkpoint', 'producer_outcome': entry}
    temporary = {'report.json.tmp', 'audit.json.tmp', bid + '.tmp'}
    arrays = {bid + '-' + label + '.npz' for label in LABELS}
    allowed = {'report.json', 'audit.json', bid + '.json'} | temporary | arrays
    require(directory.is_dir() and not directory.is_symlink()
            and {p.name for p in directory.iterdir()} <= allowed
            and all(p.is_file() and not p.is_symlink() for p in directory.iterdir()),
            'Unexpected or nonregular branch evidence')
    temp_files = sorted(p.name for p in directory.iterdir() if p.name in temporary)
    empty.update(unverified_checkpoint_files=temp_files)
    report_path = directory / 'report.json'
    if not report_path.exists():
        require(entry['status'] not in ('confirmed', 'numerical_failure'), 'Complete child report is missing')
        return {**empty, 'status': 'no_report', 'producer_outcome': entry,
                'unverified_arrays': sorted(p.name for p in directory.glob('*.npz'))}
    report = read(report_path)
    require(report['record_id'] == bid and report['metadata'] == producer.metadata_for(plan)
            and report['plan_sha256'] == PLAN_SHA and report['source_revision'] == run['head_sha']
            and report['run_id'] == str(run['id']) and report['run_attempt'] == str(run['run_attempt'])
            and report['batch_index'] == partition['batch_index'] and report['partition_index'] == partition['index'],
            'Child source, attempt, branch or metadata differs')
    if report['status'] == 'completed':
        checked = auditor.audit(directory, plan, inventory, info, grid, PLAN_SHA)
        if (directory / 'audit.json').exists():
            require(read(directory / 'audit.json') == checked, 'Available producer audit does not reproduce')
        if entry['status'] in ('confirmed', 'numerical_failure'):
            require(entry['status'] == ('confirmed' if checked['status'] == 'confirmed' else 'numerical_failure')
                    and digest(report_path) == entry['report_sha256']
                    and digest(directory / 'audit.json') == entry['audit_sha256'], 'Producer completion claim differs')
        return {**row, 'complete_diagnostic': True, 'verified_arrays': checked['verified_arrays'],
                'status': checked['status'], 'report_sha256': digest(report_path), 'producer_outcome': entry,
                'independent_audit': checked, 'unverified_arrays': checked['unverified_arrays'],
                'unverified_checkpoint_files': checked['unverified_checkpoint_files']}
    require(report['status'] == 'running' and report['branch'] is None
            and entry['status'] not in ('confirmed', 'numerical_failure'), 'Child completion claim differs')
    record_path = directory / (bid + '.json')
    traces = {}
    if record_path.exists():
        record = read(record_path)
        spec = inventory['branches'][bid]
        require(record['record_id'] == bid and record['specification'] == spec
                and record['fingerprint'] == report['metadata']['fingerprint']
                and record['case_recovery_claimed'] is False
                and 'reused_from' not in record and 'previous_incomplete_attempts' not in record
                and set(record['integrations']) <= set(LABELS), 'Partial branch identity or scope differs')
        times = grid[grid <= spec['stop']]
        require(len(times) == row['sample_count'], 'Partial branch sample count differs')
        trains = [ResetTrain(**t) for t in spec['reset_trains']]
        for label, outcome in record['integrations'].items():
            require(type(outcome['completed']) is bool and outcome['request'] == plan['requests'][label],
                    'Partial integration request differs')
            if not outcome['completed']:
                continue
            check_outcome(outcome, label, plan['requests'][label], times, info['observables'], trains, info['sha256'])
            traces[label] = trajectory(directory, bid, label, record['traces'][label], times, info['observables'])
        require(set(traces) == set(record['traces']), 'Partial trajectory inventory differs')
        checks = {a + '_vs_' + b: comparison(traces[a], traces[b], **plan['acceptance'])
                  for i, a in enumerate(LABELS) for b in LABELS[i+1:] if a in traces and b in traces}
        if record['status'] == 'running':
            require(record['comparisons'] == {}, 'Running record contains an unexpected final comparison')
        else:
            require(set(record['integrations']) == set(LABELS), 'Finished record lacks requested outcomes')
            for label, outcome in record['integrations'].items():
                check_outcome(outcome, label, plan['requests'][label], times, info['observables'], trains, info['sha256'])
            status = ('incomplete' if len(checks) != 6 else
                      'confirmed' if all(v['passed'] for v in checks.values()) else 'mismatch')
            require(record['status'] == status and record['comparisons'] == checks,
                    'Finished record without terminal report does not reproduce')
    else:
        checks = {}
    return {**empty, 'status': 'interrupted', 'verified_arrays': len(traces), 'comparisons': checks,
            'producer_outcome': entry, 'unverified_arrays': sorted(p.name for p in directory.glob('*.npz')
                if p.name not in {bid + '-' + label + '.npz' for label in traces})}


def verify_partition(directory, row, context, runner_sha, input_validation):
    plan = context[0]
    run = fixed_run(row['batch_index'])
    require(row['batch_index'] == row['index'] // 256, 'Partition batch differs')
    require(directory.is_dir() and not directory.is_symlink()
            and all(not p.is_symlink() and (p.is_file() or p.is_dir()) for p in directory.iterdir()),
            'Unsafe partition evidence directory')
    require(row['branches'] == plan['partitions'][row['index']]['branches'], 'Full partition selection differs')
    temporary = {'execution.json.tmp', 'input-validation.json.tmp'}
    report_path = directory / 'execution.json'
    validation_path = directory / 'input-validation.json'
    if validation_path.exists():
        require(read(validation_path) == input_validation, 'Input validation does not reproduce')
    if not report_path.exists():
        require({p.name for p in directory.iterdir()} <= temporary | {'input-validation.json'},
                'Unexpected evidence without an execution checkpoint')
        return {'complete_selected_diagnostics': False, 'producer_status': 'no_execution_checkpoint',
                'unverified_checkpoint_files': sorted(p.name for p in directory.iterdir() if p.name in temporary),
                'branches': [verify_branch(directory / r['record_id'], r, None, context, row) for r in row['branches']]}
    execution = read(report_path)
    require(execution['model_id'] == plan['model_id'] and execution['plan_sha256'] == PLAN_SHA
            and execution['batch_index'] == row['batch_index'] and execution['partition_index'] == row['index'] and execution['selected_branches'] == row['branches']
            and execution['expected_branches'] == len(row['branches'])
            and execution['metadata'] == producer.metadata_for(plan)
            and execution['source_revision'] == run['head_sha'] and execution['wrapper_sha256'] == runner_sha
            and execution['run_id'] == str(run['id']) and execution['run_attempt'] == str(run['run_attempt'])
            and execution['input_validation_sha256'] == digest(validation_path)
            and execution['case_recovery_claimed'] is False and execution['full_model_coverage_claimed'] is False
            and execution['full_case_audit_required'] is True, 'Partition execution lineage differs')
    entries = execution['branches']
    require([{k: e[k] for k in ('record_id', 'sample_count', 'origin')} for e in entries]
            == row['branches'][:len(entries)], 'Attempted branch prefix differs')
    require(all(e['status'] in ('running', 'confirmed', 'numerical_failure', 'time_limit', 'execution_or_audit_failure')
                for e in entries) and execution['status'] in ('running', 'completed', 'incomplete')
            and execution.get('stop_reason') in (None, 'time_limit', 'disk_limit'), 'Unknown execution outcome')
    allowed = {'execution.json', 'input-validation.json'} | temporary | {e['record_id'] for e in entries}
    require({p.name for p in directory.iterdir()} <= allowed, 'Evidence lies outside the attempted prefix')
    if execution['status'] != 'running':
        finished = len(entries) == len(row['branches']) and all(e['status'] in ('confirmed', 'numerical_failure') for e in entries)
        require(execution['status'] == ('completed' if finished else 'incomplete')
                and execution['confirmed_branches'] == sum(e['status'] == 'confirmed' for e in entries)
                and (not finished or 'stop_reason' not in execution), 'Producer aggregate outcome differs')
    by_id = {entry['record_id']: entry for entry in entries}
    branches = [verify_branch(directory / r['record_id'], r, by_id.get(r['record_id']), context, row) for r in row['branches']]
    return {'complete_selected_diagnostics': all(b['complete_diagnostic'] for b in branches),
            'execution_sha256': digest(report_path), 'producer_status': execution['status'],
            'producer_stop_reason': execution.get('stop_reason'), 'branches': branches,
            'unverified_checkpoint_files': sorted(p.name for p in directory.iterdir() if p.name in temporary)}


def preserve_snapshots(selection_path, snapshots, output):
    sources = {'selection': selection_path, **{f'batch-{batch}/{name}':
               snapshots / f'batch-{batch}' / (name + '.json')
               for batch in range(2) for name in ('run', 'jobs', 'artifacts')}}
    hashes = {name: digest(path) for name, path in sources.items()}
    destination = output / 'api-snapshots' / fingerprint(hashes)
    destination.mkdir(parents=True, exist_ok=True)
    require(not destination.is_symlink(), 'Preserved snapshot directory cannot be a symlink')
    for name, source in sources.items():
        target = destination / (name + '.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        require(not target.parent.is_symlink(), 'Unsafe preserved snapshot parent')
        if not target.exists():
            with target.open('xb') as stream:
                stream.write(source.read_bytes())
        require(not target.is_symlink() and digest(target) == hashes[name], 'Preserved API snapshot differs')
    return {'directory': str(destination.resolve()), 'sha256': hashes}


def collect(plan_path, bundle, selection_path, snapshots, archives, output):
    require(not output.is_symlink(), 'Unsafe output directory')
    for source in (bundle, snapshots, archives):
        a, b = output.resolve(), source.resolve()
        require(a != b and a not in b.parents and b not in a.parents,
                'Collection output must be separate from input directories')
    for source in (plan_path, selection_path):
        require(output.resolve() != source.resolve() and output.resolve() not in source.resolve().parents,
                'Collection output must be separate from source plan and selection files')
    context = producer.load_plan(plan_path, PLAN_SHA, bundle)
    plan = context[0]
    validation = producer.inputs.validate(bundle, producer.MANIFEST_SHA)
    selection = read(selection_path)
    validate_selection(selection, plan)
    batches = [{name: read(snapshots / f'batch-{batch}' / (name + '.json'))
                for name in ('run', 'jobs', 'artifacts')} for batch in range(2)]
    require(all(b['jobs']['total_count'] == len(b['jobs']['jobs'])
                and b['artifacts']['total_count'] == len(b['artifacts']['artifacts']) for b in batches),
            'All API pages for both batches are required')
    require(bind_selection(plan, [b['run'] for b in batches], [b['jobs'] for b in batches]) == selection,
            'Live job selection differs from fixed selection')
    preserved = preserve_snapshots(selection_path, snapshots, output)
    runner_sha = hashlib.sha256(subprocess.check_output(['git', 'show', SOURCE +
        ':python/scripts/run_rohwer_later_controls.py'], cwd=ROOT)).hexdigest()
    collected, pending, missing, errors = [], [], [], []
    for row in selection['selected']:
        try:
            snapshot = batches[row['batch_index']]
            run, jobs, artifacts = (snapshot[k] for k in ('run', 'jobs', 'artifacts'))
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
            parent = output / str(run['id']) / 'attempt-1'
            destination = parent / f'artifact-{artifact["id"]}'
            if not destination.exists():
                archive = archives / f'artifact-{artifact["id"]}.zip'
                if not archive.is_file():
                    missing.append({'index': row['index'], 'reason': 'zip_not_downloaded', 'artifact_id': artifact['id']})
                    continue
                parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='rohwer-controls-collect-', dir=parent) as temporary:
                    stage = Path(temporary) / 'artifact'
                    stage.mkdir()
                    shutil.copyfile(archive, stage / 'download.zip')
                    require(digest(stage / 'download.zip') == artifact['digest'].removeprefix('sha256:')
                            and (stage / 'download.zip').stat().st_size == artifact['size_in_bytes'], 'Original ZIP differs')
                    verify_zip(stage / 'download.zip', stage / 'evidence', extract=True)
                    stage.rename(destination)
            archive, evidence = destination / 'download.zip', destination / 'evidence'
            require(archive.is_file() and not archive.is_symlink() and evidence.is_dir()
                    and not evidence.is_symlink(), 'Unsafe cached evidence path')
            require(digest(archive) == artifact['digest'].removeprefix('sha256:')
                    and archive.stat().st_size == artifact['size_in_bytes'], 'Cached ZIP differs')
            files = verify_zip(archive, evidence)
            checked = verify_partition(evidence, row, context, runner_sha, validation)
            collected.append({**row, **checked, 'artifact_id': artifact['id'], 'archive_sha256': artifact['digest'],
                              'evidence': str(evidence.resolve()), 'evidence_sha256': files, 'job_conclusion': job['conclusion']})
        except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile) as error:
            errors.append({'index': row['index'], 'error': f'{type(error).__name__}: {error}'})
    branches = [b for part in collected for b in part['branches']]
    complete = len(collected) == 512 and len(branches) == 10924 and all(b['complete_diagnostic'] for b in branches)
    complete = complete and not (pending or missing or errors)
    confirmed = sum(b['complete_diagnostic'] and b['status'] == 'confirmed' for b in branches)
    result = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'runs': deepcopy(RUNS), 'plan_sha256': PLAN_SHA,
              'collector_script_sha256': digest(Path(__file__)),
              'transport_script_sha256': digest(ROOT / 'scripts/collect_rohwer_breaking_diagnostics.py'),
              'status': 'verification_failed' if errors else 'controls_confirmed' if complete and confirmed == 10924
                        else 'complete_with_numerical_failures' if complete else 'incomplete',
              'complete_selected_diagnostics': complete, 'all_10924_controls_confirmed': complete and confirmed == 10924,
              'confirmed_branches': confirmed, 'verified_arrays': sum(b['verified_arrays'] for b in branches),
              'partitions': collected, 'pending_indices': pending, 'missing_artifacts': missing, 'collection_errors': errors,
              'preserved_api_snapshots': preserved, 'input_validation': validation,
              'numerical_integrations_performed': 0, 'case_recovery_claimed': False,
              'full_model_coverage_claimed': False, 'full_case_audit_required': True,
              'required_stage_branches': 10924, 'required_full_branches': 11674, 'required_full_cases': 123}
    write(output / 'status.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    bind = sub.add_parser('bind')
    for key in ('plan', 'inputs', 'snapshots', 'output'):
        bind.add_argument('--' + key, type=Path, required=True)
    capture = sub.add_parser('collect')
    for key in ('plan', 'inputs', 'selection', 'snapshots', 'archives', 'output'):
        capture.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'bind':
        require(not args.output.exists(), 'Do not overwrite a fixed collection selection')
        plan = producer.load_plan(args.plan, PLAN_SHA, args.inputs)[0]
        runs = [read(args.snapshots / f'batch-{batch}' / 'run.json') for batch in range(2)]
        jobs = [read(args.snapshots / f'batch-{batch}' / 'jobs.json') for batch in range(2)]
        selection = bind_selection(plan, runs, jobs)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write(args.output, selection)
    else:
        result = collect(args.plan, args.inputs, args.selection, args.snapshots, args.archives, args.output)
        print({k: result[k] for k in ('status', 'confirmed_branches', 'pending_indices', 'missing_artifacts', 'collection_errors')})
        sys.exit(1 if result['collection_errors'] else 0)
