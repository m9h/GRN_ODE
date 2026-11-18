"""Collect the fixed Ueda cloud run and audit all original case controls offline.

No network requests, numerical integration, job dispatch or evidence selection
by outcome occurs here. Failed jobs and failed numerical comparisons are retained.
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

from grn_memory.breaking_audit import require
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain
from grn_memory.scipy_breaking_recovery import LABELS
from scripts.audit_scipy_breaking import trajectory
from scripts.audit_scipy_breaking_cases import audit as audit_cases, check_outcome
from scripts.collect_breaking_runs import extract
from scripts.continue_ueda_cases import load_inputs, selected
from scripts.prepare_ueda_continuation import digest, read, verify_snapshot

WORKFLOW = '.github/workflows/ueda-case-continuation.yml'


def bind_selection(plan, plan_sha, run, jobs):
    require(jobs['total_count'] == len(jobs['jobs']), 'All job pages are required')
    gates = [j for j in jobs['jobs'] if j['name'] == 'validation']
    require(len(gates) == 1 and gates[0]['conclusion'] == 'success', 'Linux validation must pass first')
    rows = []
    for index in range(plan['shard_count']):
        name = f'ueda-case-partition-{index}'
        matches = [j for j in jobs['jobs'] if j['name'] == name]
        require(len(matches) == 1, 'Every fixed compute job must exist exactly once')
        rows.append({'index': index, 'job_id': matches[0]['id'], 'job_name': name,
                     'artifact_name': f'ueda-cases-BIOMD0000000022-partition-{index}-attempt-{run["run_attempt"]}',
                     'branch_ids': selected(plan, index)})
    selection = {'schema_version': 1, 'repository': 'm9h/GRN_ODE', 'workflow_path': WORKFLOW,
                 'run_id': run['id'], 'run_attempt': run['run_attempt'], 'workflow_id': run['workflow_id'],
                 'head_sha': run['head_sha'], 'plan_sha256': plan_sha,
                 'original_report_sha256': plan['original_report_sha256'], 'selected': rows,
                 'validation_job_id': gates[0]['id'], 'case_recovery_claimed': False}
    validate_selection(selection, plan)
    validate_job(selection, {'job_id': gates[0]['id'], 'job_name': 'validation'}, run, gates[0])
    for row in rows:
        validate_job(selection, row, run, next(j for j in jobs['jobs'] if j['id'] == row['job_id']))
    return selection


def validate_selection(selection, plan):
    require(selection['schema_version'] == 1 and selection['repository'] == 'm9h/GRN_ODE'
            and selection['workflow_path'] == WORKFLOW and selection['case_recovery_claimed'] is False,
            'Collection identity differs')
    require(selection['original_report_sha256'] == plan['original_report_sha256']
            and all(type(selection[k]) is int and selection[k] > 0
                    for k in ('run_id', 'run_attempt', 'workflow_id', 'validation_job_id'))
            and re.fullmatch(r'[0-9a-f]{40}', selection['head_sha']), 'Immutable producer identity required')
    rows = selection['selected']
    require([r['index'] for r in rows] == list(range(plan['shard_count']))
            and len({r['job_id'] for r in rows}) == plan['shard_count'], 'Every fixed partition is required')
    for row in rows:
        i = row['index']
        require(type(row['job_id']) is int and row['job_id'] > 0
                and row['job_name'] == f'ueda-case-partition-{i}'
                and row['artifact_name'] == f'ueda-cases-BIOMD0000000022-partition-{i}-attempt-{selection["run_attempt"]}'
                and row['branch_ids'] == selected(plan, i), 'Fixed partition membership differs')


def validate_job(selection, row, run, job):
    require(run['id'] == selection['run_id'] and run['run_attempt'] == selection['run_attempt']
            and run['head_sha'] == selection['head_sha'] and run['workflow_id'] == selection['workflow_id']
            and run['path'] == WORKFLOW, 'Producer run identity differs')
    require(job['id'] == row['job_id'] and job['name'] == row['job_name']
            and job['run_id'] == run['id'] and job['run_attempt'] == run['run_attempt']
            and job['head_sha'] == run['head_sha'], 'Producer job identity differs')


def validate_artifact(selection, row, run, job, artifact):
    validate_job(selection, row, run, job)
    require(artifact['name'] == row['artifact_name'] and artifact['expired'] is False
            and artifact['workflow_run']['id'] == run['id']
            and artifact['workflow_run']['head_sha'] == run['head_sha'], 'Artifact identity differs')
    require(job['status'] == 'completed' and job['completed_at']
            and datetime.fromisoformat(job['started_at']) <= datetime.fromisoformat(artifact['created_at'])
            <= datetime.fromisoformat(job['completed_at']), 'Artifact is outside selected job attempt')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', '')), 'Original ZIP digest required')


def verify_extraction(archive, evidence):
    hashes = {}
    with zipfile.ZipFile(archive) as stream:
        for member in stream.infolist():
            if member.is_dir():
                continue
            require(Path(member.filename).name == member.filename and member.filename not in hashes,
                    'Unsafe or duplicate artifact member')
            path = evidence / member.filename
            require(path.is_file() and not path.is_symlink(), 'Missing or unsafe extracted member')
            with stream.open(member) as source:
                sha = hashlib.file_digest(source, 'sha256').hexdigest()
            require(digest(path) == sha, 'Extracted artifact bytes differ')
            hashes[member.filename] = sha
    require(set(hashes) == {p.name for p in evidence.iterdir()}, 'Unexpected extracted file')
    return hashes


def verify_branch(directory, bid, entry, original, inventory, info, grid):
    path = directory / (bid + '.json')
    if not path.exists():
        require(entry is None, 'Reported finished branch is missing')
        return {'record_id': bid, 'attempt_finished': False, 'arrays_verified': 0, 'status': 'no_checkpoint'}
    record = read(path)
    require(record['record_id'] == bid and record['specification'] == inventory['branches'][bid]
            and record['fingerprint'] == original['fingerprint'] and record['case_recovery_claimed'] is False
            and 'reused_from' not in record, 'New branch identity or scope differs')
    require(set(record['integrations']) <= set(LABELS), 'Unexpected integration request')
    spec = inventory['branches'][bid]
    times = grid[grid <= spec['stop']]
    trains = [ResetTrain(**t) for t in spec['reset_trains']]
    traces = {}
    for label, outcome in record['integrations'].items():
        if entry is None and not outcome.get('completed') and 'error' not in outcome:
            require(outcome.get('completed') is False and outcome['request'] == original['requests'][label],
                    'Active integration settings differ')
            continue
        if check_outcome(outcome, label, original['requests'][label], times, info['observables'], trains, info['sha256']):
            require(label in record['traces'], 'Complete integration lacks its array')
            traces[label] = trajectory(directory, bid, label, record['traces'][label], times, info['observables'])
    require(set(traces) == set(record['traces']), 'Unexpected saved array')
    comparisons = {a + '_vs_' + b: comparison(traces[a], traces[b], **original['acceptance'])
                   for i, a in enumerate(LABELS) for b in LABELS[i+1:] if a in traces and b in traces}
    status = ('incomplete' if len(traces) != 4 else 'confirmed'
              if all(c['passed'] for c in comparisons.values()) else 'mismatch')
    if entry is not None:
        require(set(record['integrations']) == set(LABELS), 'Finished branch lacks an integration outcome')
        require(record['comparisons'] == comparisons and record['status'] == status,
                'Saved branch result does not reproduce from complete arrays')
        require(entry == {'record_id': bid, 'file': path.name, 'sha256': digest(path), 'status': status},
                'Finished branch checkpoint differs')
    return {'record_id': bid, 'attempt_finished': entry is not None, 'arrays_verified': len(traces),
            'record_sha256': digest(path), 'comparisons': comparisons, 'status': status}


def verify_partition(directory, selection, row, plan, original, inventory, info, grid, wrapper_sha):
    lineage = read(directory/'lineage.json')
    require(lineage['schema_version'] == 1 and lineage['plan_sha256'] == selection['plan_sha256']
            and lineage['original_report_sha256'] == selection['original_report_sha256']
            and lineage['partition_index'] == row['index'] and lineage['selected_branch_ids'] == row['branch_ids']
            and lineage['full_selected_branch_ids'] == plan['selected_branch_ids']
            and lineage['source_revision'] == selection['head_sha'] and lineage['wrapper_sha256'] == wrapper_sha
            and lineage['github_run_id'] == str(selection['run_id'])
            and lineage['github_run_attempt'] == str(selection['run_attempt'])
            and lineage['github_job'] == 'compute', 'Partition lineage differs')
    require(lineage['numerical_implementation_sha256'] == original['implementation_sha256']
            and lineage['versions'] == original['versions']
            and all(isinstance(lineage[k], str) and lineage[k] for k in ('platform', 'machine', 'python')),
            'Partition numerical source or runtime differs')
    require(all(lineage[k] is False for k in ('case_recovery_claimed', 'full_model_coverage_claimed',
                                            'byte_identical_restoration_claimed')),
            'Producer cannot claim recovery or restoration')
    require(lineage['status'] in ('running', 'completed'), 'Unknown partition state')
    entries = {b['record_id']: b for b in lineage['branches']}
    require(len(entries) == len(lineage['branches'])
            and list(entries) == row['branch_ids'][:len(entries)], 'Finished branch prefix differs')
    active = lineage.get('active_branch')
    if active is not None:
        require(active in row['branch_ids'] and row['branch_ids'].index(active) in (len(entries)-1, len(entries)),
                'Active branch is outside the preserved prefix')
    if lineage['status'] == 'completed':
        require(list(entries) == row['branch_ids'] and active is None, 'Completed partition omits required branches')
    permitted = set(entries) | ({active} if active is not None else set())
    require({p.stem for p in directory.glob('*.json') if len(p.stem) == 64} <= permitted,
            'Record is outside the declared completed or active work')
    branches = [verify_branch(directory, bid, entries.get(bid), original, inventory, info, grid)
                for bid in row['branch_ids']]
    expected_files = {'lineage.json'}
    for branch in branches:
        path = directory/(branch['record_id']+'.json')
        if path.exists():
            expected_files.add(path.name)
            expected_files.update(v['file'] for v in read(path)['traces'].values())
    require(expected_files == {p.name for p in directory.iterdir()}, 'Unreferenced artifact evidence')
    complete = lineage['status'] == 'completed' and all(b['attempt_finished'] for b in branches)
    return {'complete_selected_attempts': complete, 'branches': branches,
            'lineage_sha256': digest(directory/'lineage.json')}


def collect(inputs, selection_path, snapshots, archives, output):
    selection = read(selection_path)
    experiment = load_inputs(inputs, selection['plan_sha256'])
    plan, original, inventory, _, info, grid = experiment
    validate_selection(selection, plan)
    run, jobs, artifacts = (read(snapshots/name) for name in ('run.json', 'jobs.json', 'artifacts.json'))
    require(jobs['total_count'] == len(jobs['jobs']) and artifacts['total_count'] == len(artifacts['artifacts']),
            'API snapshots must include every page')
    gates = [j for j in jobs['jobs'] if j['id'] == selection['validation_job_id']]
    require(len(gates) == 1 and gates[0]['conclusion'] == 'success', 'Selected Linux validation did not pass')
    validate_job(selection, {'job_id': selection['validation_job_id'], 'job_name': 'validation'}, run, gates[0])
    wrapper_sha = hashlib.sha256(subprocess.check_output(['git', 'show', selection['head_sha']+
        ':python/scripts/continue_ueda_cases.py'], cwd=ROOT)).hexdigest()
    collected, pending, missing, errors = [], [], [], []
    for row in selection['selected']:
        try:
            matches = [j for j in jobs['jobs'] if j['id'] == row['job_id']]
            require(len(matches) == 1, 'Selected job is missing or duplicated')
            job = matches[0]
            validate_job(selection, row, run, job)
            if job['status'] != 'completed':
                pending.append(row['index'])
                continue
            matches = [a for a in artifacts['artifacts'] if a['name'] == row['artifact_name']]
            if not matches:
                missing.append({'index': row['index'], 'reason': 'no_artifact'})
                continue
            require(len(matches) == 1, 'Selected artifact is duplicated')
            artifact = matches[0]
            validate_artifact(selection, row, run, job, artifact)
            parent = output/str(selection['run_id'])/f'attempt-{selection["run_attempt"]}'
            destination = parent/f'artifact-{artifact["id"]}'
            if not destination.exists():
                source_zip = archives/f'artifact-{artifact["id"]}.zip'
                if not source_zip.is_file():
                    missing.append({'index': row['index'], 'reason': 'zip_not_downloaded', 'artifact_id': artifact['id']})
                    continue
                parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='collect-', dir=parent) as temporary:
                    stage = Path(temporary)/'artifact'
                    stage.mkdir()
                    shutil.copyfile(source_zip, stage/'download.zip')
                    require(digest(stage/'download.zip') == artifact['digest'].removeprefix('sha256:'), 'Original ZIP differs')
                    extract(stage/'download.zip', stage/'evidence')
                    stage.rename(destination)
            archive, evidence = destination/'download.zip', destination/'evidence'
            require(archive.stat().st_size == artifact['size_in_bytes']
                    and digest(archive) == artifact['digest'].removeprefix('sha256:'), 'Saved ZIP size or hash differs')
            hashes = verify_extraction(archive, evidence)
            verified = verify_partition(evidence, selection, row, plan, original, inventory, info, grid, wrapper_sha)
            collected.append({**row, **verified, 'artifact_id': artifact['id'], 'archive_sha256': artifact['digest'],
                              'evidence': str(evidence.resolve()), 'evidence_sha256': hashes,
                              'job_conclusion': job['conclusion']})
        except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
            errors.append({'index': row['index'], 'error': f'{type(error).__name__}: {error}'})
    complete = (len(collected) == plan['shard_count'] and all(r['complete_selected_attempts'] for r in collected)
                and not (pending or missing or errors))
    status = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'status': 'verification_failed' if errors else 'ready_for_case_audit' if complete else 'incomplete',
              'selection_sha256': digest(selection_path), 'complete_selected_attempts': complete,
              'pending_indices': pending, 'missing_artifacts': missing, 'collection_errors': errors,
              'partitions': collected, 'source_snapshot_sha256': {n: digest(snapshots/n)
                  for n in ('run.json', 'jobs.json', 'artifacts.json')},
              'numerical_integrations_performed': 0, 'case_recovery_claimed': False, 'full_model_coverage_claimed': False}
    output.mkdir(parents=True, exist_ok=True)
    write_json(output/'status.json', status)
    return status, experiment


def assemble(inputs, preserved, restored, destination, status, experiment):
    require(status['complete_selected_attempts'], 'All fixed partitions must finish before assembly')
    require(not destination.exists(), 'Use a fresh assembly directory')
    plan, original, inventory, *_ = experiment
    verify_snapshot(preserved, inputs/'preservation-manifest.json')
    cloud = {b['record_id']: {**b, 'partition': p} for p in status['partitions'] for b in p['branches']}
    require(len(cloud) == sum(len(p['branches']) for p in status['partitions'])
            and set(cloud) == set(plan['selected_branch_ids']), 'Complete cloud inventory differs')
    historical = {b['record_id']: b for b in original['branches']}
    import_rows = {b['record_id']: b for b in read(inputs/'restoration-proof.json')['branches']}
    require(set(import_rows) == set(plan['imported_branch_ids']), 'Every published import is required')
    baseline = inventory['full_untreated_control']
    order = [baseline] + sorted(set(inventory['branches'])-{baseline})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ueda-assemble-', dir=destination.parent) as temporary:
        stage = Path(temporary)/'evidence'
        stage.mkdir()
        for name in ('source-evidence.json', 'original-case-plan.json', 'source-branches.jsonl.gz',
                     'source-branches-provenance.json', 'inventory.json', 'reused-report.json', 'reused-audit.json'):
            shutil.copyfile(inputs/name, stage/name)
        shutil.copyfile(inputs/'report.json', stage/'historical-report.json')
        rows, provenance = [], []
        for bid in order:
            if bid in cloud:
                item = cloud[bid]
                source, sha, kind = Path(item['partition']['evidence']), item['record_sha256'], 'cloud'
                lineage = source/'lineage.json'
                require(digest(lineage) == item['partition']['lineage_sha256'], 'Verified lineage changed')
                target = stage/'cloud-lineage'/f'partition-{item["partition"]["index"]}.json'
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(lineage, target)
            elif bid in plan['preserved_complete_branch_ids']:
                source, sha, kind = preserved, historical[bid]['sha256'], 'preserved'
            else:
                require(bid in import_rows, 'Required branch has no evidence source')
                source, sha, kind = restored, import_rows[bid]['sha256'], 'published_import'
            if bid in import_rows:
                require(digest(restored/(bid+'.json')) == import_rows[bid]['sha256'], 'Published import record changed')
                if bid in historical:
                    require(import_rows[bid]['sha256'] == historical[bid]['sha256'], 'Exact historical import differs')
            path = source/(bid+'.json')
            require(digest(path) == sha, 'Verified branch record changed')
            record = read(path)
            shutil.copyfile(path, stage/path.name)
            for label, saved in record['traces'].items():
                require(label in LABELS and saved['file'] == bid+'-'+label+'.npz'
                        and digest(source/saved['file']) == saved['sha256'], 'Chosen array differs')
                shutil.copyfile(source/saved['file'], stage/saved['file'])
            rows.append({'record_id': bid, 'file': path.name, 'sha256': sha, 'status': record['status']})
            provenance.append({'record_id': bid, 'origin': kind, 'record_sha256': sha,
                **({'artifact_id': cloud[bid]['partition']['artifact_id'],
                    'archive_sha256': cloud[bid]['partition']['archive_sha256']} if bid in cloud else {})})
        assembled = deepcopy(original)
        assembled.update(status='completed', branches=rows,
                         confirmed_branches=sum(r['status']=='confirmed' for r in rows),
                         purpose='Assembled complete case evidence; historical-report.json remains unchanged.',
                         assembly_original_report_sha256=plan['original_report_sha256'],
                         finished_at=datetime.now(timezone.utc).isoformat())
        write_json(stage/'report.json', assembled)
        write_json(stage/'assembly-provenance.json', {'selection_sha256': status['selection_sha256'],
            'original_report_sha256': plan['original_report_sha256'], 'branches': provenance,
            'source_snapshot_sha256': status['source_snapshot_sha256'], 'case_recovery_claimed': False})
        audit = audit_cases(stage)
        write_json(stage/'audit.json', audit)
        stage.rename(destination)
    return {'audit_sha256': digest(destination/'audit.json'), 'selected_cases': audit['selected_cases'],
            'recovered_selected_cases': audit['recovered_selected_cases'], 'baseline_passed': audit['baseline_passed'],
            'full_model_coverage_claimed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    bind = sub.add_parser('bind')
    for name in ('inputs', 'run', 'jobs', 'output'):
        bind.add_argument('--'+name, type=Path, required=True)
    bind.add_argument('--plan-sha256', required=True)
    collect_parser = sub.add_parser('collect')
    for name in ('inputs', 'selection', 'snapshots', 'archives', 'output'):
        collect_parser.add_argument('--'+name, type=Path, required=True)
    for name in ('assemble', 'preserved', 'restored'):
        collect_parser.add_argument('--'+name, type=Path)
    args = parser.parse_args()
    if args.command == 'bind':
        plan, *_ = load_inputs(args.inputs, args.plan_sha256)
        require(not args.output.exists(), 'Do not overwrite a fixed collection selection')
        write_json(args.output, bind_selection(plan, args.plan_sha256, read(args.run), read(args.jobs)))
    else:
        status, experiment = collect(args.inputs, args.selection, args.snapshots, args.archives, args.output)
        if args.assemble:
            require(args.preserved is not None and args.restored is not None, 'Preserved and imported evidence required')
            result = assemble(args.inputs, args.preserved, args.restored, args.assemble, status, experiment)
            write_json(args.output/'case-audit-result.json', result)
        print({k: status[k] for k in ('status', 'pending_indices', 'missing_artifacts', 'collection_errors')})
        sys.exit(1 if status['collection_errors'] else 0)
