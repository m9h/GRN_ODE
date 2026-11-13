"""Run or resume a precision partition with an independently identifiable artifact."""

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_memory import write_json
from grn_memory.taylor_partitions import digest, now, require, run_partition, source_provenance
from grn_memory.taylor_partition_resume import GitHub, restore


def execute(args, github=None):
    output = args.output
    require(not output.exists(), "Each CI attempt needs a fresh artifact directory")
    output.mkdir(parents=True)
    record = {"schema": 1, "run_id": int(os.environ["GITHUB_RUN_ID"]),
              "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]), "head_sha": os.environ["GITHUB_SHA"],
              "model": args.model, "partition_index": args.partition_index, "partition_count": args.partition_count,
              "evidence_directory": "evidence", "parent_run_id": args.resume_run, "started_at": now(),
              "status": "preparing", "max_seconds": args.max_seconds,
              "orchestrator_sha256": digest(Path(__file__)),
              "workflow_sha256": digest(ROOT.parent / ".github/workflows/precision-checkpoints.yml")}
    write_json(output / "execution.json", record)
    try:
        record["source_provenance"] = source_provenance()
        require(record["source_provenance"]["source_revision"] == record["head_sha"]
                and not record["source_provenance"]["implementation_files_differing_from_revision"],
                "CI numerical sources must match the dispatched commit")
        if args.resume_run is not None:
            github = github or GitHub(os.environ["GITHUB_REPOSITORY"])
            record["restoration"] = restore(github, args.resume_run, args.model, args.partition_index,
                                            args.partition_count, output / "evidence")
        record["status"] = "running"
        write_json(output / "execution.json", record)
        report = run_partition(args.model, args.partition_index, args.partition_count, output / "evidence",
                               resume=args.resume_run is not None, max_seconds=args.max_seconds)
        record.update(status=report["status"], diagnostic_status=report["diagnostic_status"],
                      report_sha256=digest(output / "evidence/report.json"))
    except Exception as error:
        record.update(status="execution_error", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        record["finished_at"] = now()
        write_json(output / "execution.json", record)
    return 0 if record["status"] == "completed" else 75 if record["status"] in ("checkpointed", "budget_exhausted") else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=int, choices=(35, 39), required=True)
    parser.add_argument("--partition-index", type=int, required=True)
    parser.add_argument("--partition-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume-run", type=int)
    parser.add_argument("--max-seconds", type=float, default=14400.)
    raise SystemExit(execute(parser.parse_args()))
