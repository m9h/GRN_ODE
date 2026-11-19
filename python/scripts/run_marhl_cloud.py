"""Select or execute an authenticated task from the complete Marhl cloud plan."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from grn_memory import marhl_cloud as cloud

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('operation', choices=['select', 'compute'])
parser.add_argument('--batch', type=int, required=True)
parser.add_argument('--task', type=int)
parser.add_argument('--task-indices', default='')
parser.add_argument('--resume-run', type=int)
parser.add_argument('--output', type=Path)
parser.add_argument('--plan', type=Path, default=cloud.PLAN)
parser.add_argument('--inventory', type=Path, default=cloud.INVENTORY)
args = parser.parse_args()
plan, _ = cloud.work.check_plan(args.plan, args.inventory)
if args.operation == 'select':
    print('tasks='+json.dumps(cloud.select_tasks(plan, args.batch, args.task_indices, args.resume_run)))
else:
    cloud.require(args.task is not None and args.output is not None, 'Original task index and output required')
    cloud.require(os.environ.get('GITHUB_ACTIONS') == 'true', 'Use the numerical runner for local execution')
    result = cloud.execute(cloud.GitHub(os.environ['GITHUB_REPOSITORY']), int(os.environ['GITHUB_RUN_ID']),
                           int(os.environ['GITHUB_RUN_ATTEMPT']), os.environ['GITHUB_SHA'],
                           args.batch, args.task, args.output, parent_run=args.resume_run,
                           plan_path=args.plan, inventory_path=args.inventory)
    print(json.dumps(result, indent=2))
    if result['status'] != 'completed':
        sys.exit(2)
