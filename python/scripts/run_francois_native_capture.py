"""Validate, run or independently audit one frozen François native branch."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from grn_memory import francois_native_capture as work

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate',action='store_true')
    parser.add_argument('--validate-runtime',action='store_true')
    parser.add_argument('--index',type=int)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--audit',type=Path)
    args=parser.parse_args()
    if args.validate:
        plan,*_=work.context()
        if args.validate_runtime:work.validate_runtime(work.runtime(),plan)
        print(json.dumps({'full_original_cases':118,'selected_trials':6,'required_branches':41,'required_native_integrations':82,'plan_sha256':work.PLAN_SHA,'numerical_integrations_performed':0}))
    elif args.index is None or args.output is None:
        parser.error('--index and --output are required for computation or audit')
    elif args.audit:
        result=work.audit_result(args.audit,args.index)
        if args.output.exists():raise ValueError('Do not overwrite an earlier audit')
        work.write(args.output,result)
        print(json.dumps({k:v for k,v in result.items() if k not in ('windows','partial_windows')}))
    else:
        work.run_branch(args.index,args.output)
