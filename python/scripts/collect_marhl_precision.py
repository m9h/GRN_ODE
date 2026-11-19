"""Bind, collect and audit the complete fixed Marhl precision computation."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from grn_memory import marhl_collection as collection, marhl_cases as cases
from grn_memory.marhl_precision import read, require, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['bind', 'rebind', 'collect', 'audit', 'check'])
    parser.add_argument('--batches', type=Path)
    parser.add_argument('--selection', type=Path)
    parser.add_argument('--snapshots', type=Path)
    parser.add_argument('--archives', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--run-id', type=int)
    parser.add_argument('--attempt', type=int, default=1)
    parser.add_argument('--indices')
    args = parser.parse_args()
    if args.operation == 'check':
        plan, inventory, *_ = cases.original_context()
        print(json.dumps({'tasks': plan['task_count'], 'branches': len(plan['branches']),
                          'cases': len(inventory['cases']), 'numerical_integrations_performed': 0}))
        return
    require(args.snapshots is not None and args.output is not None, 'Snapshots and output are required')
    if args.operation in ('bind', 'rebind'):
        require(not args.output.exists() and not args.output.is_symlink(), 'Use a new selection path')
        if args.operation == 'bind':
            require(args.batches is not None, 'All six batch declarations are required')
            result = collection.bind(read(args.batches), args.snapshots)
        else:
            require(args.selection is not None and args.run_id is not None and args.indices is not None,
                    'Previous selection, exact continuation run and task indices are required')
            result = collection.rebind(read(args.selection), args.run_id, args.attempt, json.loads(args.indices), args.snapshots)
        write_json(args.output, result)
        print(json.dumps({'tasks': len(result['selected']), 'selection': str(args.output)}))
        return
    require(args.selection is not None and args.archives is not None, 'Fixed selection and original ZIPs are required')
    fn = collection.collect if args.operation == 'collect' else cases.audit
    result = fn(args.selection, args.snapshots, args.archives, args.output)
    keys = ('complete_arrays', 'complete_branches', 'all_required_arrays_verified', 'all_required_branches_agree')
    if args.operation == 'audit':
        keys = ('selected_cases_passed', 'complete_selected_array_coverage', 'selected_case_validation_passed')
    print(json.dumps({key: result[key] for key in keys}))


if __name__ == '__main__':
    main()
