"""Audit complete single-worker breaking reports without promoting failures.

Initial-case coverage, conditional-search coverage and numerical agreement are
separate results. A failed integration can leave later conditional choices
unknown even when every initial case was attempted. Saved comparisons and
window summaries are audited here; numerical integration is not rerun.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import audit_branch, audit_case, audit_comparison, require
from grn_memory.catalog_breaking import candidate_plans, trial_windows
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_repeated import pulse_schedule
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import inspect_model
from scripts.audit_breaking_shards import digest, read_archives, source_hash


IMPLEMENTATION_FILES = {
    "catalog_breaking.py", "breaking_scores.py", "catalog_archive.py", "paired_scores.py",
    "catalog_repeated.py", "catalog_runner.py", "catalog_memory.py", "catalog_validation.py",
    "native_protocols.py", "delay_protocols.py", "scheper_delay.py", "simulation.py",
    "analysis.py", "timed_drives.py", "protocol_retries.py",
}


def audit_model(directory, entry, revision):
    mid = entry["biomodel_id"]
    path = directory/(mid+".json")
    report = json.loads(path.read_text())
    require(report["status"] in ("passed", "incomplete_or_failed") and report.get("finished_at"),
            "Only terminal model reports can be audited")
    require(report["network"] == entry["network"] and report["biomodel_id"] == mid,
            "Model report identity differs")
    info = inspect_model(ROOT/"models"/(mid+".xml"))
    reference_path = ROOT/"results/catalog-repeated"/(mid+".json")
    reference = json.loads(reference_path.read_text())
    require(reference["status"] == "passed" and reference["model_sha256"] == info["sha256"],
            "Invalid repeated reference")
    require(report["model_sha256"] == info["sha256"], "Model source differs")
    require(report["reference_file_sha256"] == digest(reference_path)
            and report["reference_fingerprint"] == reference["fingerprint"], "Calibration differs")
    require(report["engines"] == reference["engines"] and report["targets"] == reference["targets"],
            "Engine or independent-state inventory differs")
    metadata = {k: report[k] for k in ("configuration", "model_sha256", "reference_fingerprint",
                "reference_file_sha256", "implementation_sha256", "versions")}
    require(fingerprint(metadata) == report["fingerprint"], "Model fingerprint differs")
    require(set(report["implementation_sha256"]) == IMPLEMENTATION_FILES, "Worker source inventory differs")
    for name, sha in report["implementation_sha256"].items():
        require(source_hash(revision, "grn_memory/"+name) == sha, "Worker source differs: "+name)
    config = report["configuration"]
    require(config["dt"] == .01 and config["post_reset_offset"] == 1e-5, "Observation grid differs")
    require(config["comparison_rtol"] == 2e-5 and config["comparison_atol"] == 1e-7,
            "Comparison threshold differs")
    require(config["prefix"] == pulse_schedule()
            and config["trials"] == {k: list(v) for k, v in trial_windows(3).items()}, "Protocol timeline differs")
    require(config["reset_interval"] == .1 and config["prefix_endpoint_resets"]
            and not config["later_endpoint_resets"] and config["later_resets_per_exposure"] == 999,
            "Reset timing differs")
    plans = candidate_plans(reference)
    require(config["candidate_plan_sha256"] == fingerprint(plans), "Candidate plan differs")
    require(report["no_candidates"] == (not plans), "No-candidate flag differs")
    require(report["expected_cases"] == report["evaluated_cases"] == len(plans)
            and set(report["cases"]) == set(plans), "Complete initial-case coverage is missing")
    require(report["expected_initial_response_assessments"] == sum(len(p["responses"]) for p in plans.values()),
            "Initial response inventory differs")
    branches = read_archives(directory, report, "branches")
    cases = read_archives(directory, report, "cases")
    require(len(branches) == report["evaluated_unique_branches"], "Branch count differs")
    require(set(cases) == {fingerprint(p) for p in plans.values()}, "Case evidence coverage differs")
    for branch in branches.values():
        audit_branch(branch, report, info["observables"])
    control_id = fingerprint({"reset_trains": [], "stop": 2210.,
                              "integration_settings": config["integration_settings"]})
    require(control_id in branches, "Full untreated control is missing")
    control = branches[control_id]
    require(report["control_comparison"] == control.get("comparison", {"passed": False, "error": control.get("error")}),
            "Untreated comparison differs")
    controls = [control["passed"]]
    if config["timed_drive_encoding"]:
        require(set(report["encoding_control_comparisons"]) == set(report["engines"]), "Timed-drive controls missing")
        controls.extend(audit_comparison(c, 221001, info["observables"])
                        for c in report["encoding_control_comparisons"].values())
    used, summaries, unresolved = {control_id}, {}, []
    for key, plan in plans.items():
        case = cases[fingerprint(plan)]
        require(case["case_key"] == key, "Case key differs")
        summary, ids, unknown = audit_case(case, plan, branches, report, reference)
        require(summary == report["cases"][key], "Case summary does not reproduce")
        summaries[key] = summary
        used.update(ids)
        unresolved.extend({"case": key, "trial": trial} for trial in unknown)
    require(used == set(branches), "Unreferenced or missing branch evidence")
    retries = sum(any(len(a) > 1 for a in b["solver_attempts"].values()) for b in branches.values())
    require(report["solver_retry_branches"] == retries, "Solver retry count differs")
    passed = sum(c["status"] == "passed" for c in summaries.values())
    require(report["passed_cases"] == passed, "Passed-case count differs")
    validated = passed == len(plans) and all(controls) and not unresolved
    require((report["status"] == "passed") == validated, "Model outcome contradicts its evidence")
    return {**entry, "name": report["name"], "status": report["status"],
            "source_revision": revision, "report_sha256": digest(path), "fingerprint": report["fingerprint"],
            "complete_initial_case_coverage": True, "complete_conditional_search": not unresolved,
            "all_numerical_validations_passed": validated,
            "cases": len(plans), "passed_cases": passed,
            "conditional_trials": sum(c["evaluated_trials"] for c in summaries.values()),
            "response_trials": sum(c["evaluated_response_trials"] for c in summaries.values()),
            "branches": len(branches), "passed_branches": sum(b["passed"] for b in branches.values()),
            "incomplete_branches": sum("error" in b for b in branches.values()),
            "completed_mismatch_branches": sum(not b["passed"] and "error" not in b for b in branches.values()),
            "solver_retry_branches": retries, "unresolved_conditional_decisions": unresolved,
            "failed_branches": {key: {"specification": b["specification"], "error": b.get("error"),
                                     "comparison": b.get("comparison"), "refinement": b.get("refinement")}
                                for key, b in branches.items() if not b["passed"]},
            "case_summaries": summaries}


def audit(directory, revision, networks=None):
    catalog = json.loads((ROOT/"models/catalog.json").read_text())["models"]
    inventory = {m["network"] for m in catalog}
    selected = inventory if networks is None else set(networks)
    require(bool(selected) and selected <= inventory, "Select one or more original catalog networks")
    models = [audit_model(directory, entry, revision) for entry in catalog if entry["network"] in selected]
    totals = Counter()
    for model in models:
        for key in ("cases", "passed_cases", "conditional_trials", "response_trials", "branches",
                    "passed_branches", "incomplete_branches", "completed_mismatch_branches", "solver_retry_branches"):
            totals[key] += model[key]
        totals["passed_models"] += model["all_numerical_validations_passed"]
        totals["models_with_unresolved_conditional_decisions"] += not model["complete_conditional_search"]
    totals["models"] = len(models)
    return {"purpose": __doc__, "source_revision": revision, "selected_networks": sorted(selected),
            "catalog_model_count": len(catalog), "complete_selected_initial_case_coverage": True,
            "complete_selected_conditional_search": all(m["complete_conditional_search"] for m in models),
            "complete_catalog_initial_case_coverage": selected == inventory,
            "complete_catalog_conditional_search": selected == inventory and all(m["complete_conditional_search"] for m in models),
            "all_numerical_validations_passed": totals["passed_models"] == len(models),
            "totals": dict(totals), "models": models,
            "audit_script_sha256": digest(Path(__file__)),
            "audit_module_sha256": digest(ROOT/"grn_memory/breaking_audit.py"),
            "archive_reader_sha256": digest(ROOT/"scripts/audit_breaking_shards.py")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--network", type=int, action="append", help="Default: require all 35 models")
    args = parser.parse_args()
    result = audit(args.input, args.source_revision, args.network)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(json.dumps(result["totals"]))
    print("Complete catalog initial-case coverage:", result["complete_catalog_initial_case_coverage"])
    print("Numerical validation of selected models:", result["all_numerical_validations_passed"])
