"""Partition complete initial breaking cases without changing their experiments."""


def select_cases(plans, index, count):
    """Disjoint contiguous ranges retain useful shared histories within a job."""
    if count < 1 or not 0 <= index < count:
        raise ValueError("Require a positive shard count and an index in range")
    keys = sorted(plans)
    return keys[len(keys)*index//count:len(keys)*(index+1)//count]


def outcome(selected, report, *, execute_control=False, returncode=None, timed_out=False):
    """A partial selection can pass its own gate without passing the model."""
    if not selected and not execute_control:
        return {"status": "empty_shard", "selected_coverage_complete": True,
                "selected_cases_passed": 0, "model_complete": False}
    if report is None:
        return {"status": "incomplete", "selected_coverage_complete": False,
                "selected_cases_passed": 0, "model_complete": False}
    cases = report.get("cases", {})
    if set(cases)-set(selected):
        raise ValueError("Worker computed cases outside the declared shard")
    complete = (set(cases) == set(selected) and not timed_out and returncode in (0, 1)
                and report.get("status") in ("passed", "incomplete_or_failed"))
    passed = sum(c["status"] == "passed" for c in cases.values())
    controls_passed = report.get("control_comparison", {}).get("passed", False) and all(
        c["passed"] for c in report.get("encoding_control_comparisons", {}).values())
    validated = complete and passed == len(selected) and controls_passed
    return {"status": "selected_cases_passed" if validated else
                     "selected_cases_failed" if complete else "incomplete",
            "selected_coverage_complete": complete, "selected_cases_passed": passed,
            "model_complete": validated and report.get("status") == "passed"
                              and len(cases) == report["expected_cases"]}
