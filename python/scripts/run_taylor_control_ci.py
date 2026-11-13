"""Run a declared control with a verifiable, resumable GitHub artifact."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from grn_memory.catalog_memory import write_json
from grn_memory.taylor_case_controls import problem, run_partition, verify_committed_sources
from grn_memory.taylor_checkpoints import signature
from grn_memory.taylor_control_resume import WORKFLOW, restore
from grn_memory.taylor_partition_resume import GitHub
from grn_memory.taylor_partitions import digest, now, require, source_provenance


def execute(args, github=None):
    plan = json.loads(args.plan.read_text())
    _, _, _, core, _ = problem(plan, args.partition_index, args.partition_count)
    output = args.output
    require(not output.exists(), "Each CI attempt needs a fresh artifact directory")
    output.mkdir(parents=True)
    record = {"schema": 1, "scope": "paired-case-controls", "run_id": int(os.environ["GITHUB_RUN_ID"]),
              "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]), "head_sha": os.environ["GITHUB_SHA"],
              "model": int(plan["model_id"].removeprefix("BIOMD")), "partition_index": args.partition_index,
              "partition_count": args.partition_count, "evidence_directory": "evidence",
              "case_plan_sha256": signature(plan), "plan_file_sha256": digest(args.plan),
              "implementation_sha256": core["implementation_sha256"], "parent_run_id": args.resume_run,
              "started_at": now(), "status": "preparing", "max_seconds": args.max_seconds,
              "orchestrator_sha256": digest(Path(__file__)), "workflow_sha256": digest(ROOT.parent/WORKFLOW)}
    write_json(output/"execution.json", record)
    try:
        record["source_provenance"] = source_provenance()
        require(record["source_provenance"] == {"source_revision": record["head_sha"],
                "implementation_files_differing_from_revision": []}, "CI sources differ from dispatched commit")
        verify_committed_sources(record["head_sha"], tuple(sorted(core["implementation_sha256"].items())))
        if args.resume_run is not None:
            github = github or GitHub(os.environ["GITHUB_REPOSITORY"])
            record["restoration"] = restore(github, args.resume_run, plan, args.partition_index,
                                            args.partition_count, output/"evidence")
        record["status"] = "running"
        write_json(output/"execution.json", record)
        report = run_partition(plan, args.partition_index, args.partition_count, output/"evidence",
                               resume=args.resume_run is not None, max_seconds=args.max_seconds)
        record.update(status=report["status"], diagnostic_status=report["diagnostic_status"],
                      report_sha256=digest(output/"evidence/report.json"))
    except Exception as error:
        record.update(status="execution_error", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        record["finished_at"] = now()
        write_json(output/"execution.json", record)
    return 0 if record["status"] == "completed" else 75 if record["status"] in ("checkpointed", "budget_exhausted") else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--partition-index", type=int, required=True)
    parser.add_argument("--partition-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume-run", type=int)
    parser.add_argument("--max-seconds", type=float, default=14400.)
    raise SystemExit(execute(parser.parse_args()))
