"""Compute the fixed missing Ueda branches with the unchanged numerical producer.

The original snapshot and published imports stay separate. These new arrays
must join them in the unchanged complete-case audit before recovery is claimed.
"""

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_jax import source_hashes
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from grn_memory.scipy_breaking_recovery import prepare_inventory
from scripts.audit_scipy_breaking import PACKAGES, SOURCES
from scripts.audit_scipy_breaking_cases import META_KEYS
from scripts.diagnose_scipy_breaking_controls import EXTRA_SOURCES, compute_branch
from scripts.prepare_ueda_continuation import digest, read, select_remaining


def selected(plan, index):
    count = plan['shard_count']
    require(type(index) is int and type(count) is int and 0 <= index < count
            and 1 <= count <= len(plan['selected_branch_ids']), 'Invalid fixed partition')
    return plan['selected_branch_ids'][index::count]


def load_inputs(directory, plan_sha):
    require(digest(directory/'continuation-plan.json') == plan_sha, 'Continuation plan hash differs')
    plan, report = read(directory/'continuation-plan.json'), read(directory/'report.json')
    require(plan['schema_version'] == 1 and plan['case_recovery_claimed'] is False
            and plan['full_model_coverage_claimed'] is False, 'Unsupported plan or recovery claim')
    require(digest(directory/'report.json') == plan['original_report_sha256']
            and fingerprint({k: report[k] for k in META_KEYS}) == report['fingerprint'],
            'Original report identity differs')
    inventory, path, info, grid = prepare_inventory(directory/'source-evidence.json',
        directory/'original-case-plan.json', plan['original_source_revision'], directory/'source-branches.jsonl.gz')
    require(read(directory/'inventory.json') == inventory
            and fingerprint(inventory) == plan['inventory_sha256'] == report['inventory_sha256']
            and len(inventory['branches']) == plan['expected_full_branches'] == 323
            and sorted(inventory['cases']) == plan['selected_case_keys'] == report['selected_case_keys']
            and len(inventory['cases']) == plan['expected_selected_cases'] == 4,
            'Complete original inventory differs')
    require(digest(directory/'preserved-audit.json') == plan['preserved_audit_sha256']
            and digest(directory/'preservation-manifest.json') == plan['preservation_manifest_sha256'],
            'Preservation evidence differs')
    preserved = read(directory/'preserved-audit.json')
    reused = read(directory/'reused-report.json')
    require(digest(directory/'reused-report.json') == report['reused_report_sha256']
            and fingerprint(read(directory/'reused-audit.json')) == report['reused_audit_sha256'],
            'Published import provenance differs')
    require(plan['preserved_complete_branch_ids'] == preserved['complete_branch_ids']
            and plan['imported_branch_ids'] == sorted(r['record_id'] for r in reused['branches'])
            and plan['selected_branch_ids'] == select_remaining(inventory,
                preserved['complete_branch_ids'], plan['imported_branch_ids']),
            'Every missing original branch must be selected exactly once')
    require(plan['requests'] == report['requests'] and plan['acceptance'] == report['acceptance'],
            'Numerical settings differ')
    sources = source_hashes()
    sources.update({n: digest(ROOT/n) for n in (*SOURCES, *EXTRA_SOURCES)})
    require(sources == report['implementation_sha256'], 'Numerical implementation differs')
    require({p: version(p) for p in PACKAGES} == report['versions'], 'Numerical package versions differ')
    selected(plan, 0)
    return plan, report, inventory, path, info, grid


def run(args):
    plan, report, inventory, path, info, grid = load_inputs(args.inputs, args.plan_sha256)
    if args.check_only:
        print(json.dumps({'selected_branches': len(plan['selected_branch_ids']),
                          'full_inventory': 323, 'cases': 4, 'partitions': plan['shard_count'],
                          'numerical_implementation_unchanged': True}))
        return 0
    require(args.output is not None and args.index is not None, 'Output and partition are required')
    require(not args.output.exists(), 'Use a new output directory; existing checkpoints must be verified before resume')
    bids = selected(plan, args.index)
    args.output.mkdir(parents=True)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, encoding='utf-8').strip()
    lineage = {'schema_version': 1, 'purpose': __doc__, 'plan_sha256': args.plan_sha256,
        'original_report_sha256': plan['original_report_sha256'], 'partition_index': args.index,
        'selected_branch_ids': bids, 'full_selected_branch_ids': plan['selected_branch_ids'],
        'source_revision': revision, 'wrapper_sha256': digest(Path(__file__)),
        'numerical_implementation_sha256': report['implementation_sha256'], 'versions': report['versions'],
        'platform': platform.platform(), 'machine': platform.machine(), 'python': platform.python_version(),
        'github_run_id': os.environ.get('GITHUB_RUN_ID'), 'github_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
        'github_job': os.environ.get('GITHUB_JOB'), 'case_recovery_claimed': False,
        'full_model_coverage_claimed': False, 'byte_identical_restoration_claimed': False,
        'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'running', 'branches': []}
    destination = args.output/'lineage.json'
    write_json(destination, lineage)
    for bid in bids:
        lineage['active_branch'] = bid
        write_json(destination, lineage)
        row = compute_branch(bid, inventory['branches'][bid], args.output, report, grid, path, info)
        lineage['branches'].append(row)
        write_json(destination, lineage)
        print(json.dumps({'partition': args.index, 'completed': len(lineage['branches']),
                          'required': len(bids), 'branch': row}), flush=True)
    lineage.pop('active_branch', None)
    lineage.update(status='completed', finished_at=datetime.now(timezone.utc).isoformat())
    write_json(destination, lineage)
    return 0 if all(row['status'] == 'confirmed' for row in lineage['branches']) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--index', type=int)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-only', action='store_true')
    sys.exit(run(parser.parse_args()))
