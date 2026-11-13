"""Inspect truncated COPASI output without changing the original protocols.

This is a declared three-record diagnostic, not a case or model recovery.
Instrumentation preserves the arguments and returned object of Basico's time
course call. It saves COPASI messages and the raw output before the unchanged
adapter rejects incomplete observations. Both native solvers run the full
protocol at the original tolerances and at two strictly tighter requests.
"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import basico
import COPASI
import numpy as np

from grn_memory.catalog_memory import write_json
from grn_memory.catalog_repeated import pulse_schedule, trains_for
from grn_memory.catalog_validation import PACKAGES, comparison, inspect_model
from grn_memory.native_protocols import ResetTrain, protocol_trajectory, sample_times
from scripts.diagnose_breaking_refinement import refinement_requests

ADAPTERS = ("native_protocols.py", "catalog_validation.py", "catalog_repeated.py", "catalog_breaking.py")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def capture(collection_path, inventory_path):
    collection = json.loads(collection_path.read_text())
    inventory = json.loads(inventory_path.read_text())
    require(collection["run_id"] == inventory["parent_run"] and inventory["network"] == 32,
            "Source run or network differs")
    rows = sorted(inventory["records"], key=lambda row: (row["returned_rows"], row["record_id"], row["artifact_id"]))
    require(len(rows) == 300 and all(row["returned_rows"] < row["expected_rows"]
            and row["failed_engines"] == ["copasi"] for row in rows), "Expected 300 exported truncated COPASI records")
    selected = [rows[0], rows[len(rows)//2], rows[-1]]
    partitions = {row["artifact_id"]: row for row in collection["networks"]["32"]["partitions"]}
    sources = []
    for selected_row in selected:
        part = partitions[selected_row["artifact_id"]]
        directory = Path(part["directory"])
        report_path = directory/"BIOMD0000000035.json"
        require(digest(report_path) == part["public_evidence_sha256"][report_path.name], "Source report hash differs")
        report = json.loads(report_path.read_text())
        require(report["engines"] == ["roadrunner", "copasi"], "Unexpected original engines")
        found = []
        for archive in report["evidence_archives"]["branches"]:
            path = directory/archive["file"]
            require(digest(path) == archive["sha256"], "Source archive hash differs")
            with gzip.open(path, "rt") as stream:
                records = [json.loads(line) for line in stream]
            require(len(records) == archive["records"], "Source record count differs")
            for record in records:
                if record["record_id"] == selected_row["record_id"]:
                    require(record["fingerprint"] == report["fingerprint"] and not record["passed"]
                            and record["error"] == selected_row["error"]
                            and record["sample_count"] == selected_row["expected_rows"], "Selected source record differs")
                    found.append({"artifact_id": part["artifact_id"], "original_report_sha256": digest(report_path),
                                  "original_archive": archive, "source_fingerprint": report["fingerprint"],
                                  "model_id": report["biomodel_id"], "model_sha256": report["model_sha256"],
                                  "original_implementation_sha256": report["implementation_sha256"],
                                  "configuration": report["configuration"], "record": record})
        require(len(found) == 1, "Selected record is missing or duplicated")
        sources.extend(found)
    return {"purpose": __doc__, "source_run": collection["run_id"], "source_revision": collection["producer_revision"],
            "inventory_sha256": digest(inventory_path), "selection_rule": "first, middle and last by returned_rows, record_id, artifact_id",
            "exported_incomplete_records": len(rows), "selected_records": sources,
            "full_model_coverage_claimed": False, "case_recovery_claimed": False}


def copasi_messages():
    return COPASI.CCopasiMessage.getAllMessageText()


def observe_time_course(original, destination, monitor, *args, **kwargs):
    """Observe one unchanged call; never pad, trim, interpolate or retry output."""
    try:
        output = original(*args, **kwargs)
    finally:
        monitor["copasi_messages"] = copasi_messages()
    monitor["output_type"] = type(output).__name__
    monitor["settings"] = {key: kwargs.get(key) for key in
                           ("r_tol", "a_tol", "max_steps", "automatic", "output_event", "method")}
    monitor["requested_samples"] = len(kwargs["values"])
    monitor["requested_times_sha256"] = hashlib.sha256(np.asarray(kwargs["values"], dtype=np.float64).tobytes()).hexdigest()
    if hasattr(output, "to_numpy"):
        values = output.to_numpy()
        names = [str(name) for name in output.columns]
        monitor["shape"] = list(values.shape)
        monitor["columns"] = names
        if len(values):
            monitor["last_row"] = {name: float(value) if np.isfinite(value) else str(value)
                                   for name, value in zip(names, values[-1])}
        np.savez_compressed(destination, values=values, columns=np.asarray(names))
        monitor["raw_output"] = {"file": destination.name, "sha256": digest(destination)}
    return output


def diagnose(source, output):
    require(len(source["selected_records"]) == 3 and not source["case_recovery_claimed"], "Three declared records required")
    require(not output.exists(), "Use a fresh diagnostic directory")
    output.mkdir(parents=True)
    write_json(output/"source-evidence.json", source)
    model = ROOT/"models/BIOMD0000000035.xml"
    info = inspect_model(model)
    implementation = {name: digest(ROOT/"grn_memory"/name) for name in ADAPTERS}
    report = {"purpose": __doc__, "started_at": datetime.now(timezone.utc).isoformat(),
              "source_evidence_sha256": digest(output/"source-evidence.json"), "model_sha256": info["sha256"],
              "script_sha256": digest(Path(__file__)), "source_revision": subprocess.check_output(
                  ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "implementation_sha256": implementation, "refinement_policy_sha256": digest(ROOT/"scripts/diagnose_breaking_refinement.py"),
              "versions": {p: version(p) for p in PACKAGES}, "python": platform.python_version(), "platform": platform.platform(),
              "status": "running", "expected_records": 3, "records": [], "case_recovery_claimed": False}
    write_json(output/"report.json", report)
    possible = trains_for(pulse_schedule(), {}) + [ResetTrain(t, t+100., {}) for t in (1010., 1210., 1410., 1610., 1810., 2010.)]
    for selected in source["selected_records"]:
        require(selected["model_id"] == "BIOMD0000000035" and selected["model_sha256"] == info["sha256"], "Model differs")
        require(all(sha == selected["original_implementation_sha256"][name] for name, sha in implementation.items()),
                "Numerical adapters differ from original source")
        config = selected["configuration"]
        require(config["dt"] == .01 and config["post_reset_offset"] == 1e-5
                and config["comparison_rtol"] == 2e-5 and config["comparison_atol"] == 1e-7,
                "Original grid or acceptance differs")
        record = selected["record"]; spec = record["specification"]; bid = record["record_id"]
        grid = sample_times(2210., .01, possible, post_reset_offset=1e-5)
        times = grid[grid <= spec["stop"]]
        require(len(times) == record["sample_count"], "Original observation count differs")
        trains = [ResetTrain(**train) for train in spec["reset_trains"]]
        result = {"source_record_id": bid, "original_error": record["error"], "specification": spec,
                  "samples": len(times), "times_sha256": hashlib.sha256(times.tobytes()).hexdigest(),
                  "integrations": {}, "comparisons": {}, "trajectories": {}}
        traces = {}; destination = output/(bid+".json")
        for engine in ("roadrunner", "copasi"):
            for label, request in refinement_requests(spec["integration_settings"][engine]).items():
                key = engine+"_"+label; row = {"request": request, "completed": False}; began = time.monotonic()
                try:
                    if engine == "copasi":
                        COPASI.CCopasiMessage.clearDeque()
                        original_call = basico.run_time_course_with_output
                        def observed(*args, **kwargs):
                            return observe_time_course(original_call, output/(bid+"-"+key+"-raw.npz"), row, *args, **kwargs)
                        with patch.object(basico, "run_time_course_with_output", observed):
                            trace = protocol_trajectory(model, times, trains, engine, **request)
                    else:
                        trace = protocol_trajectory(model, times, trains, engine, **request)
                    require(list(trace.columns) == ["time"]+info["observables"]
                            and np.array_equal(trace.time.to_numpy(), times), "Full original observation inventory required")
                    traces[key] = trace
                    path = output/(bid+"-"+key+".npz")
                    np.savez_compressed(path, times=times, values=trace.iloc[:,1:].to_numpy(),
                                        observables=np.asarray(info["observables"]))
                    result["trajectories"][key] = {"file": path.name, "sha256": digest(path)}
                    row.update(completed=True, samples=len(trace))
                except Exception as error:
                    row["error"] = f"{type(error).__name__}: {error}"
                    if engine == "copasi": row.setdefault("copasi_messages", copasi_messages())
                row["seconds"] = time.monotonic()-began
                result["integrations"][key] = row
                write_json(destination, result)
                print(bid[:12], key, "completed" if row["completed"] else row["error"], flush=True)
                if row.get("copasi_messages"): print(row["copasi_messages"][:3000], flush=True)
        pairs = [("roadrunner_"+label, "copasi_"+label) for label in ("original", "tight", "tighter")]
        pairs += [(engine+"_"+a, engine+"_"+b) for engine in ("roadrunner", "copasi")
                  for a,b in (("original", "tight"), ("tight", "tighter"))]
        result["comparisons"] = {a+"_vs_"+b: comparison(traces[a], traces[b], rtol=2e-5, atol=1e-7)
                                 for a,b in pairs if a in traces and b in traces}
        required = [a+"_vs_"+b for a,b in pairs if "original" not in a+"_vs_"+b]
        result["refinement_confirmed"] = all(result["comparisons"].get(key, {}).get("passed", False) for key in required)
        write_json(destination, result)
        report["records"].append({"record_id": bid, "file": destination.name, "sha256": digest(destination),
                                  "refinement_confirmed": result["refinement_confirmed"]})
        write_json(output/"report.json", report)
    report.update(status="completed", finished_at=datetime.now(timezone.utc).isoformat())
    write_json(output/"report.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--collection", type=Path)
    group.add_argument("--source-evidence", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.collection and not args.inventory: parser.error("--collection requires --inventory")
    source = capture(args.collection, args.inventory) if args.collection else json.loads(args.source_evidence.read_text())
    diagnose(source, args.output)
