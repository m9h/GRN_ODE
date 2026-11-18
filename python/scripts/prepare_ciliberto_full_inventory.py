"""Verify the complete published Ciliberto search and inventory all failed cases.

No ODE integration is performed. Potential controls absent from the original
conditional paths are generated explicitly, never described as saved results.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_breaking import candidate_plans
from grn_memory.catalog_runner import fingerprint
from grn_memory.scipy_breaking_recovery import common_eligibility, potential_trials, trial_specifications
from scripts.audit_breaking_shards import audit, read_archives
from scripts.audit_scipy_breaking_cases import audit as audit_recovery
from scripts.diagnose_breaking_refinement import capture

MODEL = "BIOMD0000000697"
SOURCE = ROOT / "results/catalog-breaking-linux-28"


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def portable(result):
    result = json.loads(json.dumps(result))
    for part in result["partitions"]:
        part.pop("directory", None)
    return result


def extract_verified(archive, output):
    manifest = read(SOURCE / "download.json")
    require(digest(archive) == manifest["sha256"] and archive.stat().st_size == manifest["bytes"],
            "Published original archive checksum or size differs")
    require(not output.exists(), "Use a new extraction directory")
    output.mkdir(parents=True)
    observed = set()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            name = member.name
            pure = PurePosixPath(name)
            require(not pure.is_absolute() and ".." not in pure.parts, "Unsafe archive path")
            if member.isdir():
                continue
            require(member.isfile() and name in manifest["members"] and name not in observed,
                    "Unexpected, duplicate or nonregular archive member")
            expected = manifest["members"][name]
            require(member.size == expected["bytes"], "Member size differs")
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
            require(digest(target) == expected["sha256"], "Archive member checksum differs")
            observed.add(name)
    require(observed == set(manifest["members"]), "Incomplete archive member inventory")
    provenance = read(SOURCE / "source-artifacts.json")
    for part in provenance["partitions"]:
        relative = Path("shard-" + str(part["shard_index"]))
        for name, sha in part["copied_metadata_sha256"].items():
            src = SOURCE / relative / name
            require(digest(src) == sha, "Tracked original metadata differs")
            dst = output / "catalog-breaking-linux-28" / relative / name
            require(not dst.exists(), "Archive unexpectedly includes tracked metadata")
            shutil.copyfile(src, dst)
    return {"archive_sha256": manifest["sha256"], "archive_bytes": manifest["bytes"],
            "verified_members": len(observed), "metadata_partitions": len(provenance["partitions"])}


def build_inventory(plans, summaries, reference, config):
    selected = sorted(key for key, row in summaries.items() if row["status"] != "passed")
    specs, cases = {}, {}
    for key in selected:
        plan = plans[key]
        eligible = common_eligibility(plan)
        trials = {}
        for name, breakers in potential_trials(plan, reference).items():
            roles = {}
            for role, spec in trial_specifications(plan, breakers, reference, config).items():
                bid = fingerprint(spec)
                require(bid not in specs or specs[bid] == spec, "Conflicting branch identity")
                specs[bid], roles[role] = spec, bid
            trials[name] = {"breakers": breakers, "branches": roles}
        cases[key] = {"original_plan": plan, "shared_source_eligibility": eligible,
                      "potential_trials": trials, "original_summary": summaries[key]}
    baseline = {"reset_trains": [], "stop": 2210., "integration_settings": config["integration_settings"]}
    baseline_id = fingerprint(baseline)
    specs[baseline_id] = baseline
    return cases, specs, baseline_id


def prepare(archive, recovery, output):
    require(not output.exists(), "Use a new inventory output directory")
    output.mkdir(parents=True)
    transport = extract_verified(archive, output / "extracted")
    print("Verified original release members", transport["verified_members"], flush=True)
    directories = [output / "extracted/catalog-breaking-linux-28" / f"shard-{i}" for i in range(16)]
    checked = audit(directories, 28)
    require(portable(checked) == portable(read(SOURCE / "audit.json")), "Original complete-model audit differs")
    require(checked["complete_case_coverage"] and checked["cases"] == 622 and checked["passed_cases"] == 548
            and len(checked["unresolved_conditional_decisions"]) == 89, "Original scope differs")
    write(output / "original-audit.json", checked)
    print("Reproduced original audit: 548/622; 89 unresolved decisions retained", flush=True)
    reference = read(ROOT / "results/catalog-repeated" / (MODEL + ".json"))
    plans = candidate_plans(reference)
    report0 = read(directories[0] / (MODEL + ".json"))
    cases, specs, baseline = build_inventory(plans, checked["case_summaries"], reference, report0["configuration"])
    require(len(cases) == 74, "All original failed cases are required")
    source_entries, original_occurrences, failed_occurrences = [], {}, []
    missing_by_case = {}
    for index, directory in enumerate(directories):
        captured = capture(directory / (MODEL + ".json"))
        source_path = output / f"source-partition-{index:02d}.json"
        write(source_path, captured)
        source_entries.append({"index": index, "file": source_path.name, "sha256": digest(source_path),
                               "failed_branches": len(captured["failed_branches"]),
                               "original_report_sha256": captured["original_report_sha256"]})
        records = read_archives(directory, captured["original_report"], "branches")
        for bid, row in records.items():
            if bid in specs:
                require(row["specification"] == specs[bid], "Original specification differs")
                original_occurrences.setdefault(bid, []).append({"partition": index, "passed": row["passed"],
                                                                  "record_fingerprint": fingerprint(row)})
            if not row["passed"]:
                require(bid in specs, "Original failed branch is outside the full failed-case scope")
                failed_occurrences.append({"partition": index, "record_id": bid,
                                          "kind": "integration_error" if "error" in row else "completed_mismatch",
                                          "error": row.get("error"), "sample_count": row["sample_count"]})
        for key, case in cases.items():
            if case["original_summary"]["shard_index"] == index:
                required = {bid for trial in case["potential_trials"].values() for bid in trial["branches"].values()}
                missing_by_case[key] = sorted(required - records.keys())
    print("Inventoried", len(specs), "potential branches for all 74 failed cases", flush=True)
    recovery_report, recovery_inventory = read(recovery / "report.json"), read(recovery / "inventory.json")
    require(recovery_report["model_sha256"] == report0["model_sha256"] and recovery_inventory["model_id"] == MODEL,
            "Recovery model differs")
    for key, case in recovery_inventory["cases"].items():
        require(key in cases and all(cases[key][field] == case[field] for field in
                    ("original_plan", "shared_source_eligibility", "potential_trials")), "Published recovered case scope differs")
    require(all(specs.get(bid) == spec for bid, spec in recovery_inventory["branches"].items()),
            "Published recovery branch specifications differ")
    print("Checking all published recovery arrays before selecting reusable branches", flush=True)
    recovery_audit = audit_recovery(recovery)
    require(recovery_audit == read(recovery / "audit.json"), "Published recovery audit does not reproduce")
    require(recovery_audit["recovered_selected_cases"] == 2 and recovery_audit["baseline_passed"],
            "Previously published two-case recovery differs")
    write(output / "reused-recovery-audit.json", recovery_audit)
    reusable = {row["record_id"]: {"file": row["file"], "sha256": row["sha256"]}
                for row in recovery_report["branches"]}
    require(len(reusable) == 215 and set(reusable) == set(recovery_inventory["branches"]),
            "Published recovery inventory differs")
    remaining = sorted(specs.keys() - reusable.keys())
    result = {"schema_version": 1, "network": 28, "model_id": MODEL, "model_sha256": report0["model_sha256"],
              "original_cases": 622, "original_passed_cases": 548, "original_failed_case_count": len(cases),
              "original_unresolved_decisions": checked["unresolved_conditional_decisions"],
              "original_audit_sha256": digest(SOURCE / "audit.json"), "source_partitions": source_entries,
              "source_transport": transport, "calibration_sha256": digest(ROOT / "results/catalog-repeated" / (MODEL + ".json")),
              "cases": cases, "branches": specs, "expected_branches": len(specs), "full_untreated_control": baseline,
              "original_occurrences": original_occurrences, "original_failed_occurrences": failed_occurrences,
              "potential_branches_absent_from_original_case_partition": missing_by_case,
              "reused_release_tag": "kinetics-ciliberto-cases-20261118", "reused_report_sha256": digest(recovery / "report.json"),
              "reused_inventory_sha256": digest(recovery / "inventory.json"), "reused_audit_sha256": digest(recovery / "audit.json"),
              "requests": recovery_report["requests"], "acceptance": recovery_report["acceptance"],
              "reusable_verified_branches": reusable, "remaining_branch_ids": remaining,
              "remaining_integrations": 4 * len(remaining), "numerical_integrations_performed": 0,
              "conditional_search_must_be_recomputed": True, "new_case_recovery_claimed": False,
              "full_model_coverage_claimed": False, "preparation_script_sha256": digest(Path(__file__))}
    write(output / "inventory.json", result)
    summary = {"original_cases": 622, "original_passed_cases": 548, "failed_cases_selected": 74,
               "potential_branches": len(specs), "reusable_verified_branches": len(reusable),
               "remaining_branches": len(remaining), "remaining_integrations": 4 * len(remaining),
               "original_failed_branch_occurrences": len(failed_occurrences),
               "distinct_original_failed_branches": len({r["record_id"] for r in failed_occurrences}),
               "original_failure_kinds": dict(Counter(r["kind"] for r in failed_occurrences)),
               "cases_with_unobserved_potential_controls": sum(bool(v) for v in missing_by_case.values()),
               "distinct_potential_branches_missing_from_all_original_partitions": len(specs.keys() - original_occurrences.keys()),
               "inventory_sha256": digest(output / "inventory.json"), "numerical_integrations_performed": 0,
               "new_case_recovery_claimed": False, "full_model_coverage_claimed": False}
    write(output / "summary.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.archive, args.recovery, args.output)
