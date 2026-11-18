"""Run every remaining Ciliberto control with the unchanged numerical producer.

The 6,859 controls include all 200 unsaved potential continuations. This stage
does not claim case recovery: all 7,334 branches and the full 74-case replay
remain required. Complete arrays, numerical failures and interrupted work stay
explicit in the evidence.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_runner import fingerprint
from grn_memory.jax_protocols import supported_model
from scripts import prepare_ciliberto_full_controls as inputs
from scripts import run_ciliberto_full_diagnostics as original
from scripts.diagnose_scipy_breaking_controls import compute_branch

read, write, digest, require = original.read, original.write, original.digest, original.require
PARTITIONS = 256
MANIFEST_SHA = 'ab3b592ed1d25786ff22e4611331e633caf3d2ba0fa00907e4607d865d235857'
EXTRA_FILES = (*inputs.EXTRA_FIXED_FILES, 'scripts/prepare_ciliberto_full_controls.py',
               'scripts/run_ciliberto_later_controls.py', 'scripts/audit_ciliberto_later_controls.py',
               'grn_memory/catalog_runner.py', 'grn_memory/catalog_memory.py')


def runtime():
    result = original.runtime()
    result['source_hashes'].update({name: digest(ROOT / name) for name in EXTRA_FILES})
    return result


def make_plan(inventory, info, grid):
    schedule = read(original.SOURCE / 'computation-plan.json')
    require(digest(original.SOURCE / 'computation-plan.json') == original.SCHEDULE_SHA,
            'Full two-stage schedule differs')
    selected = schedule['stage_2']['branches']
    source = read(original.SOURCE / 'inventory.json')
    require(selected == sorted(set(inventory['branches']) - set(source['reusable_verified_branches'])
                               - set(schedule['stage_1']['branches']))
            and len(selected) == len(set(selected)) == 6859
            and set(inventory['generated_potential_branch_ids']) <= set(selected),
            'Every remaining control and generated continuation is required')
    rows = [{'record_id': bid, 'sample_count': int((grid <= inventory['branches'][bid]['stop']).sum()),
             'origin': inventory['branch_origins'][bid]['kind']} for bid in selected]
    partitions = []
    for index in range(PARTITIONS):
        branches = rows[index::PARTITIONS]
        partitions.append({'index': index, 'branches': branches,
            'uncompressed_numeric_payload_bytes': sum(4 * r['sample_count'] * (len(info['observables']) + 1) * 8
                                                      for r in branches)})
    require(all(inventory['requests']['roadrunner'][key] < inventory['branches'][bid]['integration_settings']['roadrunner'][key]
                for bid in selected for key in ('rtol', 'atol')), 'Requests must refine every original control setting')
    return {'schema_version': 1, 'network': 28, 'model_id': original.MODEL,
            'input_manifest_sha256': MANIFEST_SHA, 'inventory_sha256': fingerprint(inventory),
            'full_computation_plan_sha256': original.SCHEDULE_SHA,
            'model_sha256': info['sha256'], 'sample_grid_sha256': hashlib.sha256(grid.tobytes()).hexdigest(),
            'expected_model_cases': 622, 'selected_case_keys': sorted(inventory['cases']),
            'expected_full_branches': 7334, 'published_branches': 215, 'first_stage_branches': 260,
            'expected_stage_branches': 6859, 'generated_potential_branches': 200,
            'expected_integrations': 27436, 'partition_count': PARTITIONS, 'partitions': partitions,
            'requests': inventory['requests'], 'acceptance': inventory['acceptance'], 'runtime': runtime(),
            'numerical_integrations_performed_during_capture': 0,
            'case_recovery_claimed': False, 'full_model_coverage_claimed': False,
            'full_case_audit_required': True}


def metadata_for(plan):
    keys = ('model_id', 'model_sha256', 'input_manifest_sha256', 'inventory_sha256',
            'full_computation_plan_sha256', 'sample_grid_sha256', 'expected_model_cases',
            'selected_case_keys', 'expected_full_branches', 'expected_stage_branches',
            'requests', 'acceptance', 'runtime', 'case_recovery_claimed',
            'full_model_coverage_claimed', 'full_case_audit_required')
    metadata = {key: plan[key] for key in keys}
    metadata['plan_fingerprint'] = fingerprint(plan)
    metadata['fingerprint'] = fingerprint(metadata)
    return metadata


def load_plan(path, expected_sha):
    require(digest(path) == expected_sha, 'Fixed later-control plan checksum differs')
    plan = read(path)
    inventory, model, info, grid = inputs.prepare_inventory()
    require(plan == make_plan(inventory, info, grid), 'Complete later-control execution plan differs')
    supported = supported_model(model)
    require(supported['sha256'] == info['sha256'] and supported['observables'] == info['observables'],
            'Independent model encoding differs')
    return plan, inventory, model, info, grid


def selected(plan, index):
    require(type(index) is int and 0 <= index < PARTITIONS, 'Invalid fixed partition')
    return plan['partitions'][index]['branches']


def child(plan_path, plan_sha, bid, output):
    plan, inventory, model, info, grid = load_plan(plan_path, plan_sha)
    require(bid in {r['record_id'] for part in plan['partitions'] for r in part['branches']},
            'Branch is outside the complete later-control selection')
    require(not output.exists(), 'Use a new child directory; verified continuation is separate')
    output.mkdir(parents=True)
    metadata = metadata_for(plan)
    report = {'metadata': metadata, 'record_id': bid, 'plan_sha256': plan_sha,
              'status': 'running', 'branch': None,
              'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'started_at': datetime.now(timezone.utc).isoformat()}
    write(output / 'report.json', report)
    # This is the original, hash-pinned implementation used by the published
    # complete-case recovery. No solver, horizon, reset or tolerance is changed.
    row = compute_branch(bid, inventory['branches'][bid], output, metadata, grid, model, info)
    report.update(status='completed', branch=row, finished_at=datetime.now(timezone.utc).isoformat())
    write(output / 'report.json', report)
    return 0


def compute(plan_path, plan_sha, bundle, index, output, budget):
    require(0 < budget <= 19800, 'Invalid computation budget')
    require(not output.exists(), 'Use a new output directory; do not overwrite or silently resume evidence')
    plan, inventory, _, info, grid = load_plan(plan_path, plan_sha)
    rows = selected(plan, index)
    validated = inputs.validate(bundle, MANIFEST_SHA)
    require(validated['complete_input_scope_verified'], 'Complete authenticated inputs are required')
    output.mkdir(parents=True)
    write(output / 'input-validation.json', validated)
    execution = {'model_id': original.MODEL, 'plan_sha256': plan_sha, 'partition_index': index,
                 'selected_branches': rows, 'expected_branches': len(rows), 'metadata': metadata_for(plan),
                 'input_validation_sha256': digest(output / 'input-validation.json'),
                 'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                 'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
                 'wrapper_sha256': digest(Path(__file__)), 'status': 'running', 'branches': [],
                 'case_recovery_claimed': False, 'full_model_coverage_claimed': False,
                 'full_case_audit_required': True, 'started_at': datetime.now(timezone.utc).isoformat()}
    write(output / 'execution.json', execution)
    deadline = time.monotonic() + budget
    from scripts.audit_ciliberto_later_controls import audit
    for row in rows:
        if time.monotonic() >= deadline:
            execution['stop_reason'] = 'time_limit'
            break
        bid = row['record_id']
        payload = 4 * row['sample_count'] * (len(info['observables']) + 1) * 8
        # Leave room for all four numeric arrays, archive headers, checkpoints
        # and a 512 MiB margin. A disk stop retains all existing evidence.
        if shutil.disk_usage(output).free < payload + 512 * 1024**2:
            execution['stop_reason'] = 'disk_limit'
            break
        entry = {**row, 'status': 'running'}
        execution['branches'].append(entry)
        write(output / 'execution.json', execution)
        directory = output / bid
        command = [sys.executable, str(Path(__file__).resolve()), 'child',
                   '--plan', str(plan_path.resolve()), '--plan-sha256', plan_sha,
                   '--branch', bid, '--output', str(directory.resolve())]
        try:
            result = subprocess.run(command, cwd=ROOT, timeout=max(.001, deadline - time.monotonic()))
            require(result.returncode == 0, f'Child process exited {result.returncode}')
            checked = audit(directory, plan, inventory, info, grid, plan_sha)
            require(read(directory / 'report.json')['source_revision'] == execution['source_revision']
                    and read(directory / 'report.json')['run_id'] == execution['run_id']
                    and read(directory / 'report.json')['run_attempt'] == execution['run_attempt'],
                    'Child execution lineage differs')
            write(directory / 'audit.json', checked)
            entry.update(status='confirmed' if checked['status'] == 'confirmed' else 'numerical_failure',
                         report_sha256=digest(directory / 'report.json'), audit_sha256=digest(directory / 'audit.json'))
        except subprocess.TimeoutExpired:
            entry.update(status='time_limit', error='Computation budget exhausted; partial evidence retained')
        except Exception as error:
            entry.update(status='execution_or_audit_failure', error=f'{type(error).__name__}: {error}')
        write(output / 'execution.json', execution)
        print(json.dumps({'partition': index, 'branch': bid, 'status': entry['status']}), flush=True)
    finished = len(execution['branches']) == len(rows) and all(
        entry['status'] in ('confirmed', 'numerical_failure') for entry in execution['branches'])
    execution.update(status='completed' if finished else 'incomplete',
                     confirmed_branches=sum(r['status'] == 'confirmed' for r in execution['branches']),
                     finished_at=datetime.now(timezone.utc).isoformat())
    write(output / 'execution.json', execution)
    return 0 if execution['confirmed_branches'] == len(rows) else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['capture', 'check', 'child', 'compute'])
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--index', type=int)
    parser.add_argument('--branch')
    parser.add_argument('--budget', type=float, default=19200)
    args = parser.parse_args()
    if args.operation == 'capture':
        require(args.output is not None and not args.output.exists(), 'Use a new plan output file')
        inventory, _, info, grid = inputs.prepare_inventory()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write(args.output, make_plan(inventory, info, grid))
        print(json.dumps({'plan_sha256': digest(args.output), 'branches': 6859, 'partitions': PARTITIONS}))
    else:
        require(args.plan is not None and args.plan_sha256 is not None, 'Pinned execution plan required')
        if args.operation == 'check':
            load_plan(args.plan, args.plan_sha256)
            if args.inputs is not None:
                print(json.dumps(inputs.validate(args.inputs, MANIFEST_SHA)))
            print(json.dumps({'all_6859_controls_selected': True, 'numerical_integrations_performed': 0}))
        elif args.operation == 'child':
            require(args.branch is not None and args.output is not None, 'Child branch and output required')
            sys.exit(child(args.plan, args.plan_sha256, args.branch, args.output))
        else:
            require(args.inputs is not None and args.output is not None and args.index is not None,
                    'Input bundle, output and partition required')
            sys.exit(compute(args.plan, args.plan_sha256, args.inputs, args.index, args.output, args.budget))
