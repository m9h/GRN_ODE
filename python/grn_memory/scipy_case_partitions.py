"""Fixed partitions of the complete Radau/native case-control inventory."""

from decimal import Decimal
from importlib.metadata import version
import platform
import hashlib
import re
import subprocess

import numpy as np

from .breaking_audit import require
from .catalog_jax import source_hashes
from .catalog_runner import ROOT, fingerprint
from .scipy_breaking_recovery import ACCEPTANCE, digest, labels_for, prepare_inventory
from scripts.audit_scipy_breaking import SOURCES
from scripts.diagnose_scipy_breaking import native_packages


SOURCE_FILES = ("source-evidence.json", "original-case-plan.json", "source-branches.jsonl.gz",
                "source-branches-provenance.json")
IMPLEMENTATION_FILES = (*SOURCES, "grn_memory/scipy_breaking_recovery.py",
                        "grn_memory/scipy_case_partitions.py", "grn_memory/breaking_audit.py",
                        "grn_memory/breaking_scores.py", "scripts/diagnose_scipy_breaking_controls.py",
                        "scripts/audit_scipy_breaking.py", "scripts/audit_scipy_breaking_cases.py",
                        "scripts/run_scipy_case_partition.py", "scripts/audit_scipy_case_partitions.py",
                        "scripts/restore_scipy_case_partition.py")


def branch_order(inventory):
    baseline = inventory["full_untreated_control"]
    require(baseline in inventory["branches"], "Full untreated baseline is missing")
    return [baseline] + sorted(set(inventory["branches"]) - {baseline})


def selected_branches(inventory, count, index):
    order = branch_order(inventory)
    require(type(count) is int and type(index) is int and 1 <= count <= len(order)
            and 0 <= index < count, "Invalid case-control partition")
    return order[index::count]


def validate_requests(requests, engine, inventory):
    labels = labels_for(engine)
    require(set(requests) == set(labels), "All four integration requests are required")
    for base, factor in ((engine, 2), ("scipy", 10)):
        for label in (base, base + "_refined"):
            row = requests[label]
            require(set(row) == ({"method", "rtol", "atol"} if base == "scipy" else {"rtol", "atol"}),
                    "Unexpected integration setting")
            require(all(type(row[k]) in (int, float) and np.isfinite(row[k]) and row[k] > 0
                        for k in ("rtol", "atol")), "Positive finite tolerances are required")
            if base == "scipy":
                require(row["method"] == "Radau", "Independent reference must use Radau")
        require(all(requests[base + "_refined"][k] == float(Decimal(str(requests[base][k])) / factor)
                    and requests[base + "_refined"][k] < requests[base][k] for k in ("rtol", "atol")),
                "Declared refinements differ")
    require(all(requests[engine][k] < spec["integration_settings"][engine][k]
                for spec in inventory["branches"].values() for k in ("rtol", "atol")),
            "Native requests must refine every original branch")


def load_experiment(directory):
    import json
    plan_path = directory / "execution-plan.json"
    plan = json.loads(plan_path.read_text())
    require(type(plan["schema_version"]) is int and plan["schema_version"] == 1 and plan["acceptance"] == ACCEPTANCE
            and plan["case_recovery_claimed"] is False and plan["full_model_coverage_claimed"] is False,
            "Unsupported execution plan or acceptance")
    require(re.fullmatch(r"[0-9a-f]{40}", plan["source_revision"])
            and re.fullmatch(r"BIOMD[0-9]{10}", plan["model_id"]), "Immutable original source identity is required")
    require(set(plan["source_files_sha256"]) == set(SOURCE_FILES)
            and all(digest(directory / name) == sha for name, sha in plan["source_files_sha256"].items()),
            "Original source input bytes differ")
    inventory, path, info, grid = prepare_inventory(
        directory / "source-evidence.json", directory / "original-case-plan.json", plan["source_revision"],
        directory / "source-branches.jsonl.gz")
    require(plan["inventory_sha256"] == fingerprint(inventory)
            and plan["model_id"] == inventory["model_id"]
            and plan["expected_branches"] == inventory["expected_branches"]
            and plan["expected_model_cases"] == inventory["expected_model_cases"]
            and plan["selected_case_keys"] == sorted(inventory["cases"]),
            "Complete original case-control inventory differs")
    selected_branches(inventory, plan["shard_count"], 0)
    validate_requests(plan["requests"], plan["reference_engine"], inventory)
    return plan, inventory, path, info, grid


def implementation_hashes():
    sources = source_hashes()
    sources.update({name: digest(ROOT / name) for name in IMPLEMENTATION_FILES})
    sources.update({str(path.relative_to(ROOT)): digest(path) for path in (ROOT / "grn_memory").glob("*.py")})
    sources.update({name: digest(ROOT / name) for name in ("pyproject.toml", "uv.lock")})
    return sources


def verify_repository_sources(revision, sources):
    require(isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision), "Invalid producer revision")
    for name, expected in sources.items():
        if name.startswith("jaxkineticmodel/"):
            continue  # Installed package source hashes are checked separately in metadata.
        data = subprocess.check_output(["git", "show", f"{revision}:python/{name}"], cwd=ROOT)
        require(hashlib.sha256(data).hexdigest() == expected, "Producer Git source differs: " + name)


def metadata(plan_path, plan, inventory, grid, index):
    experiment = {"schema_version": 1, "execution_plan_sha256": digest(plan_path),
                  "model_id": inventory["model_id"], "model_sha256": inventory["model_sha256"],
                  "inventory_sha256": fingerprint(inventory), "reference_engine": plan["reference_engine"],
                  "requests": plan["requests"], "acceptance": ACCEPTANCE,
                  "implementation_sha256": implementation_hashes(),
                  "versions": {p: version(p) for p in sorted(native_packages(plan["reference_engine"]))},
                  "platform": {"system": platform.system(), "machine": platform.machine(),
                               "python": platform.python_version()},
                  "sample_grid_sha256": hashlib.sha256(grid.tobytes()).hexdigest(),
                  "branch_order_sha256": fingerprint(branch_order(inventory)),
                  "shard_count": plan["shard_count"], "case_recovery_claimed": False,
                  "full_model_coverage_claimed": False}
    partition = {"experiment": experiment, "experiment_fingerprint": fingerprint(experiment),
                 "shard_index": index,
                 "selected_branch_ids": selected_branches(inventory, plan["shard_count"], index)}
    return {**partition, "fingerprint": fingerprint(partition)}


def validate_metadata(saved, plan_path, plan, inventory, grid, *, live_environment=False):
    expected = metadata(plan_path, plan, inventory, grid, saved["shard_index"])
    if not live_environment:
        recorded = saved["experiment"]
        require(set(recorded["versions"]) == native_packages(plan["reference_engine"])
                and all(isinstance(v, str) and v for v in recorded["versions"].values()),
                "Producer package inventory differs")
        require(set(recorded["platform"]) == {"system", "machine", "python"}
                and all(isinstance(v, str) and v for v in recorded["platform"].values()),
                "Producer platform inventory differs")
        expected["experiment"]["versions"] = recorded["versions"]
        expected["experiment"]["platform"] = recorded["platform"]
        expected["experiment_fingerprint"] = fingerprint(expected["experiment"])
        expected["fingerprint"] = fingerprint({k: v for k, v in expected.items() if k != "fingerprint"})
    require(saved == expected, "Partition source, scope, requests, environment or fingerprint differs")


def validate_partition_inventory(reports, plan, inventory):
    require(len(reports) == plan["shard_count"], "Every original partition is required")
    require(sorted(r["metadata"]["shard_index"] for r in reports) == list(range(plan["shard_count"])),
            "Duplicate or missing partition index")
    require(len({r["metadata"]["experiment_fingerprint"] for r in reports}) == 1,
            "Cannot combine different sources or producer environments")
    all_ids = []
    for report in reports:
        meta = report["metadata"]
        wanted = selected_branches(inventory, plan["shard_count"], meta["shard_index"])
        require(meta["selected_branch_ids"] == wanted and report["status"] == "completed"
                and report["complete_selected_inventory"] is True,
                "Partition is incomplete or its original selection differs")
        require([b["record_id"] for b in report["branches"]] == wanted,
                "Partition branch inventory is missing, duplicated or reordered")
        all_ids.extend(wanted)
    require(len(all_ids) == len(set(all_ids)) == inventory["expected_branches"]
            and set(all_ids) == set(inventory["branches"]), "Complete case-control union differs")


def validate_cached_branches(directory, report, inventory, grid, info):
    """Check every saved full array before a resumed worker integrates anything."""
    import json
    from .native_protocols import ResetTrain
    from scripts.diagnose_scipy_breaking import load_saved
    meta = report["metadata"]
    experiment = meta["experiment"]
    engine = experiment["reference_engine"]
    labels = labels_for(engine)
    selected = meta["selected_branch_ids"]
    entries = {b["record_id"]: b for b in report["branches"]}
    require(len(entries) == len(report["branches"]) and set(entries) <= set(selected),
            "Unexpected or duplicate cached report entry")
    existing = {p.stem for p in directory.glob("*.json") if re.fullmatch(r"[0-9a-f]{64}", p.stem)}
    require(existing <= set(selected), "Cached record belongs to another partition")
    require(report.get("active_branch") in (None, *selected), "Unexpected active branch")
    count, arrays = 0, 0
    for bid in selected:
        path = directory / (bid + ".json")
        if not path.exists():
            require(bid not in entries, "A reported cached branch is missing")
            continue
        if bid in entries and (report["status"] == "completed" or bid != report.get("active_branch")):
            require(entries[bid]["sha256"] == digest(path), "Reported cached branch digest differs")
        record = json.loads(path.read_text())
        spec = inventory["branches"][bid]
        require(record["fingerprint"] == meta["fingerprint"] and record["record_id"] == bid
                and record["specification"] == spec and record["case_recovery_claimed"] is False,
                "Cached branch identity differs")
        require(set(record["integrations"]) <= set(labels)
                and set(record["traces"]) == {k for k, v in record["integrations"].items() if v.get("completed") is True},
                "Cached integration and array inventories differ")
        times = grid[grid <= spec["stop"]]
        trains = [ResetTrain(**t) for t in spec["reset_trains"]]
        for label, outcome in record["integrations"].items():
            request = experiment["requests"][label]
            require(outcome["request"] == request, "Cached integration settings differ")
            if outcome.get("completed") is not True:
                require(outcome.get("completed") is False, "Invalid cached completion flag")
                continue
            if not label.startswith("scipy"):
                require(outcome.get("native_engine") == engine, "Cached native engine differs")
            saved = record["traces"][label]
            require(saved["file"] == bid + "-" + label + ".npz", "Cached trajectory path differs")
            load_saved(directory / saved["file"], saved, times, info["observables"], outcome,
                       label, request, trains, info["sha256"])
            arrays += 1
        count += 1
    return {"verified_branch_records": count, "verified_complete_arrays": arrays}
