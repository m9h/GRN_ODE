"""Validate, run or bind the full sixteen-task missing-output recovery."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from grn_memory import marhl_missing_output as recovery
from grn_memory.marhl_precision import read, require, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['check', 'select', 'compute', 'bind'])
    parser.add_argument('--task', type=int)
    parser.add_argument('--task-indices', default='')
    parser.add_argument('--resume-run', type=int)
    parser.add_argument('--run-id', type=int)
    parser.add_argument('--attempt', type=int, default=1)
    parser.add_argument('--revision')
    parser.add_argument('--selection', type=Path)
    parser.add_argument('--snapshots', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.operation == 'check':
        ctx = recovery.context()
        print(json.dumps({'full_tasks': ctx['plan']['task_count'], 'recovery_tasks': sorted(ctx['rows']),
                          'numerical_integrations_performed': 0}))
    elif args.operation == 'select':
        print('tasks='+json.dumps(recovery.select_tasks(args.task_indices, args.resume_run)))
    elif args.operation == 'compute':
        require(args.task is not None and args.output is not None, 'Task and output required')
        result = recovery.execute(recovery.cloud.GitHub('m9h/GRN_ODE'), int(os.environ['GITHUB_RUN_ID']),
                  int(os.environ['GITHUB_RUN_ATTEMPT']), os.environ['GITHUB_SHA'], args.task, args.output, args.resume_run)
        print(json.dumps(result))
        return 0 if result['status'] == 'completed' else 2
    else:
        require(args.selection is not None and args.snapshots is not None and args.output is not None
                and args.run_id is not None and args.revision is not None, 'Full selection and exact recovery run required')
        require(not args.output.exists(), 'Never overwrite a fixed task selection')
        indices = recovery.select_tasks(args.task_indices, args.resume_run)
        result = recovery.rebind(read(args.selection), args.run_id, args.attempt, indices, args.snapshots,
                                 args.revision, args.resume_run)
        write_json(args.output, result)
        print(json.dumps({'full_tasks': len(result['selected']), 'recovery_tasks': indices}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
