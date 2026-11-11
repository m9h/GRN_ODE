"""Probe full failed paired branches with two arithmetic precisions.

Precision convergence and agreement with a native simulator are separate gates.
This diagnostic does not recover complete cases or validate uncomputed controls.
"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import heyoka as hy

from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison, inspect_model
from grn_memory.native_protocols import ResetTrain, protocol_trajectory, sample_times
from grn_memory.taylor_reference import taylor_trajectory


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnose(args):
    mid = f"BIOMD{args.model:010d}"
    path = ROOT/"models"/(mid+".xml")
    source = ROOT/"results/catalog-paired"/(mid+".json")
    original = json.loads(source.read_text())
    info = inspect_model(path)
    if info["sha256"] != original["model_sha256"]:
        raise ValueError("Original model source differs")
    archive = source.parent/original["branch_archive"]["file"]
    if digest(archive) != original["branch_archive"]["sha256"]:
        raise ValueError("Original branch archive differs")
    with gzip.open(archive, "rt") as stream:
        branches = {b["branch_id"]: b for line in stream if (b := json.loads(line)) and not b["passed"]}
    config = original["configuration"]
    if config["dt"] != .01 or config["post_reset_offset"] != 1e-5:
        raise ValueError("Unexpected original observation grid")
    grid = sample_times(300., .01, [ResetTrain(t, t+50., {}) for t in (50., 150., 200.)], post_reset_offset=1e-5)
    requests = {"taylor128": {"precision": 128, "tolerance": "1e-30"},
                "taylor192": {"precision": 192, "tolerance": "1e-45"}}
    native = {"rtol": 1e-13, "atol": 1e-15}
    acceptance = {"rtol": config["comparison_rtol"], "atol": config["comparison_atol"]}
    if acceptance != {"rtol": 2e-5, "atol": 1e-7}:
        raise ValueError("Original acceptance thresholds differ")
    metadata = {"model_id": mid, "model_sha256": info["sha256"], "source_report_sha256": digest(source),
        "source_archive_sha256": digest(archive), "source_fingerprint": original["fingerprint"],
        "requests": requests, "native_request": native, "acceptance": acceptance,
        "sample_grid_sha256": hashlib.sha256(grid.tobytes()).hexdigest(), "samples": len(grid),
        "versions": {"heyoka": hy.__version__, **{p: version(p) for p in ("numpy", "python-libsbml", "libroadrunner", "pandas")}},
        "python": platform.python_version(), "platform": platform.platform(),
        "implementation_sha256": {name: digest(ROOT/name) for name in (
            "grn_memory/taylor_reference.py", "grn_memory/native_protocols.py", "grn_memory/catalog_validation.py",
            "scripts/diagnose_taylor_paired.py")}}
    signature = fingerprint(metadata)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"purpose": __doc__, **metadata, "fingerprint": signature,
              "status": "running", "expected_branches": len(branches), "branches": [],
              "started_at": datetime.now(timezone.utc).isoformat()}
    write_json(args.output/"report.json", report)
    selections = [("untreated_baseline", [], grid[grid <= 50.])]
    selections.extend((bid, b["reset_trains"], grid) for bid, b in sorted(branches.items()))
    for bid, trains, times in selections:
        destination = args.output/(bid+".json")
        if args.resume and destination.exists():
            saved = json.loads(destination.read_text())
            if saved.get("fingerprint") == signature and saved.get("status") != "running":
                if bid == "untreated_baseline":
                    report["baseline"] = {"file": destination.name, "status": saved["status"]}
                else:
                    report["branches"].append({"branch_id": bid, "file": destination.name, "status": saved["status"]})
                continue
        result = {"fingerprint": signature, "branch_id": bid, "reset_trains": trains,
                  "status": "running", "integrations": {}, "comparisons": {}, "traces": {}}
        traces = {}
        for label, request in (*requests.items(), ("roadrunner", native)):
            started = time.monotonic()
            evidence = {"completed": False}
            result["integrations"][label] = evidence
            def progress(row):
                if row["completed_segments"] % 100 == 0:
                    write_json(destination, result)
                    print(bid[:12], label, row["completed_segments"], row["last_interval"], flush=True)
            try:
                if label == "roadrunner":
                    trace = protocol_trajectory(path, times, [ResetTrain(**t) for t in trains], label, **request)
                    names, values = list(trace.columns[1:]), trace.iloc[:, 1:].to_numpy()
                    evidence.update(completed=True, sample_count=len(times), observables=names)
                else:
                    names, values = taylor_trajectory(path, times, trains, **request, evidence=evidence, progress=progress)
                    trace = pd.DataFrame(values, columns=names)
                    trace.insert(0, "time", times)
                if names != info["observables"] or values.shape != (len(times), len(names)):
                    raise ValueError("Observation inventory differs")
                traces[label] = trace
                output = args.output/(bid+"-"+label+".npz")
                np.savez_compressed(output, times=times, values=values, observables=np.asarray(names))
                result["traces"][label] = {"file": output.name, "sha256": digest(output)}
            except Exception as error:
                evidence.update(completed=False, error=f"{type(error).__name__}: {error}")
            evidence["seconds"] = time.monotonic()-started
            write_json(destination, result)
        for a, b in (("taylor128", "taylor192"), ("taylor128", "roadrunner"), ("taylor192", "roadrunner")):
            if a in traces and b in traces:
                result["comparisons"][a+"_vs_"+b] = comparison(traces[a], traces[b], **acceptance)
        result["precision_converged"] = result["comparisons"].get("taylor128_vs_taylor192", {}).get("passed", False)
        result["native_agreement"] = len(result["comparisons"]) == 3 and all(
            c["passed"] for name, c in result["comparisons"].items() if name.endswith("_vs_roadrunner"))
        result["status"] = ("incomplete" if len(traces) != 3 else "confirmed" if
            result["precision_converged"] and result["native_agreement"] else
            "precision_converged_native_mismatch" if result["precision_converged"] else "precision_unresolved")
        write_json(destination, result)
        if bid == "untreated_baseline":
            report["baseline"] = {"file": destination.name, "status": result["status"]}
        else:
            report["branches"].append({"branch_id": bid, "file": destination.name, "status": result["status"]})
        write_json(args.output/"report.json", report)
        print(bid[:12], result["status"], flush=True)
    report.update(status="completed", finished_at=datetime.now(timezone.utc).isoformat())
    write_json(args.output/"report.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=int, default=39)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    diagnose(parser.parse_args())
