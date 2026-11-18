"""Capture and diagnose every failed branch in the completed Rohwer inventory.

The numerical producer and full-array auditor are unchanged. These diagnostics
do not recover cases: matched controls and conditional replay remain required.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODEL = 'BIOMD0000000038'
SOURCE = ROOT/'results/catalog-breaking-completed-35-20261116'
PARTITIONS = 32
REQUESTS = {'rtol': 1e-10, 'atol': 1e-12, 'reference_rtol': 1e-13, 'reference_atol': 1e-15}
PACKAGES = ('jax', 'jaxlib', 'jaxkineticmodel', 'diffrax', 'equinox', 'scipy',
            'numpy', 'pandas', 'libroadrunner', 'python-libsbml')
NUMERICAL_FILES = ('scripts/diagnose_scipy_breaking.py', 'scripts/audit_scipy_breaking.py',
                   'grn_memory/scipy_reference.py', 'grn_memory/jax_protocols.py',
                   'grn_memory/catalog_repeated.py', 'grn_memory/catalog_breaking.py',
                   'grn_memory/native_protocols.py', 'grn_memory/catalog_validation.py',
                   'pyproject.toml', 'uv.lock')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2)+'\n')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def runtime():
    from grn_memory.catalog_jax import source_hashes
    return {'source_hashes': {**source_hashes(), **{n: digest(ROOT/n) for n in NUMERICAL_FILES}},
            'versions': {n: version(n) for n in PACKAGES}}


def assignments(sources):
    rows = []
    for index, evidence in enumerate(sources):
        original = evidence['original_report']
        require(original['network'] == 35 and original['biomodel_id'] == MODEL,
                'Original source model differs')
        for branch in evidence['failed_branches']:
            require(branch['passed'] is False, 'Passing source branch selected')
            rows.append({'source_partition': index, 'record_id': branch['record_id'],
                         'sample_count': branch['sample_count']})
    rows.sort(key=lambda r: r['record_id'])
    require(len({r['record_id'] for r in rows}) == len(rows), 'Duplicate original failed branch')
    return [{'index': i, 'branches': rows[i::PARTITIONS]} for i in range(PARTITIONS)]


def portable(audit):
    result = json.loads(json.dumps(audit))
    for part in result['partitions']:
        part.pop('directory', None)
    return result


def capture(collection_root, output):
    from scripts.audit_breaking_continuations import evaluate
    from scripts.diagnose_breaking_refinement import capture as capture_original
    require(not output.exists(), 'Use a new capture directory')
    checked = evaluate(read(SOURCE/'selection-plan.json'), [collection_root])
    audit = checked.pop('model_audit')
    require(portable(audit) == portable(read(SOURCE/'audit.json')), 'Original whole-model audit differs')
    require(audit['complete_case_coverage'] and audit['cases'] == 260 and audit['passed_cases'] == 137,
            'Original full case scope differs')
    output.mkdir(parents=True)
    sources, entries = [], []
    for index, part in enumerate(audit['partitions']):
        evidence = capture_original(Path(part['directory'])/(MODEL+'.json'))
        path = output/f'source-partition-{index:02d}.json'
        write(path, evidence)
        sources.append(evidence)
        entries.append({'source_partition': index, 'file': path.name, 'sha256': digest(path),
                        'failed_branches': len(evidence['failed_branches']),
                        'original_report_sha256': evidence['original_report_sha256']})
    fixed = assignments(sources)
    failures = [b for s in sources for b in s['failed_branches']]
    require(len(sources) == 16 and len(failures) == 750, 'Complete original failure inventory differs')
    kinds = Counter('incomplete_output' if b.get('error') else 'completed_mismatch' for b in failures)
    plan = {'schema_version': 1, 'model_id': MODEL, 'network': 35,
            'original_audit_sha256': digest(SOURCE/'audit.json'),
            'source_selection_sha256': digest(SOURCE/'selection-plan.json'),
            'model_sha256': digest(ROOT/'models'/(MODEL+'.xml')),
            'original_cases': 260, 'original_passed_cases': 137,
            'original_failed_cases': sorted(k for k, v in audit['case_summaries'].items() if v['status'] != 'passed'),
            'source_partitions': entries, 'expected_branches': 750,
            'failure_kinds': dict(kinds), 'requests': REQUESTS,
            'acceptance': {'rtol': 2e-5, 'atol': 1e-7},
            'partition_count': PARTITIONS, 'partitions': fixed,
            'runtime': runtime(), 'numerical_integrations_performed_during_capture': 0,
            'case_recovery_claimed': False, 'full_model_coverage_claimed': False}
    write(output/'source-verification.json', checked)
    write(output/'plan.json', plan)
    print(json.dumps({'branches': len(failures), 'failed_cases': len(plan['original_failed_cases']),
                      'failure_kinds': dict(kinds), 'plan_sha256': digest(output/'plan.json')}), flush=True)


def check(inputs, expected_sha, *, check_runtime=True):
    require(digest(inputs/'plan.json') == expected_sha, 'Fixed plan checksum differs')
    plan = read(inputs/'plan.json')
    require(plan['schema_version'] == 1 and plan['network'] == 35 and plan['model_id'] == MODEL
            and plan['expected_branches'] == 750 and plan['partition_count'] == PARTITIONS
            and plan['requests'] == REQUESTS and plan['acceptance'] == {'rtol': 2e-5, 'atol': 1e-7}
            and plan['case_recovery_claimed'] is False and plan['full_model_coverage_claimed'] is False,
            'Diagnostic scope or numerical requests differ')
    require(plan['original_audit_sha256'] == digest(SOURCE/'audit.json')
            and plan['source_selection_sha256'] == digest(SOURCE/'selection-plan.json')
            and plan['model_sha256'] == digest(ROOT/'models'/(MODEL+'.xml')), 'Original evidence identity differs')
    require(len(plan['source_partitions']) == 16, 'All original partitions are required')
    sources = []
    for index, entry in enumerate(plan['source_partitions']):
        require(entry['source_partition'] == index and entry['file'] == f'source-partition-{index:02d}.json',
                'Source partition identity differs')
        path = inputs/entry['file']
        require(not path.is_symlink() and digest(path) == entry['sha256'], 'Source capture checksum differs')
        evidence = read(path)
        require(evidence['original_report_sha256'] == entry['original_report_sha256']
                and len(evidence['failed_branches']) == entry['failed_branches'], 'Source failure inventory differs')
        sources.append(evidence)
    require(plan['partitions'] == assignments(sources)
            and sum(len(p['branches']) for p in plan['partitions']) == 750, 'Complete fixed branch selection differs')
    original = read(SOURCE/'audit.json')
    require(plan['original_cases'] == original['cases'] and plan['original_passed_cases'] == original['passed_cases']
            and plan['original_failed_cases'] == sorted(k for k, v in original['case_summaries'].items()
                                                       if v['status'] != 'passed'), 'Original case inventory differs')
    if check_runtime:
        require(plan['runtime'] == runtime(), 'Numerical sources or package versions differ')
        from scripts.diagnose_scipy_breaking import prepare
        for entry in plan['source_partitions']:
            if entry['failed_branches']:
                prepare(inputs/entry['file'])
    return plan


def compute(inputs, plan, index, output, budget):
    require(type(index) is int and 0 <= index < PARTITIONS, 'Invalid partition index')
    require(0 < budget <= 19800, 'Invalid execution budget')
    require(not output.exists(), 'Use a new output; continuation requires separately verified evidence')
    output.mkdir(parents=True)
    selected = plan['partitions'][index]['branches']
    result = {'model_id': MODEL, 'plan_sha256': digest(inputs/'plan.json'), 'partition_index': index,
              'expected_branches': len(selected), 'selected_branches': selected,
              'producer_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'run_id': os.environ.get('GITHUB_RUN_ID'), 'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'runner_sha256': digest(Path(__file__)), 'runtime': runtime(),
              'status': 'running', 'branches': [], 'case_recovery_claimed': False,
              'started_at': datetime.now(timezone.utc).isoformat()}
    write(output/'execution.json', result)
    deadline = time.monotonic()+budget
    for row in selected:
        if time.monotonic() >= deadline:
            break
        bid, source_index = row['record_id'], row['source_partition']
        directory = output/bid
        command = [sys.executable, str(ROOT/'scripts/diagnose_scipy_breaking.py'),
                   '--evidence', str((inputs/f'source-partition-{source_index:02d}.json').resolve()),
                   '--branch', bid, '--output', str(directory.resolve())]
        for key, value in REQUESTS.items():
            command.extend(['--'+key.replace('_', '-'), str(value)])
        item = {**row, 'status': 'running'}
        result['branches'].append(item)
        write(output/'execution.json', result)
        try:
            completed = subprocess.run(command, cwd=ROOT, timeout=max(.001, deadline-time.monotonic()))
            require(completed.returncode == 0, f'Diagnostic process exited {completed.returncode}')
            from scripts.audit_scipy_breaking import audit
            checked = audit(directory)
            write(directory/'audit.json', checked)
            item.update(status='confirmed' if checked['all_selected_branches_confirmed'] else 'numerical_failure',
                        audit_sha256=digest(directory/'audit.json'), report_sha256=digest(directory/'report.json'))
        except subprocess.TimeoutExpired:
            item.update(status='time_limit', error='Execution budget exhausted; partial files retained')
        except Exception as error:
            item.update(status='execution_or_audit_failure', error=f'{type(error).__name__}: {error}')
        write(output/'execution.json', result)
        print(json.dumps(item), flush=True)
    result.update(status='completed' if len(result['branches']) == len(selected)
                  and all(b['status'] in ('confirmed', 'numerical_failure') for b in result['branches']) else 'incomplete',
                  confirmed_branches=sum(b['status'] == 'confirmed' for b in result['branches']),
                  finished_at=datetime.now(timezone.utc).isoformat())
    write(output/'execution.json', result)
    return 0 if result['confirmed_branches'] == len(selected) else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['capture', 'check', 'compute'])
    parser.add_argument('--collection-root', type=Path)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--index', type=int)
    parser.add_argument('--budget', type=float, default=19200)
    args = parser.parse_args()
    if args.operation == 'capture':
        require(args.collection_root is not None and args.output is not None, 'Capture paths are required')
        capture(args.collection_root, args.output)
    else:
        require(args.inputs is not None and args.plan_sha256 is not None, 'Pinned inputs are required')
        plan = check(args.inputs, args.plan_sha256)
        if args.operation == 'compute':
            require(args.output is not None, 'Output path is required')
            sys.exit(compute(args.inputs, plan, args.index, args.output, args.budget))
        print(json.dumps({'all_750_branches_selected': True, 'numerical_integrations_performed': 0}))
