"""Independently recompute every saved comparison and check partition coverage.

No Heyoka import or integration is needed. Full failure coverage requires the
baseline and all original failed branches, each with all three complete arrays.
This is branch diagnosis, not recovery of the complete memory cases.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_validation import comparison
from grn_memory.taylor_partitions import (ACCEPTANCE, PAIRS, REQUESTS, digest, load_trace,
                                         problem, require, verify_report_identity)


def audit(directories, *, allow_partial=False):
    require(bool(directories), "At least one partition is required")
    summaries, common_core, common_environment, seen = [], None, None, set()
    for directory in map(Path, directories):
        report_path = directory / "report.json"
        report = json.loads(report_path.read_text())
        require(report["status"] == "completed", "Partition is incomplete")
        selected = report["selection"]
        model = int(report["core"]["model_id"].removeprefix("BIOMD"))
        _, info, times, core, selection = problem(model, selected["index"], selected["count"])
        verify_report_identity(report, core, selection)
        require(selection["index"] not in seen, "Duplicate partition")
        seen.add(selection["index"])
        if common_core is None:
            common_core, common_environment = core, report["environment"]
        require(core == common_core and report["environment"] == common_environment,
                "Partitions have different models, sources, requests or environments")
        require(set(report["traces"]) == set(report["integrations"]) == set(REQUESTS),
                "Three complete integrations are required")
        traces = {label: load_trace(directory, report, label, info, times) for label in REQUESTS}
        comparisons = {a + "_vs_" + b: comparison(traces[a], traces[b], **ACCEPTANCE) for a, b in PAIRS}
        converged = comparisons["taylor128_vs_taylor192"]["passed"]
        native = all(comparisons[label + "_vs_roadrunner"]["passed"] for label in ("taylor128", "taylor192"))
        status = "confirmed" if converged and native else "precision_converged_native_mismatch" if converged else "precision_unresolved"
        require(report["comparisons"] == comparisons and report["precision_converged"] == converged
                and report["native_agreement"] == native and report["diagnostic_status"] == status,
                "Saved pointwise comparisons or diagnostic outcome do not reproduce")
        summaries.append({"branch_id": selection["branch_id"], "partition_index": selection["index"],
                          "status": status, "samples": len(times), "report_sha256": digest(report_path),
                          "trajectory_sha256": {k: v["sha256"] for k, v in report["traces"].items()},
                          "comparisons": comparisons})
    missing = sorted(set(range(len(common_core["original_failed_branches"])+1)) - seen)
    require(allow_partial or not missing, "Baseline and all original failed branch partitions are required")
    summaries.sort(key=lambda row: row["partition_index"])
    branches = [row for row in summaries if row["partition_index"] != 0]
    return {"purpose": __doc__, "model_id": common_core["model_id"], "core": common_core,
            "environment": common_environment, "complete_original_failure_coverage": not missing,
            "missing_partition_indices": missing, "full_protocol_branches": len(branches),
            "precision_converged_branches": sum(row["status"] != "precision_unresolved" for row in branches),
            "native_agreeing_branches": sum(row["status"] == "confirmed" for row in branches),
            "baseline_status": next((row["status"] for row in summaries if row["partition_index"] == 0), None),
            "case_recovery_claimed": False, "summaries": summaries, "audit_script_sha256": digest(Path(__file__))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True, help="Repeat once per partition directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true", help="Audit supplied complete partitions without claiming full coverage")
    args = parser.parse_args()
    result = audit(args.input, allow_partial=args.allow_partial)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(json.dumps({k: result[k] for k in ("model_id", "complete_original_failure_coverage", "full_protocol_branches",
                                            "precision_converged_branches", "native_agreeing_branches", "baseline_status")}))
