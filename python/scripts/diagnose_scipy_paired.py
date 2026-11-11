"""Audit failed paired branches with SciPy/JAX equations and native refinement.

Two SciPy requests and two tighter RoadRunner requests must agree. The original
RoadRunner request is rerun and reported separately; its known inaccuracies are
not silently promoted into the reference. All original samples and observables
remain in every comparison. This is branch evidence, not a case-score recovery.
"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_jax import source_hashes
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_paired import WINDOWS
from grn_memory.catalog_repeated import summarize
from grn_memory.catalog_validation import PACKAGES, comparison
from grn_memory.jax_protocols import supported_model
from grn_memory.native_protocols import ResetTrain, protocol_trajectory, sample_times
from grn_memory.scipy_reference import scipy_protocol_trajectory


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnose(args):
    mid = f"BIOMD{args.model:010d}"
    path = ROOT/"models"/(mid+".xml")
    info = supported_model(path)
    source = args.input/(mid+".json")
    original = json.loads(source.read_text())
    if original["model_sha256"] != info["sha256"]:
        raise ValueError("Original report and current SBML hashes differ")
    archive = source.parent/original["branch_archive"]["file"]
    if digest(archive) != original["branch_archive"]["sha256"]:
        raise ValueError("Original branch archive hash differs")
    with gzip.open(archive, "rt") as stream:
        inventory = {b["branch_id"]: b for line in stream if (b := json.loads(line))}
    if args.branch and set(args.branch)-inventory.keys():
        raise ValueError("Unknown selected branch")
    selected = ({key: inventory[key] for key in sorted(set(args.branch))} if args.branch else
                {key: b for key, b in sorted(inventory.items()) if not b["passed"]})
    config = original["configuration"]
    if config["windows"] != {k: list(v) for k, v in WINDOWS.items()}:
        raise ValueError("Unexpected original paired-screen windows")
    grid = sample_times(300., config["dt"], [ResetTrain(t,t+50.,{}) for t in (50.,150.,200.)],
                        post_reset_offset=config["post_reset_offset"])
    requests = {"scipy": {"rtol": args.rtol, "atol": args.atol},
        "scipy_refined": {"rtol": args.rtol/10, "atol": args.atol/10},
        "roadrunner_original": config["integration_settings"]["roadrunner"],
        "roadrunner": {"rtol": args.reference_rtol, "atol": args.reference_atol},
        "roadrunner_refined": {"rtol": args.reference_rtol/2, "atol": args.reference_atol/2}}
    sources = source_hashes()
    sources.update({"grn_memory/"+name: digest(ROOT/"grn_memory"/name) for name in
                    ("scipy_reference.py", "jax_protocols.py", "catalog_repeated.py", "catalog_paired.py")})
    metadata = {"model_id": mid, "model_sha256": info["sha256"], "scipy_method": args.method,
        "source_report_sha256": digest(source), "source_fingerprint": original["fingerprint"],
        "source_archive_sha256": digest(archive), "script_sha256": digest(Path(__file__)),
        "implementation_sha256": sources, "integration_requests": requests,
        "comparison_settings": {"rtol": config["comparison_rtol"], "atol": config["comparison_atol"]},
        "grid": {"duration": 300., "dt": config["dt"], "post_reset_offset": config["post_reset_offset"],
                 "samples": len(grid)},
        "versions": {p: version(p) for p in (*PACKAGES, "scipy", "jax", "jaxlib", "diffrax", "equinox", "jaxkineticmodel")}}
    fingerprint = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"purpose": __doc__, **metadata, "fingerprint": fingerprint,
        "selection": "explicit branches" if args.branch else "all originally failed branches",
        "original_branch_count": len(inventory), "selected_branch_ids": list(selected),
        "expected_branches": len(selected), "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running", "branches": []}
    write_json(args.output/"report.json", report)
    for bid, branch in selected.items():
        destination = args.output/(bid+".json")
        if args.resume and destination.exists():
            saved = json.loads(destination.read_text())
            if saved.get("fingerprint") == fingerprint and saved.get("status") != "running":
                report["branches"].append({"branch_id": bid, "status": saved["status"], "file": destination.name})
                continue
        started = time.monotonic()
        result = {"branch_id": bid, "fingerprint": fingerprint, "status": "running",
            "specification": branch["specification"], "reset_trains": branch["reset_trains"],
            "original_outcome": {k: branch[k] for k in ("passed", "error", "comparison", "solver_attempts") if k in branch},
            "integrations": {}, "comparisons": {}, "original_reference_comparisons": {}, "windows": {}}
        trains = [ResetTrain(**t) for t in branch["reset_trains"]]
        trajectories = {}
        for label, request in requests.items():
            evidence = {"request": request, "completed": False}
            result["integrations"][label] = evidence
            began = time.monotonic()

            def progress(row):
                if row["completed_segments"] % 100 == 0:
                    row["seconds_so_far"] = time.monotonic()-began
                    write_json(destination, result)
                    print(bid[:12], label, row["completed_segments"], row["last_interval"], flush=True)

            try:
                if label.startswith("scipy"):
                    trace = scipy_protocol_trajectory(path, grid, trains, method=args.method,
                                                       **request, evidence=evidence, progress=progress)
                else:
                    trace = protocol_trajectory(path, grid, trains, "roadrunner", **request)
                trajectories[label] = trace
                evidence.update(completed=True, samples=len(trace), observables=len(trace.columns)-1)
                result["windows"][label] = summarize(trace, WINDOWS)
            except Exception as exc:
                evidence.update(completed=False, error=f"{type(exc).__name__}: {exc}")
            evidence["seconds"] = time.monotonic()-began
            write_json(destination, result)
        pairs = [("scipy", "roadrunner"), ("scipy_refined", "roadrunner"),
                 ("scipy", "scipy_refined"), ("roadrunner", "roadrunner_refined"),
                 ("scipy_refined", "roadrunner_refined")]
        for a,b in pairs:
            if a in trajectories and b in trajectories:
                result["comparisons"][a+"_vs_"+b] = comparison(trajectories[a], trajectories[b], **metadata["comparison_settings"])
        if "roadrunner_original" in trajectories:
            for other in ("roadrunner", "scipy_refined"):
                if other in trajectories:
                    result["original_reference_comparisons"][other] = comparison(
                        trajectories["roadrunner_original"], trajectories[other], **metadata["comparison_settings"])
        required = ("scipy", "scipy_refined", "roadrunner", "roadrunner_refined")
        result["status"] = ("failed" if any(k not in trajectories for k in required) else
            "confirmed" if all(c["passed"] for c in result["comparisons"].values()) else "mismatch")
        result["seconds"] = time.monotonic()-started
        write_json(destination, result)
        report["branches"].append({"branch_id": bid, "status": result["status"], "file": destination.name})
        write_json(args.output/"report.json", report)
        print(f"{len(report['branches'])}/{len(selected)} {bid[:12]} {result['status']} "
              f"{result['seconds']:.2f}s", flush=True)
    report.update(status="completed", evaluated_branches=len(report["branches"]),
        confirmed_branches=sum(b["status"] == "confirmed" for b in report["branches"]),
        finished_at=datetime.now(timezone.utc).isoformat())
    write_json(args.output/"report.json", report)
    print("RESULT", report["confirmed_branches"], "/", report["expected_branches"], "confirmed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=int, required=True, help="BioModels identifier, not catalog network number")
    parser.add_argument("--branch", action="append", help="Select branch IDs; default diagnoses all original failures")
    parser.add_argument("--input", type=Path, default=ROOT/"results/catalog-paired")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--method", choices=("Radau", "BDF"), default="Radau")
    parser.add_argument("--rtol", type=float, default=1e-10)
    parser.add_argument("--atol", type=float, default=1e-12)
    parser.add_argument("--reference-rtol", type=float, default=1e-13)
    parser.add_argument("--reference-atol", type=float, default=1e-15)
    parser.add_argument("--resume", action="store_true")
    diagnose(parser.parse_args())
