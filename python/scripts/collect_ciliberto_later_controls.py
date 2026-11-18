"""Collect the fixed 256-partition Ciliberto control run from offline evidence.

All 6,859 controls remain required. Original ZIPs, API snapshots, partial arrays,
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
from scripts import audit_ciliberto_later_controls as auditor
from scripts.audit_scipy_breaking import trajectory
from scripts.audit_scipy_breaking_cases import check_outcome
from scripts.collect_ciliberto_full_diagnostics import verify_zip
from scripts import run_ciliberto_later_controls as producer
from scripts.run_ciliberto_full_diagnostics import digest, read, require, write

RUN = {'id': 44412503884, 'run_attempt': 1, 'workflow_id': 423180607,
       'head_sha': '05232fa83c4be917455dc2d143a11253cb7773e6',
       'path': '.github/workflows/ciliberto-later-controls.yml'}
PLAN_SHA = 'd1e73a51b8cc8b7e5ab2f283c5a31de6a09415db8782551e9ec6392d1a5740c0'
GATE = 135184099103


def validate_run(run):
    require(all(run[k] == value for k, value in RUN.items()) and run['event'] == 'workflow_dispatch',
            'Fixed explicitly dispatched workflow identity differs')


def validate_job(row, run, job):
    validate_run(run)
    require(job['id'] == row['job_id'] and job['name'] == row['job_name']
            and job['run_id'] == RUN['id'] and job['run_attempt'] == RUN['run_attempt']
            and job['head_sha'] == RUN['head_sha'], 'Fixed job identity differs')


def bind_selection(plan, run, jobs):
    validate_run(run)
    require(jobs['total_count'] == len(jobs['jobs']), 'All job pages are required')
    gates = [j for j in jobs['jobs'] if j['name'] == 'validation']
    require(len(gates) == 1 and gates[0]['id'] == GATE and gates[0]['status'] == 'completed'
            and gates[0]['conclusion'] == 'success', 'Fixed Linux validation must pass first')
    validate_job({'job_id': GATE, 'job_name': 'validation'}, run, gates[0])
    names = {'validation'} | {f'ciliberto-later-controls-{i}' for i in range(256)}
    require(jobs['total_count'] == 257 and {j['name'] for j in jobs['jobs']} == names
            and len({j['id'] for j in jobs['jobs']}) == 257, 'Every fixed job is required exactly once')
    rows = []
    for part in plan['partitions']:
        index = part['index']
        name = f'ciliberto-later-controls-{index}'
        job = next(j for j in jobs['jobs'] if j['name'] == name)
        row = {'index': index, 'job_id': job['id'], 'job_name': name,
               'artifact_name': f'ciliberto-controls-BIOMD0000000697-partition-{index}-attempt-1',
               'branches': deepcopy(part['branches'])}
        validate_job(row, run, job)
        rows.append(row)
    selection = {'schema_version': 1, 'repository': 'm9h/GRN_ODE', 'run': dict(RUN),
                 'plan_sha256': PLAN_SHA, 'validation_job_id': GATE, 'selected': rows,
                 'required_stage_branches': 6859, 'required_full_branches': 7334,
                 'required_full_cases': 74, 'case_recovery_claimed': False,
                 'full_model_coverage_claimed': False, 'full_case_audit_required': True}
    validate_selection(selection, plan)
    return selection


def validate_selection(selection, plan):
    require(selection['schema_version'] == 1 and selection['repository'] == 'm9h/GRN_ODE'
            and selection['run'] == RUN and selection['plan_sha256'] == PLAN_SHA
            and selection['validation_job_id'] == GATE and selection['required_stage_branches'] == 6859
            and selection['required_full_branches'] == 7334 and selection['required_full_cases'] == 74
            and selection['case_recovery_claimed'] is False and selection['full_model_coverage_claimed'] is False
            and selection['full_case_audit_required'] is True, 'Immutable selection identity or scope differs')
    rows = selection['selected']
    require([r['index'] for r in rows] == list(range(256)) and len({r['job_id'] for r in rows}) == 256,
            'All 256 fixed partitions are required')
    for row, part in zip(rows, plan['partitions'], strict=True):
        index = row['index']
        require(type(row['job_id']) is int and row['job_id'] > 0 and row['job_id'] != GATE
                and row['job_name'] == f'ciliberto-later-controls-{index}'
                and row['artifact_name'] == f'ciliberto-controls-BIOMD0000000697-partition-{index}-attempt-1'
                and row['branches'] == part['branches'], 'Complete original partition membership differs')


def validate_artifact(row, run, job, artifact):
    validate_job(row, run, job)
    require(type(artifact['id']) is int and artifact['id'] > 0 and artifact['name'] == row['artifact_name']
            and artifact['expired'] is False and artifact['workflow_run']['id'] == RUN['id']
            and artifact['workflow_run']['head_sha'] == RUN['head_sha'], 'Artifact producer identity differs')
    require(job['status'] == 'completed' and job['completed_at']
            and datetime.fromisoformat(job['started_at']) <= datetime.fromisoformat(artifact['created_at'])
            <= datetime.fromisoformat(job['completed_at']), 'Artifact is outside the fixed job attempt')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))
            and type(artifact['size_in_bytes']) is int and artifact['size_in_bytes'] > 0,
            'Original ZIP digest and size are required')


def verify_branch(directory, row, entry, context):
    plan, inventory, _, info, grid = context
    bid = row['record_id']
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
            and report['plan_sha256'] == PLAN_SHA and report['source_revision'] == RUN['head_sha']
            and report['run_id'] == str(RUN['id']) and report['run_attempt'] == str(RUN['run_attempt']),
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
                'branches': [verify_branch(directory / r['record_id'], r, None, context) for r in row['branches']]}
    execution = read(report_path)
    require(execution['model_id'] == plan['model_id'] and execution['plan_sha256'] == PLAN_SHA
            and execution['partition_index'] == row['index'] and execution['selected_branches'] == row['branches']
            and execution['expected_branches'] == len(row['branches'])
            and execution['metadata'] == producer.metadata_for(plan)
            and execution['source_revision'] == RUN['head_sha'] and execution['wrapper_sha256'] == runner_sha
            and execution['run_id'] == str(RUN['id']) and execution['run_attempt'] == str(RUN['run_attempt'])
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
    branches = [verify_branch(directory / r['record_id'], r, by_id.get(r['record_id']), context) for r in row['branches']]
    return {'complete_selected_diagnostics': all(b['complete_diagnostic'] for b in branches),
            'execution_sha256': digest(report_path), 'producer_status': execution['status'],
            'producer_stop_reason': execution.get('stop_reason'), 'branches': branches,
            'unverified_checkpoint_files': sorted(p.name for p in directory.iterdir() if p.name in temporary)}


def preserve_snapshots(selection_path, snapshots, output):
    sources = {'selection': selection_path, **{name: snapshots / (name + '.json') for name in ('run', 'jobs', 'artifacts')}}
    hashes = {name: digest(path) for name, path in sources.items()}
    destination = output / 'api-snapshots' / fingerprint(hashes)
    destination.mkdir(parents=True, exist_ok=True)
    require(not destination.is_symlink(), 'Preserved snapshot directory cannot be a symlink')
    for name, source in sources.items():
        target = destination / (name + '.json')
        if not target.exists():
            with target.open('xb') as stream:
                stream.write(source.read_bytes())
        require(not target.is_symlink() and digest(target) == hashes[name], 'Preserved API snapshot differs')
    return {'directory': str(destination.resolve()), 'sha256': hashes}


def collect(plan_path, bundle, selection_path, snapshots, archives, output):
    context = producer.load_plan(plan_path, PLAN_SHA)
    plan = context[0]
    validation = producer.inputs.validate(bundle, producer.MANIFEST_SHA)
    selection = read(selection_path)
    validate_selection(selection, plan)
    run, jobs, artifacts = (read(snapshots / (name + '.json')) for name in ('run', 'jobs', 'artifacts'))
    require(jobs['total_count'] == len(jobs['jobs']) and artifacts['total_count'] == len(artifacts['artifacts']),
            'All API pages are required')
    require(bind_selection(plan, run, jobs) == selection, 'Live job selection differs from fixed selection')
    preserved = preserve_snapshots(selection_path, snapshots, output)
    runner_sha = hashlib.sha256(subprocess.check_output(['git', 'show', RUN['head_sha'] +
        ':python/scripts/run_ciliberto_later_controls.py'], cwd=ROOT)).hexdigest()
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
            parent = output / str(RUN['id']) / 'attempt-1'
            destination = parent / f'artifact-{artifact["id"]}'
            if not destination.exists():
                archive = archives / f'artifact-{artifact["id"]}.zip'
                if not archive.is_file():
                    missing.append({'index': row['index'], 'reason': 'zip_not_downloaded', 'artifact_id': artifact['id']})
                    continue
                parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='ciliberto-controls-collect-', dir=parent) as temporary:
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
    complete = len(collected) == 256 and len(branches) == 6859 and all(b['complete_diagnostic'] for b in branches)
    complete = complete and not (pending or missing or errors)
    confirmed = sum(b['complete_diagnostic'] and b['status'] == 'confirmed' for b in branches)
    result = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'run': dict(RUN), 'plan_sha256': PLAN_SHA,
              'collector_script_sha256': digest(Path(__file__)),
              'transport_script_sha256': digest(ROOT / 'scripts/collect_ciliberto_full_diagnostics.py'),
              'status': 'verification_failed' if errors else 'controls_confirmed' if complete and confirmed == 6859
                        else 'complete_with_numerical_failures' if complete else 'incomplete',
              'complete_selected_diagnostics': complete, 'all_6859_controls_confirmed': complete and confirmed == 6859,
              'confirmed_branches': confirmed, 'verified_arrays': sum(b['verified_arrays'] for b in branches),
              'partitions': collected, 'pending_indices': pending, 'missing_artifacts': missing, 'collection_errors': errors,
              'preserved_api_snapshots': preserved, 'input_validation': validation,
              'numerical_integrations_performed': 0, 'case_recovery_claimed': False,
              'full_model_coverage_claimed': False, 'full_case_audit_required': True,
              'required_stage_branches': 6859, 'required_full_branches': 7334, 'required_full_cases': 74}
    write(output / 'status.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    bind = sub.add_parser('bind')
    for key in ('plan', 'run', 'jobs', 'output'):
        bind.add_argument('--' + key, type=Path, required=True)
    capture = sub.add_parser('collect')
    for key in ('plan', 'inputs', 'selection', 'snapshots', 'archives', 'output'):
        capture.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'bind':
        require(not args.output.exists(), 'Do not overwrite a fixed collection selection')
        plan = producer.load_plan(args.plan, PLAN_SHA)[0]
        selection = bind_selection(plan, read(args.run), read(args.jobs))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write(args.output, selection)
    else:
        result = collect(args.plan, args.inputs, args.selection, args.snapshots, args.archives, args.output)
        print({k: result[k] for k in ('status', 'confirmed_branches', 'pending_indices', 'missing_artifacts', 'collection_errors')})
        sys.exit(1 if result['collection_errors'] else 0)
