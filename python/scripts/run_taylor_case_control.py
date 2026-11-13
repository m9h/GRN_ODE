"""Compute or resume a full control, or independently audit complete paired cases."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grn_memory.catalog_memory import write_json
from grn_memory.taylor_case_controls import (ORIGINAL_REVISION, audit_cases, make_plan, run_partition)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--model", type=int, required=True)
    plan.add_argument("--case", action="append", required=True)
    plan.add_argument("--source-revision", default=ORIGINAL_REVISION)
    plan.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--partition-index", type=int, required=True)
    run.add_argument("--partition-count", type=int, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--resume", action="store_true")
    run.add_argument("--max-seconds", type=float, default=14400.)
    audit = sub.add_parser("audit")
    audit.add_argument("--plan", type=Path, required=True)
    audit.add_argument("--input", type=Path, action="append", default=[])
    audit.add_argument("--allow-partial", action="store_true")
    audit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "plan":
        result = make_plan(args.model, args.case, args.source_revision)
    elif args.command == "audit":
        result = audit_cases(json.loads(args.plan.read_text()), args.input, allow_partial=args.allow_partial)
    else:
        result = run_partition(json.loads(args.plan.read_text()), args.partition_index, args.partition_count,
                               args.output, resume=args.resume, max_seconds=args.max_seconds)
        print(json.dumps({k: result[k] for k in ("status", "diagnostic_status")}))
        return 0 if result["status"] == "completed" else 75 if result["status"] in ("checkpointed", "budget_exhausted") else 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
