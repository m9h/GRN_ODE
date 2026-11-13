"""Compute one complete failed paired branch with resumable Taylor integrations."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grn_memory.taylor_partitions import run_partition


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=int, required=True, help="BioModels number, not catalog network number")
    parser.add_argument("--partition-index", type=int, required=True)
    parser.add_argument("--partition-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-seconds", type=float, default=14400., help="Cooperative wall budget at protocol boundaries")
    args = parser.parse_args()
    report = run_partition(args.model, args.partition_index, args.partition_count, args.output,
                           resume=args.resume, max_seconds=args.max_seconds)
    # Partial artifacts are retained; the dispatcher must explicitly resume them.
    sys.exit(0 if report["status"] == "completed" else 75 if report["status"] in ("checkpointed", "budget_exhausted") else 1)
