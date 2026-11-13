"""Compute all controls and possible continuations for complete breaking cases.

Every branch retains four full trajectories and six pairwise comparisons.
An independent case audit must recompute the conditional search before any
case is recovered. Original native results are preserved separately.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from grn_memory.breaking_audit import require
from grn_memory.catalog_jax import source_hashes
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain, protocol_trajectory
from grn_memory.scipy_reference import scipy_protocol_trajectory
from grn_memory.scipy_breaking_recovery import ACCEPTANCE, LABELS, digest, prepare_inventory
from scripts.audit_scipy_breaking import audit as audit_failed_branches, PACKAGES, SOURCES
from scripts.diagnose_scipy_breaking import load_saved


EXTRA_SOURCES = ("scripts/diagnose_scipy_breaking_controls.py", "grn_memory/scipy_breaking_recovery.py",
                 "grn_memory/breaking_audit.py", "grn_memory/breaking_scores.py",
                 "scripts/audit_scipy_breaking.py")


def read(path):
    return json.loads(Path(path).read_text())


def validate_resume(report, signature):
    require(report["fingerprint"] == signature, "Resume requires unchanged source, inventory and environment")


def compute_branch(bid, spec, directory, metadata, grid, path, info, *, resume=False, imported=None):
    signature = metadata["fingerprint"]
    requests = metadata["requests"]
    times = grid[grid <= spec["stop"]]
    trains = [ResetTrain(**t) for t in spec["reset_trains"]]
    record_path = directory / (bid + ".json")
    record = {"fingerprint": signature, "record_id": bid, "specification": spec, "integrations": {},
              "traces": {}, "comparisons": {}, "status": "running", "case_recovery_claimed": False}
    if resume and record_path.exists():
        record = read(record_path)
        validate_resume(record, signature)
        require(record["record_id"] == bid and record["specification"] == spec,
                "Cached branch specification differs")
    elif imported:
        prior, source, provenance = imported
        require(prior["record_id"] == bid and prior["specification"] == spec
                and prior["status"] == "confirmed", "Imported branch identity or status differs")
        record["integrations"] = deepcopy(prior["integrations"])
        record["traces"] = deepcopy(prior["traces"])
        record["reused_from"] = provenance
        for label in LABELS:
            saved = prior["traces"][label]
            require(saved["file"] == bid + "-" + label + ".npz", "Imported trajectory path differs")
            shutil.copyfile(source / saved["file"], directory / saved["file"])
    require(set(record["integrations"]) <= set(LABELS)
            and set(record["traces"]) == {k for k, v in record["integrations"].items() if v.get("completed") is True},
            "Cached trajectory inventory differs from completed integrations")
    traces = {}
    for label in LABELS:
        request = requests[label]
        array_path = directory / (bid + "-" + label + ".npz")
        if record["integrations"].get(label, {}).get("completed") and label in record["traces"]:
            traces[label] = load_saved(array_path, record["traces"][label], times, info["observables"],
                                       record["integrations"][label], label, request, trains, info["sha256"])
            continue
        if label in record["integrations"]:
            record.setdefault("previous_incomplete_attempts", {}).setdefault(label, []).append(
                deepcopy(record["integrations"][label]))
        outcome = {"request": request, "completed": False}
        record["integrations"][label] = outcome
        began = time.monotonic()

        def progress(row):
            if row["completed_segments"] % 500 == 0:
                write_json(record_path, record)
                print(bid[:12], label, row["completed_segments"], row["last_interval"], flush=True)

        try:
            if label.startswith("scipy"):
                trace = scipy_protocol_trajectory(path, times, trains, **request, evidence=outcome, progress=progress)
                outcome["observables"] = list(trace.columns[1:])
            else:
                trace = protocol_trajectory(path, times, trains, "roadrunner", **request)
                outcome.update(completed=True, sample_count=len(times), observables=list(trace.columns[1:]))
            require(np.array_equal(trace.time.to_numpy(), times), "Observation times differ")
            np.savez_compressed(array_path, times=times, values=trace.iloc[:, 1:].to_numpy(),
                                observables=np.asarray(list(trace.columns[1:])))
            record["traces"][label] = {"file": array_path.name, "sha256": digest(array_path)}
            traces[label] = load_saved(array_path, record["traces"][label], times, info["observables"],
                                       outcome, label, request, trains, info["sha256"])
        except Exception as error:
            outcome.update(completed=False, error=f"{type(error).__name__}: {error}")
            record["traces"].pop(label, None)
        outcome["seconds"] = time.monotonic() - began
        write_json(record_path, record)
    record["comparisons"] = {a + "_vs_" + b: comparison(traces[a], traces[b], **ACCEPTANCE)
                              for i, a in enumerate(LABELS) for b in LABELS[i+1:] if a in traces and b in traces}
    record["status"] = ("incomplete" if len(record["comparisons"]) != 6 else
                         "confirmed" if all(c["passed"] for c in record["comparisons"].values()) else "mismatch")
    write_json(record_path, record)
    return {"record_id": bid, "file": record_path.name, "sha256": digest(record_path), "status": record["status"]}


def diagnose(args):
    inventory, path, info, grid = prepare_inventory(args.evidence, args.case_plan, args.source_revision,
                                                   args.original_branches)
    source = read(args.diagnostics / "report.json")
    require(source["model_id"] == inventory["model_id"]
            and source["source_report_sha256"] == inventory["source_report_sha256"],
            "Failed-branch diagnostic source differs")
    sources = source_hashes()
    sources.update({name: digest(ROOT / name) for name in (*SOURCES, *EXTRA_SOURCES)})
    versions = {p: version(p) for p in PACKAGES}
    require(versions == source["versions"], "Diagnostic producer environment differs")
    require(all(source["requests"]["roadrunner"][k] < spec["integration_settings"]["roadrunner"][k]
                for spec in inventory["branches"].values() for k in ("rtol", "atol")),
            "RoadRunner requests must refine every original branch")
    audited = audit_failed_branches(args.diagnostics)
    require(audited["all_selected_branches_confirmed"] and audited["complete_captured_failure_coverage"],
            "Complete confirmed original failed-branch diagnostics are required")
    metadata = {"model_id": inventory["model_id"], "model_sha256": info["sha256"],
                "inventory_sha256": fingerprint(inventory), "requests": source["requests"],
                "acceptance": ACCEPTANCE, "implementation_sha256": sources, "versions": versions,
                "sample_grid_sha256": hashlib.sha256(grid.tobytes()).hexdigest(),
                "reused_report_sha256": digest(args.diagnostics / "report.json"),
                "reused_audit_sha256": fingerprint(audited), "case_recovery_claimed": False,
                "full_model_coverage_claimed": False}
    signature = fingerprint(metadata)
    report_path = args.output / "report.json"
    if report_path.exists():
        require(args.resume, "Existing output requires --resume")
        validate_resume(read(report_path), signature)
    args.output.mkdir(parents=True, exist_ok=True)
    for src, name in ((args.evidence, "source-evidence.json"), (args.case_plan, "original-case-plan.json"),
                      (args.original_branches, "source-branches.jsonl.gz"),
                      (args.original_branches.parent / "source-branches-provenance.json", "source-branches-provenance.json"),
                      (args.diagnostics / "report.json", "reused-report.json")):
        shutil.copyfile(src, args.output / name)
    write_json(args.output / "inventory.json", inventory)
    write_json(args.output / "reused-audit.json", audited)
    report = {"purpose": __doc__, **metadata, "fingerprint": signature, "status": "running",
              "expected_branches": inventory["expected_branches"], "branches": [],
              "expected_model_cases": inventory["expected_model_cases"],
              "selected_case_keys": sorted(inventory["cases"]),
              "full_untreated_control": inventory["full_untreated_control"],
              "started_at": datetime.now(timezone.utc).isoformat()}
    write_json(report_path, report)
    reused = {e["record_id"]: e for e in source["branches"]}
    require(set(reused) <= inventory["branches"].keys(), "Diagnostic branches are outside the complete cases")
    order = [inventory["full_untreated_control"]] + sorted(set(inventory["branches"]) - {inventory["full_untreated_control"]})
    for bid in order:
        imported = None
        if bid in reused:
            entry = reused[bid]
            require(entry["file"] == bid + ".json", "Imported record path differs")
            source_path = args.diagnostics / entry["file"]
            require(digest(source_path) == entry["sha256"], "Imported branch digest differs")
            imported = (read(source_path), args.diagnostics,
                        {"report_sha256": metadata["reused_report_sha256"], "record_sha256": entry["sha256"]})
        row = compute_branch(bid, inventory["branches"][bid], args.output, report, grid, path, info,
                             resume=args.resume, imported=imported)
        report["branches"].append(row)
        write_json(report_path, report)
        print(len(report["branches"]), "/", len(order), bid[:12], row["status"], flush=True)
    report.update(status="completed", confirmed_branches=sum(b["status"] == "confirmed" for b in report["branches"]),
                  finished_at=datetime.now(timezone.utc).isoformat())
    write_json(report_path, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--case-plan", type=Path, required=True)
    parser.add_argument("--original-branches", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".diagnostic.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        diagnose(args)
