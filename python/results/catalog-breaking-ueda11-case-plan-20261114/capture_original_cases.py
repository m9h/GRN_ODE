"""Capture the original failed cases and verify their complete control inventory."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Repository python directory")
    parser.add_argument("--original", required=True, type=Path, help="Original report and evidence directory")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.source.resolve()
    sys.path.insert(0, str(root))
    from grn_memory.catalog_breaking import candidate_plans
    from grn_memory.breaking_audit import audit_case
    from grn_memory.scipy_breaking_recovery import prepare_inventory

    evidence = json.loads(args.evidence.read_text())
    report = evidence["original_report"]
    mid = report["biomodel_id"]
    if digest(args.original / (mid + ".json")) != evidence["original_report_sha256"]:
        raise ValueError("Original report differs")
    selected = {key for key, case in report["cases"].items() if case["status"] != "passed"}
    reference = json.loads((root / "results/catalog-repeated" / (mid + ".json")).read_text())
    plans = candidate_plans(reference)
    archives, cases, branches = {}, {}, {}

    def records(kind):
        for entry in report["evidence_archives"][kind]:
            path = args.original / entry["file"]
            if digest(path) != entry["sha256"]:
                raise ValueError("Original archive differs: " + entry["file"])
            archives[entry["file"]] = entry["sha256"]
            with gzip.open(path, "rt") as stream:
                for line in stream:
                    yield json.loads(line)

    for case in records("cases"):
        if case["case_key"] in selected:
            if case["case_key"] in cases:
                raise ValueError("Duplicate original case")
            cases[case["case_key"]] = case
    if set(cases) != selected:
        raise ValueError("Original failed-case coverage differs")
    needed = {bid for case in cases.values() for trial in case["trials"].values()
              for bid in trial["branches"].values()}
    for branch in records("branches"):
        bid = branch["record_id"]
        if bid in needed:
            if bid in branches:
                raise ValueError("Duplicate original branch")
            branches[bid] = branch
    if set(branches) != needed:
        raise ValueError("Required original branch coverage differs")
    captured = {}
    for key, case in cases.items():
        summary, _, unknown = audit_case(case, plans[key], branches, report, reference)
        if summary != report["cases"][key]:
            raise ValueError("Original case summary does not reproduce")
        captured[key] = {"case": case, "summary": summary, "unresolved_conditional_decisions": unknown}
    plan = {"purpose": __doc__, "model_id": mid,
            "source_report_sha256": evidence["original_report_sha256"], "cases": captured,
            "required_branch_count": len(branches),
            "original_failed_branches": sum(not b["passed"] for b in branches.values()),
            "selected_branches": {bid: {"specification": b["specification"], "sample_count": b["sample_count"],
                                         "original_passed": b["passed"]} for bid, b in sorted(branches.items())},
            "case_recovery_claimed": False, "conditional_search_must_be_revalidated": True}
    args.output.mkdir(parents=True, exist_ok=True)
    plan_path = args.output / "original-case-plan.json"
    if plan_path.exists():
        raise ValueError("Refusing to replace an existing case plan")
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    archive = args.output / "source-branches.jsonl.gz"
    with gzip.open(archive, "wt") as stream:
        for _, branch in sorted(branches.items()):
            stream.write(json.dumps(branch, sort_keys=True) + "\n")
    provenance = {"purpose": "Original selected records preserved after verifying all source archives and cases.",
                  "source_report_sha256": evidence["original_report_sha256"],
                  "source_fingerprint": report["fingerprint"], "verified_original_archives": archives,
                  "selected_branch_ids": sorted(branches), "selected_branch_count": len(branches),
                  "selected_archive_sha256": digest(archive), "selected_archive_bytes": archive.stat().st_size}
    (args.output / "source-branches-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    inventory, _, _, _ = prepare_inventory(args.evidence, plan_path, args.revision, archive)
    (args.output / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(json.dumps({"cases": sorted(selected), "original_case_branches": len(branches),
                      "total_required": inventory["expected_branches"],
                      "reusable_failed_branches": len(evidence["failed_branches"])}))


if __name__ == "__main__":
    main()
