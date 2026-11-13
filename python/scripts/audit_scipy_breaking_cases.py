"""Audit complete Radau/RoadRunner breaking cases from every saved observation.

Original, primary and refined conditional paths remain distinct. Recovery
requires every original and possible control, a passing full untreated baseline,
and matching controlled classifications across both implementations and requests.
No historical native passes are added to these selected-case results.
"""

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from grn_memory.breaking_audit import require
from grn_memory.breaking_scores import classification_key, remaining_responses, trial_scores
from grn_memory.catalog_breaking import next_breakers, trial_windows
from grn_memory.catalog_jax import source_hashes
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_repeated import summarize
from grn_memory.catalog_runner import fingerprint
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain
from grn_memory.scipy_breaking_recovery import (ACCEPTANCE, LABELS, common_eligibility, digest,
                                               potential_trials, prepare_inventory, trial_specifications)
from scripts.audit_scipy_breaking import PACKAGES, SOURCES, trajectory
from scripts.diagnose_scipy_breaking_controls import EXTRA_SOURCES


META_KEYS = ("model_id", "model_sha256", "inventory_sha256", "requests", "acceptance",
             "implementation_sha256", "versions", "sample_grid_sha256", "reused_report_sha256",
             "reused_audit_sha256", "case_recovery_claimed", "full_model_coverage_claimed")
PRIMARY = ("roadrunner", "scipy")
REFINED = ("roadrunner_refined", "scipy_refined")


def read(path):
    return json.loads(Path(path).read_text())


def replay_case(plan, reference, config, branches, engines):
    """Recompute the source algorithm's exact path for one declared solver pair."""
    source = common_eligibility(plan)
    trials, used, unknown = {}, set(), []

    def evaluate(name, breakers, responses):
        k = len(breakers)
        roles = {role: fingerprint(spec) for role, spec in
                 trial_specifications(plan, breakers, reference, config).items()}
        require(set(roles.values()) <= branches.keys(), "Required case control is missing")
        used.update(roles.values())
        cells = {role: branches[bid] for role, bid in roles.items()}
        available = [label for label in LABELS if all(label in b["windows"] for b in cells.values())]
        scores = {label: trial_scores(cells, label, responses, source, k) for label in available}
        disagreements = [r for r in responses if len(available) == len(LABELS)
                         and len({fingerprint(classification_key(scores[e][r])) for e in LABELS}) != 1]
        record = {"trial": k, "breakers": breakers, "responses": responses, "branches": roles,
                  "scores": scores, "missing_score_engines": sorted(set(LABELS) - set(available)),
                  "controlled_classification_disagreements": disagreements,
                  "passed": len(available) == len(LABELS) and not disagreements
                            and all(b["status"] == "confirmed" for b in cells.values())}
        trials[name] = record
        if not set(engines) <= scores.keys():
            unknown.append(name)
            return None
        remaining = remaining_responses(scores, responses, engines)
        record["remaining_responses"] = remaining
        record["raw_reversal_disagreements"] = [r for r in responses if
            scores[engines[0]][r]["matlab"]["break_direction"] != scores[engines[1]][r]["matlab"]["break_direction"]]
        return remaining

    remaining = evaluate("first", [plan["breaker"]], list(plan["responses"]))
    if remaining:
        remaining = evaluate("second", [plan["breaker"]] * 2, remaining)
        if remaining:
            for third, responses in next_breakers(plan, remaining, reference).items():
                evaluate("third__" + third, [plan["breaker"], plan["breaker"], third], responses)
    return {"engines": list(engines), "trials": trials, "used_branches": sorted(used),
            "unresolved_conditional_decisions": unknown, "complete_conditional_search": not unknown,
            "passed": not unknown and all(t["passed"] for t in trials.values())}


def evaluate_case(plan, reference, config, branches, baseline_passed):
    primary = replay_case(plan, reference, config, branches, PRIMARY)
    refined = replay_case(plan, reference, config, branches, REFINED)
    potential = {fingerprint(spec) for breakers in potential_trials(plan, reference).values()
                 for spec in trial_specifications(plan, breakers, reference, config).values()}
    require(potential <= branches.keys(), "An original or possible conditional control is missing")
    all_controls = all(branches[bid]["status"] == "confirmed" for bid in potential)
    path = lambda row: {k: {f: t[f] for f in ("breakers", "responses")} for k, t in row["trials"].items()}
    return {"primary_search": primary, "refined_search": refined,
            "conditional_paths_agree": path(primary) == path(refined),
            "all_original_and_potential_controls_confirmed": all_controls,
            "required_potential_branches": sorted(potential), "baseline_passed": baseline_passed,
            "passed": baseline_passed and all_controls and primary["passed"] and refined["passed"]}


def check_outcome(outcome, label, request, times, names, trains, model_sha):
    require(outcome["request"] == request, "Recorded request differs")
    if outcome.get("completed") is not True:
        require(outcome.get("completed") is False and isinstance(outcome.get("error"), str)
                and bool(outcome["error"]), "Incomplete integration needs explicit failure evidence")
        return False
    require(outcome["sample_count"] == len(times) and outcome["observables"] == names,
            "Complete integration observation inventory differs")
    if label.startswith("scipy"):
        resets = sorted({float(v) for train in trains if train.values for v in train.times()})
        counts = [len(t.indices()) if t.values else 0 for t in trains]
        require(outcome["backend"] == "scipy.solve_ivp" and outcome["rhs_backend"] == "Jaxkineticmodel"
                and outcome["jacobian"] == "jax.jacfwd"
                and outcome["model_sha256"] == model_sha and outcome["method"] == "Radau"
                and outcome["rtol"] == request["rtol"] and outcome["atol"] == request["atol"]
                and outcome["x64"] is True and outcome["absolute_time_preserved"] is True,
                "Radau arithmetic, model or absolute clock differs")
        require(outcome["expected_resets"] == outcome["performed_resets"] == len(resets)
                and outcome["expected_train_reset_counts"] == outcome["train_reset_counts"] == counts
                and outcome["expected_segments"] == outcome["completed_segments"] == len(resets) + 1
                and outcome["last_interval"] == [resets[-1] if resets else 0., float(times[-1])],
                "Incomplete Radau reset schedule or final interval")
    return True


def summary_discrepancy(old, new):
    """Flag contradictory window evidence without claiming cross-run array agreement."""
    worst = {"max_scaled_error": 0.}
    for old_label, old_windows in old["windows"].items():
        for label, windows in new["windows"].items():
            for window, values in old_windows.items():
                for observable, stats in values.items():
                    for statistic in ("minimum", "mean", "maximum"):
                        a, b = stats[statistic], windows[window][observable][statistic]
                        error = abs(a - b) / (ACCEPTANCE["atol"] + ACCEPTANCE["rtol"] * max(abs(a), abs(b)))
                        if error > worst["max_scaled_error"]:
                            worst = {"max_scaled_error": error, "original_engine": old_label, "new_engine": label,
                                     "window": window, "observable": observable, "statistic": statistic}
    return worst


def audit(directory):
    directory = Path(directory)
    report_path = directory / "report.json"
    report_sha = digest(report_path)
    report = read(report_path)
    require(report["status"] == "completed", "Control computation is still running")
    require(fingerprint({k: report[k] for k in META_KEYS}) == report["fingerprint"], "Producer fingerprint differs")
    require(report["case_recovery_claimed"] is False and report["full_model_coverage_claimed"] is False,
            "Producer cannot claim case or model recovery")
    saved_inventory = read(directory / "inventory.json")
    inventory, _, info, grid = prepare_inventory(directory / "source-evidence.json", directory / "original-case-plan.json",
                                                 saved_inventory["source_revision"], directory / "source-branches.jsonl.gz")
    require(saved_inventory == inventory and fingerprint(inventory) == report["inventory_sha256"],
            "Complete source control inventory differs")
    require(report["model_id"] == inventory["model_id"] and report["model_sha256"] == info["sha256"]
            and report["sample_grid_sha256"] == hashlib.sha256(grid.tobytes()).hexdigest()
            and report["acceptance"] == ACCEPTANCE, "Model, grid or acceptance differs")
    sources = source_hashes()
    sources.update({n: digest(ROOT / n) for n in (*SOURCES, *EXTRA_SOURCES)})
    require(sources == report["implementation_sha256"], "Producer sources differ")
    require(set(report["versions"]) == PACKAGES and all(isinstance(v, str) and v for v in report["versions"].values()),
            "Producer package inventory differs")
    source = read(directory / "reused-report.json")
    source_audit = read(directory / "reused-audit.json")
    require(digest(directory / "reused-report.json") == report["reused_report_sha256"]
            and fingerprint(source_audit) == report["reused_audit_sha256"]
            and source_audit["report_sha256"] == report["reused_report_sha256"]
            and source_audit["all_selected_branches_confirmed"]
            and source_audit["complete_captured_failure_coverage"], "Imported failed-branch provenance differs")
    require(source["requests"] == report["requests"] and source["versions"] == report["versions"]
            and source["model_id"] == inventory["model_id"]
            and source["source_report_sha256"] == inventory["source_report_sha256"], "Imported settings or model differ")
    requests = report["requests"]
    require(set(requests) == set(LABELS), "All four requests are required")
    from decimal import Decimal
    for base, factor in (("roadrunner", 2), ("scipy", 10)):
        for label in (base, base + "_refined"):
            require(set(requests[label]) == ({"rtol", "atol", "method"} if base == "scipy" else {"rtol", "atol"}),
                    "Integration setting inventory differs")
            require(all(np.isfinite(requests[label][k]) and requests[label][k] > 0 for k in ("rtol", "atol")),
                    "Invalid integration tolerance")
            if base == "scipy":
                require(requests[label]["method"] == "Radau", "Independent method differs")
        require(all(requests[base + "_refined"][k] == float(Decimal(str(requests[base][k])) / factor)
                    and requests[base + "_refined"][k] < requests[base][k] for k in ("rtol", "atol")),
                "Integration requests are not the specified refinements")
    require(report["expected_branches"] == len(report["branches"]) == inventory["expected_branches"]
            and {e["record_id"] for e in report["branches"]} == set(inventory["branches"])
            and report["selected_case_keys"] == sorted(inventory["cases"])
            and report["expected_model_cases"] == inventory["expected_model_cases"]
            and report["full_untreated_control"] == inventory["full_untreated_control"],
            "Complete branch, case or baseline inventory differs")
    reused = {b["record_id"]: b for b in source["branches"]}
    imported_arrays = {b["record_id"]: b for b in source_audit["branches"]}
    branches, records = {}, []
    for entry in report["branches"]:
        bid = entry["record_id"]
        require(entry["file"] == bid + ".json", "Unexpected branch record path")
        record_path = directory / entry["file"]
        require(digest(record_path) == entry["sha256"], "Branch record hash differs")
        record = read(record_path)
        spec = inventory["branches"][bid]
        require(record["record_id"] == bid and record["fingerprint"] == report["fingerprint"]
                and record["specification"] == spec and record["case_recovery_claimed"] is False,
                "Branch identity or scope differs")
        require(all(requests["roadrunner"][k] < spec["integration_settings"]["roadrunner"][k]
                    for k in ("rtol", "atol")), "Native request does not refine the original")
        require(set(record["integrations"]) == set(LABELS), "Integration outcomes are incomplete")
        times = grid[grid <= spec["stop"]]
        trains = [ResetTrain(**t) for t in spec["reset_trains"]]
        traces = {}
        for label in LABELS:
            if check_outcome(record["integrations"][label], label, requests[label], times,
                             info["observables"], trains, info["sha256"]):
                require(label in record["traces"], "Completed integration has no trajectory")
                traces[label] = trajectory(directory, bid, label, record["traces"][label], times, info["observables"])
        require(set(traces) == set(record["traces"]), "Unexpected trajectory outside completed integrations")
        comparisons = {a + "_vs_" + b: comparison(traces[a], traces[b], **ACCEPTANCE)
                       for i, a in enumerate(LABELS) for b in LABELS[i+1:] if a in traces and b in traces}
        require(record["comparisons"] == comparisons, "Saved comparisons do not reproduce from arrays")
        status = ("incomplete" if len(comparisons) != 6 else
                  "confirmed" if all(c["passed"] for c in comparisons.values()) else "mismatch")
        require(record["status"] == entry["status"] == status, "Branch status contradicts arrays")
        if bid in reused:
            require(record.get("reused_from") == {"report_sha256": report["reused_report_sha256"],
                                                   "record_sha256": reused[bid]["sha256"]},
                    "Imported record provenance differs")
            require(record["traces"] == imported_arrays[bid]["traces"], "Imported trajectory hashes differ")
        else:
            require("reused_from" not in record, "Unexpected imported branch")
        windows = {label: summarize(trace, trial_windows(round((spec["stop"] - 1010) / 400)))
                   for label, trace in traces.items()}
        branches[bid] = {"status": status, "windows": windows}
        records.append({"record_id": bid, "status": status, "record_sha256": entry["sha256"],
                        "samples": len(times), "traces": record["traces"], "comparisons": comparisons})
    require(report["confirmed_branches"] == sum(b["status"] == "confirmed" for b in branches.values()),
            "Confirmed branch count differs")
    original = read(directory / "source-evidence.json")["original_report"]
    reference = read(ROOT / "results/catalog-repeated" / (inventory["model_id"] + ".json"))
    baseline_passed = branches[inventory["full_untreated_control"]]["status"] == "confirmed"
    cases = {key: evaluate_case(value["original_plan"], reference, original["configuration"], branches, baseline_passed)
             for key, value in inventory["cases"].items()}
    captured_cases = read(directory / "original-case-plan.json")["cases"]
    for key, result in cases.items():
        original_path = {name: {field: trial[field] for field in ("breakers", "responses")}
                         for name, trial in captured_cases[key]["case"]["trials"].items()}
        result["original_path"] = original_path
        for label in ("primary", "refined"):
            new_path = {name: {field: trial[field] for field in ("breakers", "responses")}
                        for name, trial in result[label + "_search"]["trials"].items()}
            result[label + "_matches_original_path"] = new_path == original_path
    import gzip
    contradictions = {}
    with gzip.open(directory / "source-branches.jsonl.gz", "rt") as stream:
        for line in stream:
            old = json.loads(line)
            if old["passed"] and branches[old["record_id"]]["status"] == "confirmed":
                difference = summary_discrepancy(old, branches[old["record_id"]])
                if difference["max_scaled_error"] > 1:
                    contradictions[old["record_id"]] = difference
    require(digest(report_path) == report_sha, "Producer report changed during audit")
    return {"purpose": __doc__, "model_id": inventory["model_id"], "report_sha256": report_sha,
            "complete_selected_control_inventory": True, "baseline_passed": baseline_passed,
            "branches": records, "cases": cases, "selected_cases": len(cases),
            "recovered_selected_cases": sum(c["passed"] for c in cases.values()),
            "original_passing_cases_included": False, "full_model_coverage_claimed": False,
            "original_passing_branches_requiring_revalidation": contradictions,
            "cross_run_native_array_agreement_claimed": False,
            "audit_script_sha256": digest(Path(__file__)),
            "array_reader_sha256": digest(ROOT / "scripts/audit_scipy_breaking.py")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with (args.input / ".diagnostic.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        result = audit(args.input)
    write_json(args.output, result)
    print(json.dumps({k: result[k] for k in ("selected_cases", "recovered_selected_cases", "baseline_passed")}))
