"""Bind all 32 continuation jobs, retain their original ZIPs, and audit all 750 branches."""

import argparse
from datetime import datetime
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import continue_rohwer_checkpoint as continuation
from scripts.run_rohwer_breaking_diagnostics import digest, read, require, write

WORKFLOW = '.github/workflows/rohwer-first-continuation.yml'


def validate_run(run, revision):
    require(re.fullmatch('[0-9a-f]{40}', revision) and run['head_sha'] == revision
            and run['path'] == WORKFLOW and run['event'] == 'workflow_dispatch'
            and type(run['id']) is int and run['id'] > 0 and run['run_attempt'] == 1,
            'Continuation run identity differs; a rerun requires a new explicit selection')


def validate_job(row, run, job):
    require(job['id'] == row['job_id'] and job['name'] == row['job_name']
            and job['run_id'] == run['id'] and job['run_attempt'] == run['run_attempt']
            and job['head_sha'] == run['head_sha'], 'Selected continuation job differs')


def bind(plan, run, jobs, revision, context):
    validate_run(run, revision)
    require(jobs['total_count'] == len(jobs['jobs']) == 33, 'Every actual continuation job is required')
    gates = [j for j in jobs['jobs'] if j['name'] == 'validation']
    require(len(gates) == 1 and gates[0]['status'] == 'completed' and gates[0]['conclusion'] == 'success',
            'Continuation Linux validation must pass')
    validate_job({'job_id': gates[0]['id'], 'job_name': 'validation'}, run, gates[0])
    rows = []
    for part in plan['partitions']:
        i = part['index']
        matches = [j for j in jobs['jobs'] if j['name'] == f'rohwer-checkpoint-continuation-{i}']
        require(len(matches) == 1, 'Every fixed continuation partition must exist exactly once')
        row = {'index': i, 'job_id': matches[0]['id'], 'job_name': matches[0]['name'],
               'artifact_name': f'rohwer-checkpoint-continuation-{continuation.producer.MODEL}-partition-{i}-attempt-1',
               'branches': part['branches']}
        validate_job(row, run, matches[0])
        rows.append(row)
    require(len({j['id'] for j in jobs['jobs']}) == 33, 'Duplicate job identity')
    return {'schema_version': 1, 'repository': 'm9h/GRN_ODE', 'workflow_path': WORKFLOW,
            'run_id': run['id'], 'run_attempt': 1, 'producer_revision': revision,
            'validation_job_id': gates[0]['id'], 'plan_sha256': continuation.original.PLAN_SHA,
            'binding_sha256': context['binding_sha256'], 'generation': context['binding']['generation'],
            'selected': rows, 'case_recovery_claimed': False, 'full_model_coverage_claimed': False}


def validate_artifact(row, run, job, artifact):
    validate_job(row, run, job)
    require(type(artifact['id']) is int and artifact['id'] > 0
            and artifact['name'] == row['artifact_name'] and artifact['expired'] is False
            and artifact['workflow_run']['id'] == run['id']
            and artifact['workflow_run']['head_sha'] == run['head_sha'], 'Continuation artifact identity differs')
    require(job['status'] == 'completed' and job['completed_at']
            and datetime.fromisoformat(job['started_at']) <= datetime.fromisoformat(artifact['created_at'])
            <= datetime.fromisoformat(job['completed_at']), 'Artifact is outside selected continuation job')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', artifact.get('digest', ''))
            and type(artifact['size_in_bytes']) is int and artifact['size_in_bytes'] > 0,
            'Original continuation ZIP size and checksum required')


def collect(selection_path, snapshots, archives, output, bindings=continuation.BINDINGS, binding_sha=continuation.BINDING_SHA):
    context = continuation.check_bindings(bindings, binding_sha)
    plan, requirements = context['plan'], context['requirements']
    selection = read(selection_path)
    run, jobs, artifacts = (read(snapshots/(n+'.json')) for n in ('run', 'jobs', 'artifacts'))
    require(selection == bind(plan, run, jobs, selection['producer_revision'], context), 'Fixed continuation selection differs')
    require(artifacts['total_count'] == len(artifacts['artifacts']), 'All artifact pages required')
    pending, missing, errors, partitions = [], [], [], []
    for row in selection['selected']:
        try:
            job = next(j for j in jobs['jobs'] if j['id'] == row['job_id'])
            if job['status'] != 'completed':
                pending.append(row['index'])
                continue
            matches = [a for a in artifacts['artifacts'] if a['name'] == row['artifact_name']]
            if not matches:
                missing.append({'index': row['index'], 'reason': 'no_artifact'})
                continue
            require(len(matches) == 1, 'Duplicate continuation artifact')
            artifact = matches[0]
            validate_artifact(row, run, job, artifact)
            destination = output/str(run['id'])/'attempt-1'/f'artifact-{artifact["id"]}'
            if not destination.exists():
                archive = archives/f'artifact-{artifact["id"]}.zip'
                if not archive.is_file():
                    missing.append({'index': row['index'], 'reason': 'zip_not_downloaded', 'artifact_id': artifact['id']})
                    continue
                require(not archive.is_symlink() and digest(archive) == artifact['digest'].removeprefix('sha256:')
                        and archive.stat().st_size == artifact['size_in_bytes'], 'Original continuation ZIP differs')
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='rohwer-continuation-', dir=destination.parent) as tmp:
                    stage = Path(tmp)/'artifact'
                    stage.mkdir()
                    shutil.copyfile(archive, stage/'download.zip')
                    continuation.original.verify_zip(stage/'download.zip', stage/'evidence', extract=True)
                    stage.rename(destination)
            archive, evidence = destination/'download.zip', destination/'evidence'
            require(not archive.is_symlink() and digest(archive) == artifact['digest'].removeprefix('sha256:')
                    and archive.stat().st_size == artifact['size_in_bytes'], 'Cached original ZIP differs')
            files = continuation.original.verify_zip(archive, evidence)
            checked = continuation.audit(evidence, row['index'], plan, context,
                        revision=selection['producer_revision'], run_id=str(run['id']), run_attempt='1')
            partitions.append({**row, **checked, 'artifact_id': artifact['id'], 'archive_sha256': artifact['digest'],
                               'evidence': str(evidence.resolve()), 'evidence_sha256': files,
                               'job_conclusion': job['conclusion']})
        except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
            errors.append({'index': row['index'], 'error': f'{type(error).__name__}: {error}'})
    branches = [b for p in partitions for b in p['branches']]
    complete = len(partitions) == 32 and len(branches) == 750 and all(b['complete_diagnostic'] for b in branches)
    complete = complete and not (pending or missing or errors)
    confirmed = sum(b['complete_diagnostic'] and b['status'] == 'confirmed' for b in branches)
    preserved = sum(p['parent_arrays_preserved'] for p in partitions)
    require(len(partitions) != 32 or preserved == requirements['parent_arrays'], 'Complete collection must preserve every parent array')
    result = {'status': 'verification_failed' if errors else 'diagnostics_confirmed' if complete and confirmed == 750
              else 'complete_with_numerical_failures' if complete else 'incomplete',
              'selection_sha256': digest(selection_path), 'complete_selected_diagnostics': complete,
              'fixed_branch_count': 750, 'confirmed_branches': confirmed,
              'verified_arrays': sum(b['verified_arrays'] for b in branches), 'parent_arrays_preserved': preserved,
              'partitions': partitions, 'pending_indices': pending, 'missing_artifacts': missing,
              'collection_errors': errors, 'numerical_integrations_performed': 0,
              'case_recovery_claimed': False, 'full_model_coverage_claimed': False,
              'source_snapshot_sha256': {n: digest(snapshots/(n+'.json')) for n in ('run', 'jobs', 'artifacts')}}
    output.mkdir(parents=True, exist_ok=True)
    write(output/'status.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    binder = sub.add_parser('bind')
    for name in ('run', 'jobs', 'output'):
        binder.add_argument('--'+name, type=Path, required=True)
    binder.add_argument('--revision', required=True)
    collector = sub.add_parser('collect')
    for name in ('selection', 'snapshots', 'archives', 'output'):
        collector.add_argument('--'+name, type=Path, required=True)
    for command in (binder, collector):
        command.add_argument('--bindings', type=Path, default=continuation.BINDINGS)
        command.add_argument('--binding-sha', default=continuation.BINDING_SHA)
    args = parser.parse_args()
    if args.operation == 'bind':
        context = continuation.check_bindings(args.bindings, args.binding_sha)
        require(not args.output.exists(), 'Do not overwrite an immutable selection')
        write(args.output, bind(context['plan'], read(args.run), read(args.jobs), args.revision, context))
    else:
        result = collect(args.selection, args.snapshots, args.archives, args.output, args.bindings, args.binding_sha)
        print({k: result[k] for k in ('status', 'confirmed_branches', 'verified_arrays', 'parent_arrays_preserved',
                                     'pending_indices', 'missing_artifacts', 'collection_errors')})
        sys.exit(1 if result['collection_errors'] else 0)
