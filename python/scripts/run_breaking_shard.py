"""Run one deterministic partition of complete breaking cases with checkpoints.

The existing catalog worker performs every selected case, including its entire
conditional search. A bounded execution can stop between cases or branches;
retain the output directory, including .evidence, and resume the same selection.
Successful shard validation is explicitly distinct from complete-model coverage.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_shards import select_cases, outcome
from grn_memory.catalog_breaking import candidate_plans
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args):
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError("Timeout must be finite and positive")
    catalog = json.loads((ROOT/"models/catalog.json").read_text())["models"]
    entry = next((e for e in catalog if e["network"] == args.network), None)
    if entry is None:
        raise ValueError("Unknown network number")
    mid = entry["biomodel_id"]
    reference_path = ROOT/"results/catalog-repeated"/(mid+".json")
    reference = json.loads(reference_path.read_text())
    if reference["status"] != "passed":
        raise ValueError("The complete repeated-input reference must pass")
    plans = candidate_plans(reference)
    selected = select_cases(plans, args.shard_index, args.shard_count)
    selection = {"network": args.network, "model_id": mid, "shard_index": args.shard_index,
                 "shard_count": args.shard_count, "candidate_plan_sha256": fingerprint(plans),
                 "reference_file_sha256": digest(reference_path), "case_keys": selected,
                 "expected_model_cases": len(plans), "selected_case_count": len(selected)}
    selection_hash = fingerprint(selection)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output/".shard.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another shard worker is using this output directory") from exc
        destination = args.output/"shard.json"
        if destination.exists():
            previous = json.loads(destination.read_text())
            if not args.resume:
                raise ValueError("Existing shard output requires --resume")
            if previous["selection_sha256"] != selection_hash:
                raise ValueError("Existing output has a different shard selection")
        execute_control = not plans and args.shard_index == 0
        command = [sys.executable, "-m", "grn_memory.catalog_breaking", "--worker", "--network", str(args.network),
                   "--output", str(args.output), "--sample-dt", ".01", "--post-reset-offset", "1e-5"]
        if args.resume:
            command.append("--resume")
        for key in selected:
            command.extend(["--case", key])
        manifest = {"purpose": __doc__, **selection, "selection_sha256": selection_hash,
                    "runner_sha256": digest(Path(__file__)),
                    "partition_source_sha256": digest(ROOT/"grn_memory/breaking_shards.py"),
                    "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    "started_at": datetime.now(timezone.utc).isoformat(), "status": "running",
                    "timeout_seconds": args.timeout, "command": command, "executed_control": execute_control,
                    "resume_requested": args.resume, "model_complete": False}
        write_json(destination, manifest)
        wall_start, started = time.time(), time.monotonic()
        returncode, timed_out, report = None, False, None
        if selected or execute_control:
            print(f"Network {args.network}, shard {args.shard_index}/{args.shard_count}: "
                  f"{len(selected)}/{len(plans)} complete initial cases", flush=True)
            with (args.output/"worker.log").open("w") as log:
                try:
                    process = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                             timeout=args.timeout, check=False)
                    returncode = process.returncode
                except subprocess.TimeoutExpired:
                    # subprocess.run kills and waits for this isolated worker.
                    # Atomic .evidence checkpoints already written are retained.
                    timed_out = True
            report_path = args.output/(mid+".json")
            if report_path.exists() and report_path.stat().st_mtime >= wall_start:
                report = json.loads(report_path.read_text())
                manifest["model_report_sha256"] = digest(report_path)
                manifest["model_fingerprint"] = report["fingerprint"]
        manifest.update(outcome(selected, report, execute_control=execute_control,
                                returncode=returncode, timed_out=timed_out))
        manifest.update(returncode=returncode, timed_out=timed_out, seconds=time.monotonic()-started,
                        finished_at=datetime.now(timezone.utc).isoformat())
        write_json(destination, manifest)
        print(json.dumps({k: manifest[k] for k in ("network", "shard_index", "status",
            "selected_case_count", "selected_cases_passed", "selected_coverage_complete", "model_complete")}), flush=True)
        return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=int, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=18000.)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    result = run(args)
    raise SystemExit(0 if result["status"] in ("selected_cases_passed", "empty_shard") else 1)
