"""Audit a predetermined complete partition inventory across workflow runs.

Collectors download artifacts; this tool performs no network requests or
integrations. Every selected file must match its original checksummed ZIP.
The existing model auditor keeps each partition's branch evidence separate.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_breaking import candidate_plans
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_runner import fingerprint
from scripts import audit_breaking_shards as auditor


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def validate_plan(plan):
    require(plan.get("schema_version") == 1, "Unsupported selection plan")
    network, count = plan["network"], plan["shard_count"]
    require(type(network) is int and type(count) is int and count > 0, "Invalid network or partition count")
    catalog = read(ROOT/"models/catalog.json")["models"]
    entries = [e for e in catalog if e["network"] == network]
    require(len(entries) == 1 and entries[0]["biomodel_id"] == plan["model_id"], "Plan model differs")
    reference = read(ROOT/"results/catalog-repeated"/(plan["model_id"]+".json"))
    require(plan["expected_model_cases"] == len(candidate_plans(reference)), "Plan case inventory differs")
    parts = plan["partitions"]
    require(len(parts) == count and all(type(p["shard_index"]) is int for p in parts)
            and sorted(p["shard_index"] for p in parts) == list(range(count)),
            "Plan must select every partition exactly once")
    require(len({p["job_id"] for p in parts}) == count, "Duplicate selected job")
    for p in parts:
        require(all(type(p[k]) is int and p[k] > 0 for k in ("run_id", "run_attempt", "job_id")),
                "Positive run, attempt and job identities are required")
        require(re.fullmatch(r"[0-9a-f]{40}", p["producer_revision"]), "Invalid producer revision")
    return sorted(parts, key=lambda p: p["shard_index"])


def verify_artifact(partition, collection_directory, selection, plan):
    artifact_id = partition["artifact_id"]
    require(type(artifact_id) is int and artifact_id > 0, "Invalid artifact identity")
    artifact = collection_directory/f"artifact-{artifact_id}"
    directory = artifact/"evidence"
    require(Path(partition["directory"]).resolve() == directory.resolve(), "Artifact directory differs")
    expected = partition["archive_sha256"]
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", expected), "Artifact ZIP digest is required")
    archive = artifact/"download.zip"
    require(digest(archive) == expected.removeprefix("sha256:"), "Artifact ZIP digest differs")
    files, names, size = {}, set(), 0
    with zipfile.ZipFile(archive) as stream:
        for entry in stream.infolist():
            path = PurePosixPath(entry.filename)
            require(not path.is_absolute() and ".." not in path.parts and entry.filename not in names
                    and not stat.S_ISLNK(entry.external_attr >> 16), "Unsafe or duplicate artifact member")
            names.add(entry.filename)
            if entry.is_dir():
                continue
            target = directory/entry.filename
            require(target.resolve().is_relative_to(directory.resolve()) and not target.is_symlink()
                    and target.is_file() and target.stat().st_size == entry.file_size,
                    "Extracted artifact inventory differs")
            sha = hashlib.sha256()
            with stream.open(entry) as member:
                for chunk in iter(lambda: member.read(1024*1024), b""):
                    sha.update(chunk)
            files[entry.filename] = sha.hexdigest()
            require(digest(target) == files[entry.filename], "Extracted artifact bytes differ from ZIP")
            size += entry.file_size
    actual = set()
    for path in directory.rglob("*"):
        require(not path.is_symlink(), "Symlink in extracted artifact")
        if path.is_file():
            actual.add(str(path.relative_to(directory)))
    require(actual == set(files), "Untracked or missing extracted artifact files")
    manifest_path = directory/"shard.json"
    require(digest(manifest_path) == partition["manifest_sha256"], "Collected manifest digest differs")
    manifest = read(manifest_path)
    require(manifest["network"] == plan["network"] and manifest["model_id"] == plan["model_id"]
            and manifest["shard_index"] == selection["shard_index"]
            and manifest["shard_count"] == plan["shard_count"]
            and manifest["git_revision"] == selection["producer_revision"], "Selected manifest identity differs")
    require(manifest["selected_coverage_complete"] is True and "finished_at" in manifest
            and manifest["status"] != "running", "Selected partition is not complete")
    return directory, {**selection, "artifact_id": artifact_id, "archive_sha256": expected,
                       "archive_bytes": archive.stat().st_size,
                       "manifest_sha256": digest(manifest_path), "verified_files": len(files),
                       "verified_uncompressed_bytes": size, "file_inventory_sha256": fingerprint(files)}


def evaluate(plan, collection_roots):
    selections = validate_plan(plan)
    states, ready, pending, needs_resume = [], [], [], []
    collections = {}
    for selection in selections:
        run, attempt = selection["run_id"], selection["run_attempt"]
        key = run, attempt
        if key not in collections:
            candidates = [Path(root)/str(run)/f"attempt-{attempt}"/"collection.json" for root in collection_roots]
            found = [p for p in candidates if p.exists()]
            require(len(found) <= 1, "Ambiguous collection source")
            collections[key] = (found[0], read(found[0])) if found else (None, None)
        path, collection = collections[key]
        state = {**selection, "state": "waiting_for_collection"}
        states.append(state)
        if collection is None:
            pending.append(selection["shard_index"])
            continue
        require(collection["run_id"] == run and collection["run_attempt"] == attempt
                and collection["producer_revision"] == selection["producer_revision"],
                "Collected run identity differs from plan")
        network = collection["networks"].get(str(plan["network"]), {"jobs": [], "partitions": []})
        jobs = [j for j in network["jobs"] if j["index"] == selection["shard_index"]]
        require(len(jobs) <= 1, "Ambiguous selected job")
        if not jobs:
            pending.append(selection["shard_index"])
            continue
        job = jobs[0]
        require(job["id"] == selection["job_id"], "Selected job identity differs")
        state.update(state=job["status"], conclusion=job["conclusion"])
        if job["status"] != "completed":
            pending.append(selection["shard_index"])
            continue
        parts = [p for p in network["partitions"] if p["shard_index"] == selection["shard_index"]]
        require(len(parts) <= 1, "Ambiguous selected artifact")
        if not parts:
            state["state"] = "completed_job_missing_artifact"
            pending.append(selection["shard_index"])
            continue
        part = parts[0]
        require(part["shard_count"] == plan["shard_count"], "Collected partition count differs")
        require(type(part["selected_coverage_complete"]) is bool, "Invalid reported coverage flag")
        state.update(artifact_id=part["artifact_id"], reported_inventory_complete=part["selected_coverage_complete"])
        if not part["selected_coverage_complete"]:
            needs_resume.append(selection["shard_index"])
        ready.append((part, path.parent, selection))
    result = {"purpose": __doc__, "network": plan["network"], "model_id": plan["model_id"],
              "plan_sha256": fingerprint(plan), "partition_states": states,
              "pending_indices": pending, "needs_continuation_indices": needs_resume,
              "complete_case_coverage": False, "all_numerical_validations_passed": False,
              "numerical_integrations_performed": 0, "workflow_dispatches_performed": 0,
              "selection_auditor_sha256": digest(Path(__file__))}
    if needs_resume or pending:
        result["status"] = "incomplete_execution" if needs_resume else "waiting_for_partitions"
        return result
    directories, provenance = [], []
    for part, collection_directory, selection in ready:
        directory, verified = verify_artifact(part, collection_directory, selection, plan)
        directories.append(directory)
        provenance.append(verified)
    audited = auditor.audit(directories, plan["network"])
    result.update(status="passed" if audited["all_numerical_validations_passed"] else "numerical_disagreement",
                  complete_case_coverage=audited["complete_case_coverage"],
                  all_numerical_validations_passed=audited["all_numerical_validations_passed"],
                  verified_artifacts=provenance, model_audit=audited)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--collection-root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=45.)
    args = parser.parse_args()
    if not 1 <= args.interval <= 60:
        parser.error("Use a watch interval of 1–60 seconds")
    plan = read(args.plan)
    validate_plan(plan)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output/".selection-audit.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        saved_plan = args.output/"selection-plan.json"
        if saved_plan.exists():
            require(read(saved_plan) == plan, "Use a new output for a different selection plan")
        else:
            write_json(saved_plan, plan)
        previous = None
        while True:
            try:
                result = evaluate(plan, args.collection_root)
            except Exception as error:
                write_json(args.output/"status.json", {"status": "audit_error", "plan_sha256": fingerprint(plan),
                           "complete_case_coverage": False, "all_numerical_validations_passed": False,
                           "error": f"{type(error).__name__}: {error}"})
                raise
            summary = {k: result[k] for k in ("network", "status", "pending_indices", "needs_continuation_indices",
                                             "complete_case_coverage", "all_numerical_validations_passed")}
            result["checked_at"] = datetime.now(timezone.utc).isoformat()
            if "model_audit" in result:
                write_json(args.output/"audit.json", result.pop("model_audit"))
                result["model_audit_sha256"] = digest(args.output/"audit.json")
            write_json(args.output/"status.json", result)
            if summary != previous:
                print(json.dumps(summary), flush=True)
                previous = summary
            if not args.watch or result["status"] != "waiting_for_partitions":
                return
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
