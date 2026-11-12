"""Refine failed native breaking branches without changing their protocols.

The source evidence captures all failed branches from a completed model report.
Only the two tighter requests and their mutual agreement determine refinement
confirmation. The original failures remain explicit. This diagnostic does not
recompute case scores or the conditional choice of later trials.
"""

import argparse
from decimal import Decimal
import gzip
import hashlib
from importlib.metadata import version
import json
import logging
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_breaking import trial_windows
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_repeated import pulse_schedule, summarize, trains_for
from grn_memory.catalog_validation import PACKAGES, comparison, inspect_model
from grn_memory.native_protocols import ResetTrain, protocol_trajectory, sample_times
from grn_memory.timed_drives import encode_yoon_drives, yoon_trajectory


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refinement_requests(original):
    """Tighten both recorded tolerances, including models with tiny states."""
    if set(original) != {"rtol", "atol"} or any(not math.isfinite(v) or v <= 0 for v in original.values()):
        raise ValueError("Positive finite original rtol and atol are required")
    requests = {"original": dict(original)}
    for label, factor in (("tight", 10), ("tighter", 20)):
        requests[label] = {k: float(Decimal(str(v))/factor) for k, v in original.items()}
    if any(not 0 < requests["tighter"][k] < requests["tight"][k] < original[k] for k in original):
        raise ValueError("Both tolerances must remain positive and strictly decrease")
    return requests


def trajectory_for(original, path):
    if original["engines"] != ["roadrunner", "copasi"]:
        raise NotImplementedError("This diagnostic requires the two native ODE engines")
    encoding = original["configuration"].get("timed_drive_encoding")
    if encoding:
        expected = {"method": "equivalent timed g1/g2 switches as events for t >= 0",
                    "sha256": hashlib.sha256(encode_yoon_drives(path).encode()).hexdigest()}
        if encoding != expected:
            raise ValueError("Original timed-drive encoding differs")
        return yoon_trajectory
    return protocol_trajectory


def capture(report_path):
    original = json.loads(report_path.read_text())
    if "finished_at" not in original:
        raise ValueError("Source model must have finished before evidence capture")
    records, hashes = {}, {}
    for entry in original["evidence_archives"]["branches"]:
        archive = report_path.parent/entry["file"]
        actual = digest(archive)
        if actual != entry["sha256"]:
            raise ValueError("Original branch archive hash differs")
        hashes[entry["file"]] = actual
        with gzip.open(archive, "rt") as stream:
            rows = [json.loads(line) for line in stream]
        if len(rows) != entry["records"]:
            raise ValueError("Original archive record count differs")
        for row in rows:
            if row["record_id"] in records or row["fingerprint"] != original["fingerprint"]:
                raise ValueError("Duplicate or incorrectly fingerprinted branch")
            records[row["record_id"]] = row
    if len(records) != original["evaluated_unique_branches"]:
        raise ValueError("Incomplete source branch inventory")
    return {"original_report": original, "original_report_sha256": digest(report_path),
        "verified_source_archives": hashes,
        "failed_branches": [b for _, b in sorted(records.items()) if not b["passed"]]}


def diagnose(args):
    evidence = capture(args.report) if args.report else json.loads(args.evidence.read_text())
    original = evidence["original_report"]
    path = ROOT/"models"/(original["biomodel_id"]+".xml")
    info = inspect_model(path)
    if info["sha256"] != original["model_sha256"]:
        raise ValueError("Model and original report hashes differ")
    trajectory = trajectory_for(original, path)
    args.output.mkdir(parents=True, exist_ok=True)
    evidence_path = args.output/"source-evidence.json"
    write_json(evidence_path, evidence)
    possible = trains_for(pulse_schedule(), {})
    possible += [ResetTrain(t,t+100.,{}) for t in (1010.,1210.,1410.,1610.,1810.,2010.)]
    config = original["configuration"]
    grid = sample_times(2210., config["dt"], possible, post_reset_offset=config["post_reset_offset"])
    metadata = {"purpose": __doc__, "model_id": original["biomodel_id"],
        "model_sha256": info["sha256"], "source_evidence_sha256": digest(evidence_path),
        "script_sha256": digest(Path(__file__)),
        "implementation_sha256": {name: digest(ROOT/"grn_memory"/name) for name in
            ("native_protocols.py", "catalog_validation.py", "catalog_repeated.py", "catalog_breaking.py", "timed_drives.py")},
        "timed_drive_encoding": config.get("timed_drive_encoding"),
        "request_policy": "original recorded tolerances, each divided by 10, then by 20",
        "observation_grid_sha256": hashlib.sha256(grid.tobytes()).hexdigest(),
        "versions": {p: version(p) for p in PACKAGES},
        "comparison_settings": {"rtol": config["comparison_rtol"], "atol": config["comparison_atol"]},
        "expected_branches": len(evidence["failed_branches"]), "branches": [], "status": "running"}
    write_json(args.output/"report.json", metadata)
    for source in evidence["failed_branches"]:
        bid = source["record_id"]
        spec = source["specification"]
        times = grid[grid <= spec["stop"]]
        if len(times) != source["sample_count"]:
            raise ValueError("Original sample count differs from reconstructed grid")
        trains = [ResetTrain(**t) for t in spec["reset_trains"]]
        result = {"source_record_id": bid, "specification": spec,
            "original_comparison": source.get("comparison"), "original_error": source.get("error"),
            "integrations": {}, "comparisons": {}, "windows": {}}
        destination = args.output/(bid+".json")
        traces = {}
        for engine in original["engines"]:
            requests = refinement_requests(spec["integration_settings"][engine])
            for label, request in requests.items():
                key = engine+"_"+label
                row = {"request": request}
                began = time.monotonic()
                try:
                    trace = trajectory(path, times, trains, engine, **request)
                    if (list(trace.columns) != ["time"]+info["observables"] or len(trace) != len(times)
                            or not (trace["time"].to_numpy() == times).all()):
                        raise ValueError("Complete original observation inventory is required")
                    traces[key] = trace
                    row.update(completed=True, samples=len(trace))
                    result["windows"][key] = summarize(trace, trial_windows(round((spec["stop"]-1010)/400)))
                except Exception as exc:
                    row.update(completed=False, error=f"{type(exc).__name__}: {exc}")
                row["seconds"] = time.monotonic()-began
                result["integrations"][key] = row
                write_json(destination, result)
                print(bid[:12], key, "completed" if row["completed"] else row["error"],
                      f'{row["seconds"]:.2f}s', flush=True)
        pairs = [("roadrunner_"+v, "copasi_"+v) for v in ("original", "tight", "tighter")]
        pairs += [(e+"_"+a, e+"_"+b) for e in original["engines"]
                  for a,b in (("original", "tight"), ("tight", "tighter"))]
        required = []
        for a,b in pairs:
            name = a+"_vs_"+b
            if "original" not in name:
                required.append(name)
            if a in traces and b in traces:
                result["comparisons"][name] = comparison(traces[a], traces[b], **metadata["comparison_settings"])
        result["refinement_confirmed"] = all(result["comparisons"].get(k, {}).get("passed", False) for k in required)
        write_json(destination, result)
        metadata["branches"].append({"record_id": bid, "file": destination.name,
            "refinement_confirmed": result["refinement_confirmed"], "sha256": digest(destination)})
        write_json(args.output/"report.json", metadata)
        print(len(metadata["branches"]), "/", metadata["expected_branches"], bid[:12],
              result["refinement_confirmed"], flush=True)
    metadata.update(status="completed", confirmed_branches=sum(b["refinement_confirmed"] for b in metadata["branches"]))
    write_json(args.output/"report.json", metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--report", type=Path, help="Completed original model report, beside its published archives")
    source.add_argument("--evidence", type=Path, help="Previously captured source-evidence.json")
    parser.add_argument("--output", type=Path, required=True)
    logging.getLogger("basico.task_timecourse").setLevel(logging.CRITICAL)
    diagnose(parser.parse_args())
