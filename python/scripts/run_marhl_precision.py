"""Prepare, check or execute the complete fixed Marhl precision task inventory."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from grn_memory import marhl_precision as work

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('operation', choices=['prepare', 'check', 'batch', 'run', 'audit'])
parser.add_argument('--inventory', type=Path, default=ROOT/'results/catalog-breaking-marhl-full-controls-20261118/inventory.json')
parser.add_argument('--plan', type=Path, required=True)
parser.add_argument('--task', type=int)
parser.add_argument('--batch', type=int)
parser.add_argument('--branch')
parser.add_argument('--directory', type=Path, action='append')
parser.add_argument('--output', type=Path)
parser.add_argument('--resume', action='store_true')
parser.add_argument('--max-seconds', type=float, default=14400.)
args = parser.parse_args()
if args.operation == 'prepare':
    work.require(not args.plan.exists(), 'Use a new plan path')
    from scripts.prepare_marhl_full_controls import check
    check(args.inventory)
    work.write_json(args.plan, work.make_plan(args.inventory))
if args.operation in ('prepare', 'check', 'batch'):
    plan, _ = work.check_plan(args.plan, args.inventory, rebuild_inventory=True)
    if args.operation == 'batch':
        work.require(args.batch is not None and 0 <= args.batch < len(plan['batches']), 'Select a declared batch')
        result = plan['batches'][args.batch]
    else:
        result = {k: plan[k] for k in ['model_id', 'selected_cases', 'task_count', 'diagnostic_priority_tasks', 'remaining_required_tasks']}
        result['plan_file_sha256'] = work.digest(args.plan)
elif args.operation == 'run':
    work.require(args.task is not None and args.output is not None, 'Task index and output directory required')
    report = work.run_task(args.plan, args.inventory, args.task, args.output, resume=args.resume, max_seconds=args.max_seconds)
    result = {'task': args.task, 'status': report['status'], 'report_sha256': work.digest(args.output/'report.json')}
else:
    work.require(args.branch and args.directory and args.output, 'Branch, four directories and audit output required')
    result = work.audit_branch(args.plan, args.inventory, args.branch, args.directory)
    work.write_json(args.output, result)
    result = {k: result[k] for k in ['branch_id', 'status', 'verified_arrays', 'samples', 'full_grid_compared']}
print(json.dumps(result, indent=2))
if args.operation == 'run' and result['status'] != 'completed':
    sys.exit(2)
