"""Recompute complete paired cases from independently checked branch evidence.

Recorded pointwise comparisons are audited, not rerun. A case uses the same two
refined engines in every arm; original and recovered cases remain separate.
"""

import math

from .catalog_paired import WINDOWS, branch_id, case_branches
from .paired_scores import classification_key, response_score


ENGINES = ("scipy_refined", "roadrunner_refined")
REQUIRED_INTEGRATIONS = ("scipy", "scipy_refined", "roadrunner", "roadrunner_refined")
COMPARISONS = ("scipy_vs_roadrunner", "scipy_refined_vs_roadrunner",
               "scipy_vs_scipy_refined", "roadrunner_vs_roadrunner_refined",
               "scipy_refined_vs_roadrunner_refined")
METADATA_KEYS = ("model_id", "model_sha256", "scipy_method", "source_report_sha256",
                 "source_fingerprint", "source_archive_sha256", "script_sha256",
                 "implementation_sha256", "integration_requests", "comparison_settings",
                 "grid", "versions")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_comparison(record, observables):
    """Reject missing species, partial horizons and inconsistent pass flags."""
    require(record["samples"] == 30001, "Comparison does not cover all 30001 samples")
    errors = record["per_observable_max_scaled_error"]
    require(set(errors) == set(observables) and record["observables"] == len(observables),
            "Comparison does not cover all original observables")
    require(all(math.isfinite(x) and x >= 0 for x in errors.values()), "Invalid comparison errors")
    require(record["max_scaled_error"] == max(errors.values()), "Inconsistent comparison maximum")
    require(record["passed"] == (record["max_scaled_error"] <= 1), "Inconsistent comparison pass flag")
    return record["passed"]


def validate_diagnostic_branch(record, report, original, observables):
    """Audit a terminal record, including the full reset schedule and all gates."""
    require(record["fingerprint"] == report["fingerprint"], "Diagnostic fingerprint differs")
    require(record["branch_id"] == original["branch_id"], "Diagnostic branch identity differs")
    for key in ("specification", "reset_trains"):
        require(record[key] == original[key], f"Diagnostic {key} differs from original")
    require(record["status"] in ("confirmed", "failed", "mismatch"), "Diagnostic is not terminal")
    integrations = record["integrations"]
    completed = []
    for label in REQUIRED_INTEGRATIONS:
        evidence = integrations.get(label, {})
        require(evidence.get("request") == report["integration_requests"][label],
                "Integration request differs from diagnostic metadata")
        if not evidence.get("completed"):
            continue
        completed.append(label)
        require(evidence["samples"] == 30001 and evidence["observables"] == len(observables),
                "Integration has incomplete observations")
        if label.startswith("scipy"):
            counts = [499] * len(original["reset_trains"])
            require(evidence["model_sha256"] == report["model_sha256"], "Integration model differs")
            require(evidence["method"] == report["scipy_method"], "Integration method differs")
            require(all(evidence[k] == evidence["request"][k] for k in ("rtol", "atol")),
                    "Actual integration tolerances differ")
            require(evidence["x64"] and evidence["absolute_time_preserved"], "Integration precision or clock differs")
            require(evidence["expected_train_reset_counts"] == evidence["train_reset_counts"] == counts,
                    "Integration reset counts differ")
            require(evidence["expected_resets"] == evidence["performed_resets"] == sum(counts),
                    "Integration total reset count differs")
            require(evidence["completed_segments"] == evidence["expected_segments"] == sum(counts)+1,
                    "Integration segments are incomplete")
            require(evidence["sample_count"] == 30001, "Integration sample grid is incomplete")
        windows = record["windows"][label]
        require(set(windows) == set(WINDOWS), "Incomplete window inventory")
        for rows in windows.values():
            require(set(rows) == set(observables), "Incomplete window observables")
            for row in rows.values():
                values = [row[k] for k in ("minimum", "mean", "maximum")]
                require(all(math.isfinite(x) for x in values), "Nonfinite window summary")
                # Summation roundoff can put a constant-window mean just outside
                # its endpoint range. Allow only machine-scale roundoff here.
                slack = 1e-14 * max(1., *map(abs, values))
                require(values[0]-slack <= values[1] <= values[2]+slack,
                        "Window mean lies outside recorded range")
    comparisons = record["comparisons"]
    expected_pairs = {k for k in COMPARISONS if all(e in completed for e in k.split("_vs_"))}
    require(set(comparisons) == expected_pairs, "Missing or unexpected comparison gates")
    passes = [validate_comparison(c, observables) for c in comparisons.values()]
    status = ("failed" if len(completed) != len(REQUIRED_INTEGRATIONS) else
              "confirmed" if all(passes) else "mismatch")
    require(record["status"] == status, "Diagnostic status contradicts its evidence")
    return status == "confirmed"


def recover_cases(plans, original_cases, records):
    """Score all originally failed cases, with explicit missing/failed arms."""
    result = {}
    for key, plan in plans.items():
        if original_cases[key]["status"] == "passed":
            continue
        ids = {role: branch_id(spec) for role, spec in case_branches(plan).items()}
        missing = {role: bid for role, bid in ids.items() if bid not in records}
        unconfirmed = {role: records[bid]["status"] for role, bid in ids.items()
                       if bid in records and records[bid]["status"] != "confirmed"}
        case = {**plan, "branches": ids, "original_status": original_cases[key]["status"],
                "status": "incomplete", "missing_branches": missing,
                "unconfirmed_branches": unconfirmed}
        if not missing and not unconfirmed:
            cells = {role: records[bid] for role, bid in ids.items()}
            scores = {e: {r: response_score(cells, e, r) for r in plan["responses"]} for e in ENGINES}
            disagree = [r for r in plan["responses"] if
                        classification_key(scores[ENGINES[0]][r]) != classification_key(scores[ENGINES[1]][r])]
            paper_disagree = {r: [k for k,v in scores[ENGINES[0]][r]["paper_like"].items()
                                 if v != scores[ENGINES[1]][r]["paper_like"][k]] for r in plan["responses"]}
            case.update(scores=scores, controlled_classification_disagreements=disagree,
                        paper_like_disagreements={r: v for r,v in paper_disagree.items() if v},
                        status="mismatch" if disagree else "passed")
        elif not missing:
            case["status"] = "failed"
        result[key] = case
    return result
