"""Recompute complete conditional searches from archived breaking evidence."""

from collections import Counter
from dataclasses import asdict
import math

from .breaking_scores import classification_key, remaining_responses, trial_scores
from .catalog_breaking import branch_trains, next_breakers, trial_windows
from .catalog_runner import fingerprint


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit_comparison(record, samples, observables):
    require(record["samples"] == samples, "Comparison observation horizon is incomplete")
    errors = record["per_observable_max_scaled_error"]
    require(set(errors) == set(observables) and record["observables"] == len(observables),
            "Comparison observable inventory differs")
    require(all(math.isfinite(x) and x >= 0 for x in errors.values()), "Invalid comparison errors")
    require(record["max_scaled_error"] == max(errors.values()), "Comparison maximum is inconsistent")
    require(record["passed"] == (record["max_scaled_error"] <= 1), "Comparison pass flag is inconsistent")
    return record["passed"]


def audit_branch(branch, report, observables):
    spec = branch["specification"]
    require(branch["record_id"] == fingerprint(spec), "Branch identifier differs from specification")
    require(branch["fingerprint"] == report["fingerprint"], "Branch model fingerprint differs")
    stop = spec["stop"]
    require(stop in (1410., 1810., 2210.), "Unexpected branch horizon")
    samples = round(stop/.01)+1
    require(branch["sample_count"] == samples, "Branch observation horizon is incomplete")
    passed = False
    if "comparison" in branch:
        passed = audit_comparison(branch["comparison"], samples, observables)
    if "windows" in branch:
        require(set(branch["windows"]) == set(report["engines"]), "Window engine inventory differs")
        for windows in branch["windows"].values():
            require(set(windows) == set(trial_windows(round((stop-1010)/400))), "Window horizon differs")
            for rows in windows.values():
                require(set(rows) == set(observables), "Window observable inventory differs")
                for row in rows.values():
                    values = [row[k] for k in ("minimum", "mean", "maximum")]
                    require(all(math.isfinite(x) for x in values), "Nonfinite window summary")
                    slack = 1e-14*max(1., *map(abs, values))
                    require(values[0]-slack <= values[1] <= values[2]+slack, "Window mean is outside its range")
    else:
        passed = False
    if "jitcdde" in report["engines"]:
        refinement = branch.get("refinement", {})
        if set(refinement) != {"versus_method_of_steps", "versus_original_step"}:
            passed = False
        for comparison in refinement.values():
            passed &= audit_comparison(comparison, samples, observables)
    passed &= "error" not in branch
    require(branch["passed"] == passed, "Branch outcome contradicts its evidence")
    fallbacks = report["configuration"]["integration_error_fallbacks"]
    for engine, attempts in branch["solver_attempts"].items():
        allowed = [spec["integration_settings"][engine]]
        if engine in fallbacks and fallbacks[engine] != allowed[0]:
            allowed.append(fallbacks[engine])
        require(0 < len(attempts) <= len(allowed), "Unexpected solver retry count")
        for index, attempt in enumerate(attempts):
            require(attempt["settings"] == allowed[index], "Undeclared solver request")
            if index < len(attempts)-1:
                require(attempt["status"] == "error", "Retry followed a completed trajectory")
        if attempts[-1]["status"] == "completed":
            require(branch["integration_settings_used"][engine] == attempts[-1]["settings"],
                    "Recorded used solver settings differ")
    if passed:
        require(set(branch["solver_attempts"]) == set(report["engines"]), "Missing engine attempt")
        require(all(a[-1]["status"] == "completed" for a in branch["solver_attempts"].values()),
                "Passed branch has incomplete integration")
    return passed


def audit_case(case, plan, branches, report, reference):
    require(all(case[k] == plan[k] for k in ("ucs", "breaker", "responses")), "Case plan differs")
    require(case["record_id"] == fingerprint(plan) and case["fingerprint"] == report["fingerprint"],
            "Case identity differs")
    config, engines = report["configuration"], report["engines"]
    settings = {**config["integration_settings"], **config["case_integration_overrides"].get(plan["ucs"], {})}
    expected_trials, used, unresolved = set(), set(), []

    def trial(name, breakers, responses):
        expected_trials.add(name)
        require(name in case["trials"], "A required conditional trial is missing")
        record = case["trials"][name]
        k = len(breakers)
        require(record["trial"] == k and record["breakers"] == breakers and record["responses"] == responses,
                "Conditional trial specification differs")
        expected = {}
        for base, history, breaking in (("none",False,False), ("history",True,False),
                                       ("breaker",False,True), ("history_breaker",True,True)):
            for cue in (False, True):
                spec = {"reset_trains": [asdict(t) for t in branch_trains(
                    plan["ucs"], breakers, history, breaking, cue, reference)],
                    "stop": 1010.+400*k, "integration_settings": settings}
                expected[base+("_cue" if cue else "_sham")] = fingerprint(spec)
        require(record["branches"] == expected, "Trial controls, reset schedule or prior rechallenges differ")
        require(set(expected.values()) <= branches.keys(), "Trial branch evidence is missing")
        used.update(expected.values())
        cells = {role: branches[bid] for role,bid in expected.items()}
        if not all("windows" in b for b in cells.values()):
            require(not record["passed"] and "scores" not in record and "remaining_responses" not in record,
                    "Incomplete trajectories were used to score a trial")
            unresolved.append(name)
            return None
        scores = {e: trial_scores(cells,e,responses,plan["responses"],k) for e in engines}
        require(record["scores"] == scores, "Trial scores do not reproduce")
        disagree = [r for r in responses if classification_key(scores[engines[0]][r]) !=
                    classification_key(scores[engines[1]][r])]
        require(record["controlled_classification_disagreements"] == disagree, "Controlled labels differ")
        raw_fields = ("eligible", "resistance", "sensitization", "last_code", "break_direction")
        raw = [r for r in responses if any(scores[engines[0]][r]["matlab"][f] !=
                                          scores[engines[1]][r]["matlab"][f] for f in raw_fields)]
        require(record["raw_matlab_disagreements"] == raw, "Raw MATLAB label disagreements differ")
        remaining = remaining_responses(scores,responses,engines)
        require(record["remaining_responses"] == remaining, "Conditional continuation differs")
        require(record["passed"] == (all(b["passed"] for b in cells.values()) and not disagree),
                "Trial pass flag differs")
        return remaining

    remaining = trial("first", [plan["breaker"]], list(plan["responses"]))
    if remaining:
        remaining = trial("second", [plan["breaker"]]*2, remaining)
        if remaining:
            thirds = next_breakers(plan,remaining,reference)
            require(case["expected_third_trials"] == thirds, "Third-breaker inventory differs")
            no_third = [r for r in remaining if not any(r in values for values in thirds.values())]
            require(case["responses_without_available_third_breaker"] == no_third,
                    "Unavailable third-breaker responses differ")
            for third,responses in thirds.items():
                trial("third__"+third, [plan["breaker"],plan["breaker"],third], responses)
    require(set(case["trials"]) == expected_trials, "Unexpected or missing conditional trials")
    require(case["passed"] == all(t["passed"] for t in case["trials"].values()), "Case outcome differs")
    categories = Counter(s["category"] for t in case["trials"].values()
                         for s in t.get("scores",{}).get(engines[0],{}).values())
    summary = {"record_id": case["record_id"], "status": "passed" if case["passed"] else "mismatch",
               "initial_response_assessments": len(plan["responses"]), "evaluated_trials": len(case["trials"]),
               "evaluated_response_trials": sum(len(t["responses"]) for t in case["trials"].values()),
               "controlled_categories": dict(categories),
               "raw_disagreeing_response_trials": sum(len(t.get("raw_matlab_disagreements",[])) for t in case["trials"].values())}
    return summary, used, unresolved
