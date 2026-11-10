"""Shared process isolation and provenance for later catalog protocol stages."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .catalog_memory import write_json
from .catalog_validation import ROOT, inspect_model
from .native_protocols import intervention_targets, protocol_trajectory


def context(entry):
    """Use the checked single-input catalog as the protocol/reference inventory."""
    path = ROOT/"models"/f'{entry["biomodel_id"]}.xml'
    reference_path = ROOT/"results/catalog-memory"/f'{entry["biomodel_id"]}.json'
    reference = json.loads(reference_path.read_text())
    info = inspect_model(path)
    if reference["status"] != "passed" or reference["model_sha256"] != info["sha256"]:
        raise ValueError("A validated single-input reference with matching model hash is required")
    targets, excluded = intervention_targets(path)
    if list(targets) != list(reference["targets"]):
        raise ValueError("Independent state inventory differs from the checked reference")
    if info["delay_expressions"]:
        from .delay_protocols import delay_protocol_trajectory as trajectory
    else:
        trajectory = protocol_trajectory
    return path, reference, targets, excluded, trajectory


def implementation_hashes(names):
    return {name: hashlib.sha256((ROOT/"grn_memory"/name).read_bytes()).hexdigest() for name in names}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def run_catalog(module, worker, description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--output", type=Path, default=ROOT/"results"/module.replace("_", "-"))
    parser.add_argument("--network", action="append", type=int)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=14400)
    parser.add_argument("--limit-cases", type=int)
    parser.add_argument("--sample-dt", type=float, default=.01,
                        help="Output sampling interval; changing it invalidates cached results")
    parser.add_argument("--post-reset-offset", type=float, default=1e-5,
                        help="Actual time offset for samples coincident with resets")
    parser.add_argument("--case", action="append", help="Select case keys for diagnosis; selection is not full coverage")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.workers < 1 or args.timeout <= 0 or (args.limit_cases is not None and args.limit_cases < 1):
        parser.error("Counts and timeout must be positive")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((ROOT/"models/catalog.json").read_text())["models"]
    if args.network:
        if set(args.network)-{entry["network"] for entry in catalog}:
            parser.error("Unknown catalog network")
        catalog = [entry for entry in catalog if entry["network"] in args.network]
    if args.worker:
        if len(catalog) != 1:
            parser.error("Worker requires exactly one network")
        result = worker(catalog[0], args)
        raise SystemExit(0 if result["status"] == "passed" else 1)

    def isolated(entry):
        command = [sys.executable, "-m", "grn_memory."+module, "--worker", "--network", str(entry["network"]),
                   "--output", str(args.output), "--sample-dt", str(args.sample_dt),
                   "--post-reset-offset", str(args.post_reset_offset)]
        if args.resume:
            command.append("--resume")
        if args.limit_cases:
            command.extend(["--limit-cases", str(args.limit_cases)])
        for case in args.case or []:
            command.extend(["--case", case])
        env = dict(os.environ)
        env.setdefault("MPLCONFIGDIR", str(args.output/".mpl-cache"))
        with (args.output/f'{entry["biomodel_id"]}.log').open("w") as stream:
            try:
                result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, env=env, timeout=args.timeout)
                execution = {"returncode": result.returncode}
            except subprocess.TimeoutExpired:
                execution = {"timeout": args.timeout}
        destination = args.output/f'{entry["biomodel_id"]}.json'
        record = json.loads(destination.read_text()) if destination.exists() else {**entry, "status": "failed"}
        if execution.get("returncode") != 0:
            record["status"] = "incomplete_or_failed"
        record["worker"] = execution
        write_json(destination, record)
        return record

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(isolated, entry) for entry in catalog]):
            result = future.result()
            results.append(result)
            print(f'{result["network"]:02d} {result["status"]}: {result.get("passed_cases",0)}/{result.get("expected_cases",0)}', flush=True)
    # Detailed per-model files retain every branch. Duplicating them here made
    # the aggregate exceed GitHub's 100 MB file limit for the repeated screen.
    fields = ("network", "biomodel_id", "name", "status", "expected_cases", "evaluated_cases",
              "passed_cases", "fingerprint", "control_comparison", "worker")
    models = [{**{k: r[k] for k in fields if k in r}, "report_file": r["biomodel_id"]+".json"}
              for r in sorted(results, key=lambda r:r["network"])]
    summary = {"scope": description, "model_count": len(results),
               "passed_models": sum(r["status"] == "passed" for r in results),
               "expected_cases": sum(r.get("expected_cases", 0) for r in results),
               "passed_cases": sum(r.get("passed_cases", 0) for r in results), "models": models}
    write_json(args.output/"report.json", summary)
    if summary["passed_models"] != summary["model_count"]:
        raise SystemExit(1)
