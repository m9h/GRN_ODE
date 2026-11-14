"""Reproduce the stopped artifact's cache failure and verify safe preparation.

Run with uv from the python directory. No trajectories are integrated and no
model or case is promoted to passed by this check.
"""

import argparse
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import audit_case, require
from grn_memory.breaking_resume import digest, prepare
from grn_memory.catalog_breaking import candidate_plans
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from scripts.collect_breaking_runs import extract


def reproduce(archive, output):
    expected_sha = "17b728dc9b438becc054ff1300dfe09fa3dc52ae237cb8551f233aada7f7a551"
    require(digest(archive) == expected_sha, "Wrong original artifact ZIP")
    require(not output.exists(), "Use a fresh output directory")
    output.mkdir(parents=True)
    source = output/"original"
    extract(archive, source)
    before = {str(p.relative_to(source)): digest(p) for p in source.rglob("*") if p.is_file()}
    manifest = json.loads((source/"shard.json").read_text())
    report = json.loads((source/"BIOMD0000000035.json").read_text())
    reference = json.loads((ROOT/"results/catalog-repeated/BIOMD0000000035.json").read_text())
    plans = {fingerprint(plan): plan for plan in candidate_plans(reference).values()}
    records = {"branches": {}, "cases": {}}
    for path in sorted((source/".evidence"/manifest["model_id"]/report["fingerprint"]).glob("*.json.gz")):
        kind, key = path.name.removesuffix(".json.gz").split("-", 1)
        with gzip.open(path, "rt") as stream:
            records[kind][key] = json.load(stream)
    failures = []
    for key, case in records["cases"].items():
        try:
            audit_case(case, plans[key], records["branches"], report, reference)
        except ValueError as error:
            failures.append({"record_id": key, "case_key": case["case_key"],
                             "saved_passed": case["passed"], "error": str(error)})
    require(len(failures) == 5 and all(f["error"] == "Trial scores do not reproduce"
                                     and f["saved_passed"] is False for f in failures),
            "Original five failed historical scores were not reproduced")
    prepared = output/"prepared"
    result = prepare(source, prepared, 32, 7, 16)
    require(all(f["case_key"] not in result["case_keys"] for f in failures),
            "An original failed aggregate belongs to the new selection")
    for relative, sha in result["copied_checkpoint_sha256"].items():
        require(digest(prepared/relative) == sha == before[relative], "Active checkpoint bytes changed")
    for relative, history in result["preserved_case_history"].items():
        require(digest(prepared/history["preserved_path"]) == history["sha256"] == before[relative],
                "Historical case bytes changed")
        require(not (prepared/relative).exists(), "Historical case was placed in the active cache")
    after = {str(p.relative_to(source)): digest(p) for p in source.rglob("*") if p.is_file()}
    require(before == after and digest(archive) == expected_sha, "Original evidence was modified")
    summary = {"network": 32, "model_id": manifest["model_id"], "shard_index": 7, "shard_count": 16,
               "source_artifact_id": 14028918797, "source_run": 43273680209,
               "source_zip_bytes": archive.stat().st_size, "source_zip_sha256": expected_sha,
               "source_manifest_sha256": digest(source/"shard.json"),
               "original_nonreproducing_case_aggregates": failures,
               "preparation": {k: result[k] for k in (
                   "case_keys", "validated_branch_checkpoints", "examined_case_checkpoints",
                   "validated_case_checkpoints", "preserved_case_checkpoints", "copied_checkpoints",
                   "preparation_source_sha256", "numerical_integrations_performed", "model_completion_claimed")},
               "prepared_manifest_sha256": digest(prepared/"resume-source.json"),
               "original_evidence_unchanged": True, "all_copied_bytes_verified": True,
               "preparation_passed": True}
    write_json(output/"verification.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reproduce(args.archive, args.output), indent=2))
