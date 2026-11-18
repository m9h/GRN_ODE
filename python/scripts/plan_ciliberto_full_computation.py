"""Partition the fixed full inventory without dispatching or integrating."""

import argparse
import hashlib
import json
from pathlib import Path


def make_plan(inv, inventory_sha256):
    failed = {r["record_id"] for r in inv["original_failed_occurrences"]}
    reused = set(inv["reusable_verified_branches"])
    remaining = set(inv["remaining_branch_ids"])
    if (inv["network"] != 28 or inv["model_id"] != "BIOMD0000000697"
            or len(inv["cases"]) != 74 or len(inv["branches"]) != 7334
            or len(failed) != 270 or len(reused) != 215 or len(failed & reused) != 10
            or len(inv["remaining_branch_ids"]) != len(remaining)
            or reused & remaining or reused | remaining != set(inv["branches"])
            or inv["new_case_recovery_claimed"] or inv["full_model_coverage_claimed"]):
        raise ValueError("Complete fixed Ciliberto inventory differs")
    first = sorted(failed - reused)
    later = sorted(remaining - set(first))
    if len(first) != 260 or len(later) != 6859 or set(first) | set(later) != remaining:
        raise ValueError("Remaining original failures or controls differ")
    return {"schema_version": 1, "network": 28, "model_id": inv["model_id"],
            "inventory_sha256": inventory_sha256,
            "stage_1": {"purpose": "Diagnose every original failed branch without a previously verified full-array result",
                        "branches": first, "expected_branches": 260, "integrations": 1040,
                        "partitions": [{"index": i, "branch_ids": first[i::32]} for i in range(32)]},
            "stage_2": {"purpose": "Complete every remaining matched control and potential continuation before the full 74-case audit",
                        "branches": later, "expected_branches": 6859, "integrations": 27436},
            "all_remaining_branches": 7119, "all_remaining_integrations": 28476,
            "full_case_audit_required": True, "workflow_dispatched": False,
            "numerical_integrations_performed": 0, "case_recovery_claimed": False,
            "full_model_coverage_claimed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = args.inventory.read_bytes()
    plan = make_plan(json.loads(data), hashlib.sha256(data).hexdigest())
    with args.output.open("x") as stream:
        json.dump(plan, stream, indent=2, allow_nan=False)
        stream.write("\n")
