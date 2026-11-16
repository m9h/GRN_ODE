"""Recompute all full-array comparisons and complete cases across fixed partitions.

All original failed cases, every possible later control, and the full untreated
baseline are required. Partial partitions and a passing branch pilot cannot
recover a case. Original passing cases are not included in this recovery claim.
"""

import argparse
from contextlib import ExitStack
import fcntl
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_breaking import trial_windows
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_repeated import summarize
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain
from grn_memory.scipy_breaking_recovery import ACCEPTANCE, digest, labels_for
from grn_memory.scipy_case_partitions import (SOURCE_FILES, load_experiment, validate_metadata,
                                             validate_partition_inventory, verify_repository_sources)
from scripts.audit_scipy_breaking import trajectory
from scripts.audit_scipy_breaking_cases import check_outcome, evaluate_case, summary_discrepancy


def read(path):
    return json.loads(path.read_text())


def audit_record(directory, entry, report, inventory, grid, info):
    meta = report["metadata"]
    experiment = meta["experiment"]
    engine, requests = experiment["reference_engine"], experiment["requests"]
    labels = labels_for(engine)
    bid = entry["record_id"]
    require(entry["file"] == bid + ".json", "Unexpected branch record path")
    record_path = directory / entry["file"]
    require(digest(record_path) == entry["sha256"], "Branch record hash differs")
    record = read(record_path)
    spec = inventory["branches"][bid]
    require(record["record_id"] == bid and record["fingerprint"] == meta["fingerprint"]
            and record["specification"] == spec and record["case_recovery_claimed"] is False
            and "reused_from" not in record, "Branch identity, source or scope differs")
    require(set(record["integrations"]) == set(labels), "All four integration outcomes are required")
    times = grid[grid <= spec["stop"]]
    trains = [ResetTrain(**t) for t in spec["reset_trains"]]
    traces = {}
    for label in labels:
        outcome = record["integrations"][label]
        if check_outcome(outcome, label, requests[label], times, info["observables"], trains, info["sha256"]):
            if not label.startswith("scipy"):
                require(outcome.get("native_engine") == engine, "Native implementation identity differs")
            require(label in record["traces"], "Completed integration has no saved trajectory")
            traces[label] = trajectory(directory, bid, label, record["traces"][label], times, info["observables"])
    require(set(traces) == set(record["traces"]), "Unexpected array outside completed integrations")
    checks = {a + "_vs_" + b: comparison(traces[a], traces[b], **ACCEPTANCE)
              for i, a in enumerate(labels) for b in labels[i + 1:] if a in traces and b in traces}
    require(checks == record["comparisons"], "Comparisons do not reproduce from every saved observation")
    status = ("incomplete" if len(checks) != 6 else
              "confirmed" if all(c["passed"] for c in checks.values()) else "mismatch")
    require(record["status"] == entry["status"] == status, "Branch status contradicts full arrays")
    windows = {label: summarize(trace, trial_windows(round((spec["stop"] - 1010) / 400)))
               for label, trace in traces.items()}
    return {"status": status, "windows": windows}, {
        "record_id": bid, "shard_index": meta["shard_index"], "status": status,
        "record_sha256": entry["sha256"], "samples": len(times), "traces": record["traces"],
        "comparisons": checks}


def audit(directories):
    require(bool(directories), "Complete original partition inventory is required")
    require(len({p.resolve() for p in directories}) == len(directories), "Duplicate input directory")
    first = directories[0]
    plan, inventory, _, info, grid = load_experiment(first)
    inputs = sorted([(directory, read(directory / "report.json")) for directory in directories],
                    key=lambda item: item[1]["metadata"]["shard_index"])
    reports = [report for _, report in inputs]
    validate_partition_inventory(reports, plan, inventory)
    branches, records, provenance = {}, [], []
    for directory, report in inputs:
        report_sha = digest(directory / "report.json")
        require(read(directory / "execution-plan.json") == plan
                and read(directory / "inventory.json") == inventory,
                "Partition input plan or reconstructed inventory differs")
        require(all(digest(directory / name) == plan["source_files_sha256"][name] for name in SOURCE_FILES),
                "Partition original evidence differs")
        require(report["case_recovery_claimed"] is False and report["full_model_coverage_claimed"] is False,
                "Producer cannot promote a case or model")
        validate_metadata(report["metadata"], directory / "execution-plan.json", plan, inventory, grid)
        verify_repository_sources(report["producer_revision"], report["metadata"]["experiment"]["implementation_sha256"])
        for entry in report["branches"]:
            bid = entry["record_id"]
            require(bid not in branches, "Overlapping branch partitions")
            branches[bid], record = audit_record(directory, entry, report, inventory, grid, info)
            records.append(record)
        require(report["confirmed_branches"] == sum(b["status"] == "confirmed" for b in report["branches"]),
                "Confirmed partition branch count differs")
        require(digest(directory / "report.json") == report_sha, "Producer changed during audit")
        provenance.append({"directory": str(directory), "report_sha256": report_sha,
                           "shard_index": report["metadata"]["shard_index"],
                           "fingerprint": report["metadata"]["fingerprint"]})
    original = read(first / "source-evidence.json")["original_report"]
    reference = read(ROOT / "results/catalog-repeated" / (inventory["model_id"] + ".json"))
    labels = labels_for(plan["reference_engine"])
    baseline = branches[inventory["full_untreated_control"]]["status"] == "confirmed"
    captured = read(first / "original-case-plan.json")["cases"]
    cases = {}
    for key, value in inventory["cases"].items():
        result = evaluate_case(value["original_plan"], reference, original["configuration"], branches,
                               baseline, labels)
        original_path = {name: {f: t[f] for f in ("breakers", "responses")}
                         for name, t in captured[key]["case"]["trials"].items()}
        result["original_path"] = original_path
        for label in ("primary", "refined"):
            path = {name: {f: t[f] for f in ("breakers", "responses")}
                    for name, t in result[label + "_search"]["trials"].items()}
            result[label + "_matches_original_path"] = path == original_path
        cases[key] = result
    contradictions = {}
    with gzip.open(first / "source-branches.jsonl.gz", "rt") as stream:
        for line in stream:
            old = json.loads(line)
            new = branches[old["record_id"]]
            if old["passed"] and new["status"] == "confirmed":
                difference = summary_discrepancy(old, new)
                if difference["max_scaled_error"] > 1:
                    contradictions[old["record_id"]] = difference
    return {"purpose": __doc__, "model_id": inventory["model_id"],
            "experiment_fingerprint": reports[0]["metadata"]["experiment_fingerprint"],
            "complete_selected_control_inventory": True, "baseline_passed": baseline,
            "expected_branches": inventory["expected_branches"],
            "confirmed_branches": sum(b["status"] == "confirmed" for b in branches.values()),
            "branches": records, "cases": cases, "partitions": provenance,
            "selected_cases": len(cases), "recovered_selected_cases": sum(c["passed"] for c in cases.values()),
            "original_passing_cases_included": False, "full_model_coverage_claimed": False,
            "original_passing_branches_requiring_revalidation": contradictions,
            "cross_run_native_array_agreement_claimed": False, "numerical_integrations_performed": 0,
            "audit_script_sha256": digest(Path(__file__)),
            "case_auditor_sha256": digest(ROOT / "scripts/audit_scipy_breaking_cases.py"),
            "array_reader_sha256": digest(ROOT / "scripts/audit_scipy_breaking.py")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with ExitStack() as stack:
        for directory in args.input:
            lock = stack.enter_context(directory.with_name(directory.name + ".lock").open("a"))
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        result = audit(args.input)
    write_json(args.output, result)
    print(json.dumps({k: result[k] for k in ("selected_cases", "recovered_selected_cases", "baseline_passed")}))
