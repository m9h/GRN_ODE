"""Index complete-model breaking audits without treating branch diagnostics as recovery."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Repository python directory")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.source.resolve()
    sys.path.insert(0, str(root))
    from grn_memory.catalog_breaking import candidate_plans

    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    catalog = json.loads((root / "models/catalog.json").read_text())["models"]
    rows = {}
    for model in catalog:
        path = root / "results/catalog-repeated" / (model["biomodel_id"] + ".json")
        reference = json.loads(path.read_text())
        if reference["status"] != "passed":
            raise ValueError("Candidate calibration has not passed")
        rows[model["network"]] = {**model, "name": reference.get("name", model["biomodel_id"]),
                                  "expected_cases": len(candidate_plans(reference)),
                                  "calibration_sha256": digest(path), "complete_model_audits": []}
    if set(rows) != set(range(1, 36)):
        raise ValueError("Original 35-model catalog is incomplete")
    paths = subprocess.check_output(["git", "ls-files", "python/results/catalog-breaking*/audit.json"],
                                    cwd=root.parent, text=True).splitlines()
    excluded = []
    for name in paths:
        path = root.parent / name
        data = json.loads(path.read_text())
        if "models" in data:
            entries = data["models"]
        elif data.get("complete_case_coverage") is True and "network" in data:
            entries = [data]
        else:
            excluded.append({"file": name, "sha256": digest(path),
                             "reason": "No complete-model initial-case coverage claim; not counted as model recovery."})
            continue
        for entry in entries:
            row = rows[entry["network"]]
            if (entry["biomodel_id"] != row["biomodel_id"] or entry["cases"] != row["expected_cases"]
                    or entry.get("complete_initial_case_coverage", entry.get("complete_case_coverage")) is not True):
                raise ValueError("Complete-model inventory differs: " + name)
            conditional = entry.get("complete_conditional_search",
                                    not entry.get("unresolved_conditional_decisions", []))
            passed = entry["all_numerical_validations_passed"]
            if type(passed) is not bool or (passed and (not conditional or entry["passed_cases"] != row["expected_cases"])):
                raise ValueError("Passing model audit contradicts case coverage: " + name)
            row["complete_model_audits"].append({"file": name, "sha256": digest(path),
                                                 "passed_cases": entry["passed_cases"],
                                                 "complete_conditional_search": conditional,
                                                 "all_numerical_validations_passed": passed})
    for row in rows.values():
        row["has_terminal_complete_initial_inventory"] = bool(row["complete_model_audits"])
        row["has_passing_complete_model_audit"] = any(a["all_numerical_validations_passed"]
                                                     for a in row["complete_model_audits"])
        row["no_eligible_cases"] = row["expected_cases"] == 0
        row["status"] = ("validated" if row["has_passing_complete_model_audit"] else
                         "terminal_with_failures" if row["has_terminal_complete_initial_inventory"] else "unfinished")
    result = {"purpose": __doc__, "scope": "Existing complete-model breaking audits only; no numerical rerun.",
              "selection_policy": "Preserve every indexed complete-model audit, including failed originals. A model passes only when a whole-model audit passes; never combine favorable individual branches or case counts.",
              "catalog_sha256": digest(root / "models/catalog.json"), "models": list(rows.values()),
              "excluded_diagnostics": excluded,
              "totals": {"catalog_models": len(rows),
                         "terminal_models": sum(r["has_terminal_complete_initial_inventory"] for r in rows.values()),
                         "validated_models": sum(r["has_passing_complete_model_audit"] for r in rows.values()),
                         "zero_candidate_models": [n for n, r in rows.items() if r["no_eligible_cases"]],
                         "unfinished_networks": [n for n, r in rows.items() if r["status"] == "unfinished"],
                         "terminal_networks_with_failures": [n for n, r in rows.items() if r["status"] == "terminal_with_failures"]},
              "goal_completion_claimed": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["totals"], indent=2))


if __name__ == "__main__":
    main()
