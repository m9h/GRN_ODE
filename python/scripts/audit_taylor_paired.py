"""Recompute Taylor diagnostic comparisons from all saved trajectory samples."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from grn_memory.breaking_audit import require
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison, inspect_model
from grn_memory.native_protocols import ResetTrain, sample_times


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(directory):
    report_path = directory/"report.json"
    report = json.loads(report_path.read_text())
    require(report["status"] == "completed", "Diagnostic is still running")
    keys = ("model_id", "model_sha256", "source_report_sha256", "source_archive_sha256",
            "source_fingerprint", "requests", "native_request", "acceptance", "sample_grid_sha256",
            "samples", "versions", "python", "platform", "implementation_sha256")
    require(fingerprint({k: report[k] for k in keys}) == report["fingerprint"], "Diagnostic fingerprint differs")
    source = ROOT/"results/catalog-paired"/(report["model_id"]+".json")
    original = json.loads(source.read_text())
    info = inspect_model(ROOT/"models"/(report["model_id"]+".xml"))
    require(report["model_sha256"] == info["sha256"] == original["model_sha256"], "Model source differs")
    archive = source.parent/original["branch_archive"]["file"]
    require(digest(source) == report["source_report_sha256"] and digest(archive) == report["source_archive_sha256"],
            "Original evidence differs")
    require(original["fingerprint"] == report["source_fingerprint"], "Original fingerprint differs")
    for name, sha in report["implementation_sha256"].items():
        require(digest(ROOT/name) == sha, "Diagnostic implementation differs: "+name)
    with gzip.open(archive, "rt") as stream:
        branches = {b["branch_id"]: b for line in stream if (b := json.loads(line)) and not b["passed"]}
    require(report["expected_branches"] == len(branches) == len(report["branches"]), "Branch inventory is incomplete")
    require({r["branch_id"] for r in report["branches"]} == set(branches), "Original failure inventory differs")
    require(report["acceptance"] == {"rtol": 2e-5, "atol": 1e-7}, "Acceptance threshold differs")
    grid = sample_times(300., .01, [ResetTrain(t, t+50., {}) for t in (50., 150., 200.)], post_reset_offset=1e-5)
    require(len(grid) == report["samples"] == 30001 and hashlib.sha256(grid.tobytes()).hexdigest() == report["sample_grid_sha256"],
            "Observation grid differs")
    summaries = []
    selections = [("untreated_baseline", [], grid[grid <= 50.], report["baseline"])]
    selections.extend((row["branch_id"], branches[row["branch_id"]]["reset_trains"], grid, row) for row in report["branches"])
    for bid, trains, times, row in selections:
        require(row["file"] == bid+".json", "Unexpected branch evidence path")
        path = directory/row["file"]
        record = json.loads(path.read_text())
        require(record["fingerprint"] == report["fingerprint"] and record["branch_id"] == bid, "Branch identity differs")
        require(record["reset_trains"] == trains, "Original reset schedule differs")
        counts = [len(ResetTrain(**t).indices()) if t["values"] else 0 for t in trains]
        reset_count = len({float(v) for t in trains if t["values"] for v in ResetTrain(**t).times()})
        traces, hashes = {}, {}
        require(set(record["traces"]) == set(record["integrations"]) == {"taylor128", "taylor192", "roadrunner"},
                "Complete three-integrator evidence is required")
        for label, saved in record["traces"].items():
            require(saved["file"] == bid+"-"+label+".npz", "Unexpected trajectory path")
            data_path = directory/saved["file"]
            require(digest(data_path) == saved["sha256"], "Trajectory digest differs")
            with np.load(data_path, allow_pickle=False) as data:
                names = list(data["observables"])
                require(np.array_equal(data["times"], times) and names == info["observables"], "Observation inventory differs")
                values = data["values"]
                require(values.shape == (len(times), len(names)) and np.isfinite(values).all(), "Incomplete trajectory array")
                trace = pd.DataFrame(values, columns=names); trace.insert(0, "time", times)
            traces[label] = trace
            hashes[label] = saved["sha256"]
            evidence = record["integrations"][label]
            require(evidence["completed"] and evidence["sample_count"] == len(times) and evidence["observables"] == names,
                    "Integration outcome differs")
            if label.startswith("taylor"):
                request = report["requests"][label]
                require(evidence["precision_bits"] == request["precision"] and float(evidence["tolerance"]) == float(request["tolerance"]),
                        "Arithmetic precision or tolerance differs")
                require(evidence["model_sha256"] == info["sha256"] and evidence["absolute_time_preserved"], "Model or clock differs")
                require(evidence["expected_resets"] == evidence["performed_resets"] == reset_count
                        and evidence["expected_train_reset_counts"] == evidence["train_reset_counts"] == counts
                        and evidence["expected_segments"] == evidence["completed_segments"] == reset_count+1,
                        "Reset or segment coverage is incomplete")
        comparisons = {a+"_vs_"+b: comparison(traces[a], traces[b], **report["acceptance"])
                       for a, b in (("taylor128", "taylor192"), ("taylor128", "roadrunner"), ("taylor192", "roadrunner"))}
        require(comparisons == record["comparisons"], "Saved pointwise comparisons do not reproduce")
        converged = comparisons["taylor128_vs_taylor192"]["passed"]
        native = all(c["passed"] for name, c in comparisons.items() if name.endswith("_vs_roadrunner"))
        status = "confirmed" if converged and native else "precision_converged_native_mismatch" if converged else "precision_unresolved"
        require(record["precision_converged"] == converged and record["native_agreement"] == native
                and record["status"] == row["status"] == status, "Diagnostic outcome differs")
        summaries.append({"branch_id": bid, "status": status, "samples": len(times), "resets": reset_count,
                          "record_sha256": digest(path), "trajectory_sha256": hashes, "comparisons": comparisons})
    return {"purpose": __doc__, "report_sha256": digest(report_path), "model_id": report["model_id"],
            "complete_original_failure_coverage": True, "full_protocol_branches": len(branches),
            "precision_converged_branches": sum(s["status"] != "precision_unresolved" for s in summaries[1:]),
            "native_agreeing_branches": sum(s["status"] == "confirmed" for s in summaries[1:]),
            "baseline_status": summaries[0]["status"], "case_recovery_claimed": False,
            "summaries": summaries, "audit_script_sha256": digest(Path(__file__))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(json.dumps({k: result[k] for k in ("model_id", "full_protocol_branches", "precision_converged_branches",
                                            "native_agreeing_branches", "baseline_status")}))
