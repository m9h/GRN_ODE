"""Audit and diagnose every failed branch in the four original Marhl partitions.

Each partition keeps its own evidence, including a shared failed control that
appears twice. This is a branch diagnostic; full case recovery requires the
complete control inventory and a fresh conditional-search audit.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_memory import write_json
from scripts.audit_breaking_shards import audit, digest
from scripts.diagnose_breaking_refinement import capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    source = ROOT/"results/catalog-breaking-linux-30"
    directories = [source/f"shard-{i}" for i in range(4)]
    original = audit(directories, 30)
    require(original["complete_case_coverage"] and original["cases"] == 38
            and original["passed_cases"] == 26 and not original["all_numerical_validations_passed"]
            and not original["unresolved_conditional_decisions"], "Original model inventory differs")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    items, distinct = [], set()
    for index, directory in enumerate(directories):
        report_path = directory/"BIOMD0000000039.json"
        evidence = capture(report_path)
        ids = sorted(b["record_id"] for b in evidence["failed_branches"])
        distinct.update(ids)
        evidence_path = output/f"source-partition-{index}.json"
        if evidence_path.exists():
            require(json.loads(evidence_path.read_text()) == evidence, "Existing source evidence differs")
        else:
            write_json(evidence_path, evidence)
        items.append({"shard_index": index, "source_report_sha256": digest(report_path),
                      "source_manifest_sha256": digest(directory/"shard.json"),
                      "source_evidence_file": evidence_path.name,
                      "source_evidence_sha256": digest(evidence_path),
                      "failed_branch_ids": ids,
                      "failed_case_keys": sorted(k for k, v in evidence["original_report"]["cases"].items()
                                                 if v["status"] != "passed")})
    require(sum(len(i["failed_branch_ids"]) for i in items) == 30 and len(distinct) == 29
            and sum(len(i["failed_case_keys"]) for i in items) == 12,
            "Complete original failure inventory differs")
    plan = {"purpose": __doc__, "network": 30, "model_id": "BIOMD0000000039",
            "source_producer_revision": "2e7327b0d273f4b33bdd8aa37601c1a497854a2a",
            "source_audit_sha256": digest(source/"audit.json"),
            "partitions": items, "expected_cases": 38, "original_passed_cases": 26,
            "failed_case_count": 12, "failed_branch_records": 30,
            "distinct_failed_branch_specifications": 29, "expected_integrations": 120,
            "expected_pairwise_comparisons": 180,
            "requests": {"roadrunner": {"rtol": 1e-14, "atol": 1e-16},
                         "roadrunner_refined": {"rtol": 5e-15, "atol": 5e-17},
                         "scipy": {"method": "Radau", "rtol": 1e-11, "atol": 1e-13},
                         "scipy_refined": {"method": "Radau", "rtol": 1e-12, "atol": 1e-14}},
            "acceptance": {"rtol": 2e-5, "atol": 1e-7},
            "case_recovery_claimed": False, "full_model_validation_claimed": False}
    plan_path = output/"plan.json"
    if plan_path.exists():
        require(json.loads(plan_path.read_text()) == plan, "Existing diagnostic plan differs")
    else:
        write_json(plan_path, plan)
    print(json.dumps({k: plan[k] for k in ("failed_case_count", "failed_branch_records",
                                          "distinct_failed_branch_specifications", "expected_integrations")}), flush=True)
    if args.prepare_only:
        return
    for item in items:
        index = item["shard_index"]
        destination = output/f"shard-{index}"
        command = [sys.executable, "-u", str(ROOT/"scripts/diagnose_scipy_breaking.py"),
                   "--evidence", str(output/item["source_evidence_file"]),
                   "--output", str(destination), "--reference-rtol", "1e-14", "--reference-atol", "1e-16",
                   "--rtol", "1e-11", "--atol", "1e-13", "--resume"]
        subprocess.run(command, cwd=ROOT, check=True)
        subprocess.run([sys.executable, str(ROOT/"scripts/audit_scipy_breaking.py"),
                        "--input", str(destination), "--output", str(destination/"audit.json")],
                       cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
