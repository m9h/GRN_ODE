"""Compute one immutable partition of every original failed case's controls.

Completed full arrays are checkpoints. No branch-only pilot is substituted for
the complete case inventory. Only the separate all-partition auditor can
evaluate case recovery.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shutil
import sys
import time
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_memory import write_json
from grn_memory.scipy_case_partitions import (SOURCE_FILES, load_experiment, metadata, validate_metadata,
                                             verify_repository_sources, validate_cached_branches)
from scripts.diagnose_scipy_breaking_controls import TimeBudgetReached, compute_branch


def run(args):
    require(0 < args.budget_seconds <= 86400, "Use a finite positive integration budget of at most one day")
    deadline = time.monotonic() + args.budget_seconds
    plan, inventory, path, info, grid = load_experiment(args.inputs)
    meta = metadata(args.inputs / "execution-plan.json", plan, inventory, grid, args.shard_index)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8").strip()
    verify_repository_sources(revision, meta["experiment"]["implementation_sha256"])
    destination = args.output / "report.json"
    if destination.exists():
        require(args.resume, "Existing output requires --resume")
        report = json.loads(destination.read_text())
        validate_metadata(report["metadata"], args.inputs / "execution-plan.json", plan, inventory, grid,
                          live_environment=True)
        require(report["metadata"] == meta, "Resume partition differs")
        validate_cached_branches(args.output, report, inventory, grid, info)
        report.setdefault("resumed_at", []).append(datetime.now(timezone.utc).isoformat())
    else:
        require(not any(args.output.iterdir()), "Fresh output must be empty")
        report = {"purpose": __doc__, "metadata": meta, "branches": [], "status": "running",
                  "started_at": datetime.now(timezone.utc).isoformat(),
                  "case_recovery_claimed": False, "full_model_coverage_claimed": False}
    for name in (*SOURCE_FILES, "execution-plan.json"):
        target = args.output / name
        if target.resolve() != (args.inputs / name).resolve():
            shutil.copyfile(args.inputs / name, target)
    write_json(args.output / "inventory.json", inventory)
    report.setdefault("executions", []).append({"producer_revision": revision,
                                                "started_at": datetime.now(timezone.utc).isoformat()})
    report["producer_revision"] = revision
    report.update(status="running", complete_selected_inventory=False)
    report.pop("finished_at", None)
    write_json(destination, report)
    completed = {b["record_id"]: b for b in report["branches"]}
    require(set(completed) <= set(meta["selected_branch_ids"]), "Unexpected cached branch")
    branch_meta = {**meta["experiment"], "fingerprint": meta["fingerprint"]}
    for bid in meta["selected_branch_ids"]:
        report["active_branch"] = bid
        write_json(destination, report)
        try:
            row = compute_branch(bid, inventory["branches"][bid], args.output, branch_meta, grid, path, info,
                                 resume=args.resume, deadline=deadline)
        except TimeBudgetReached:
            report.update(status="checkpointed", next_branch=bid,
                          checkpointed_at=datetime.now(timezone.utc).isoformat())
            write_json(destination, report)
            return report
        completed[bid] = row
        report["branches"] = [completed[k] for k in meta["selected_branch_ids"] if k in completed]
        write_json(destination, report)
        print(json.dumps({"partition": args.shard_index, "saved": len(completed),
                          "required": len(meta["selected_branch_ids"]), "branch": bid, "status": row["status"]}), flush=True)
    report.pop("next_branch", None)
    report.pop("active_branch", None)
    report.update(status="completed", complete_selected_inventory=True,
                  confirmed_branches=sum(b["status"] == "confirmed" for b in report["branches"]),
                  finished_at=datetime.now(timezone.utc).isoformat())
    write_json(destination, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--shard-index", required=True, type=int)
    parser.add_argument("--budget-seconds", type=float, default=16800.)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # Keep the lock outside the evidence directory so a fresh directory is empty.
    with args.output.with_name(args.output.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = run(args)
    sys.exit(0 if report["status"] == "completed" else 75)
