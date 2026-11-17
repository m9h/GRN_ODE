"""Collect a fixed complete partition selection without performing integrations.

Finished jobs can be collected while their parent matrix is still running.
Checkpoint artifacts remain incomplete evidence, irrespective of job conclusion.
Only the complete all-partition auditor may make a selected-case recovery claim.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_memory import write_json
from grn_memory.scipy_case_partitions import (
    SOURCE_FILES, load_experiment, validate_metadata, validate_cached_branches,
    verify_repository_sources, validate_partition_inventory,
)
from scripts import audit_scipy_case_partitions as auditor
from scripts.collect_breaking_runs import extract, pages
from scripts.restore_scipy_case_partition import GitHub, digest


def read(path):
    return json.loads(path.read_text())


def validate_selection(selection, plan_path, plan):
    require(selection["schema_version"] == 1 and selection["model_id"] == plan["model_id"]
            and selection["execution_plan_sha256"] == digest(plan_path)
            and selection["partition_count"] == plan["shard_count"], "Collection experiment differs")
    rows = selection["partitions"]
    require(sorted(r["shard_index"] for r in rows) == list(range(plan["shard_count"])),
            "Exactly every original partition must be selected")
    require(len({r["job_id"] for r in rows}) == len(rows), "Duplicate selected job")
    for row in rows:
        require(all(type(row[k]) is int and row[k] > 0 for k in ("run_id", "run_attempt", "job_id"))
                and type(row["shard_index"]) is int
                and re.fullmatch(r"[0-9a-f]{40}", row["producer_revision"]),
                "Immutable run, attempt, job and revision are required")


def validate_job(row, run, job):
    require(run["id"] == row["run_id"] and run["run_attempt"] == row["run_attempt"]
            and run["head_sha"] == row["producer_revision"]
            and run["path"] == ".github/workflows/scipy-case-controls.yml",
            "Selected producer run or attempt differs")
    require(job["id"] == row["job_id"] and job["run_id"] == run["id"]
            and job["run_attempt"] == row["run_attempt"]
            and job["head_sha"] == run["head_sha"]
            and job["name"] == f"scipy-case-partition-{row['shard_index']}",
            "Selected job identity differs")


def validate_artifact(artifact, row, run, job, model):
    validate_job(row, run, job)
    name = f"scipy-cases-{model}-partition-{row['shard_index']}-attempt-{row['run_attempt']}"
    require(artifact["name"] == name and artifact["expired"] is False
            and artifact["workflow_run"]["id"] == run["id"]
            and artifact["workflow_run"]["head_sha"] == run["head_sha"], "Artifact identity differs")
    # Other matrix jobs may still be running. Only this fixed job must be final.
    require(job["status"] == "completed" and job["completed_at"]
            and datetime.fromisoformat(job["started_at"])
            <= datetime.fromisoformat(artifact["created_at"])
            <= datetime.fromisoformat(job["completed_at"]), "Artifact is outside this completed job attempt")
    require(isinstance(artifact.get("digest"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"]), "Original ZIP SHA-256 is required")


def verify_extraction(archive, evidence):
    """Bind existing extracted bytes to the verified ZIP, including on restart."""
    hashes = {}
    with zipfile.ZipFile(archive) as stream:
        for member in stream.infolist():
            if member.is_dir():
                continue
            path = evidence / member.filename
            require(not path.is_symlink() and path.resolve().is_relative_to(evidence.resolve()),
                    "Extracted path escapes evidence")
            sha = hashlib.sha256()
            with stream.open(member) as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    sha.update(chunk)
            require(path.is_file() and digest(path) == sha.hexdigest(), "Extracted artifact bytes differ")
            hashes[member.filename] = sha.hexdigest()
    require(set(hashes) == {str(p.relative_to(evidence)) for p in evidence.rglob("*") if p.is_file()},
            "Unexpected extracted evidence file")
    return hashes


def stamps(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "Symlink in collected evidence")
        if path.is_file():
            stat = path.stat()
            result[str(path.relative_to(directory))] = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
    return result


def verify_partition(evidence, row, inputs, experiment):
    plan, inventory, _, info, grid = experiment
    report = read(evidence / "report.json")
    require(report["producer_revision"] == row["producer_revision"]
            and report["metadata"]["shard_index"] == row["shard_index"], "Report producer differs")
    require(report["case_recovery_claimed"] is False and report["full_model_coverage_claimed"] is False,
            "Producer cannot promote a case or model")
    require(all(digest(evidence / name) == digest(inputs / name)
                for name in (*SOURCE_FILES, "execution-plan.json")), "Original input bytes differ")
    require(read(evidence / "inventory.json") == inventory, "Reconstructed inventory differs")
    validate_metadata(report["metadata"], inputs / "execution-plan.json", plan, inventory, grid)
    verify_repository_sources(row["producer_revision"], report["metadata"]["experiment"]["implementation_sha256"])
    verified = validate_cached_branches(evidence, report, inventory, grid, info)
    require(report["status"] in ("running", "checkpointed", "completed"), "Unknown producer status")
    selected = report["metadata"]["selected_branch_ids"]
    require([b["record_id"] for b in report["branches"]] == selected[:len(report["branches"])],
            "Reported branches are not the fixed original prefix")
    complete = report["status"] == "completed"
    require(report["complete_selected_inventory"] is complete, "Completion flag differs")
    require(not complete or len(report["branches"]) == len(selected), "Incomplete branch inventory")
    audited, timings = [], []
    for entry in report["branches"]:
        # A killed resume can leave an updated active record ahead of report.json.
        if not complete and entry["record_id"] == report.get("active_branch"):
            continue
        _, proof = auditor.audit_record(evidence, entry, report, inventory, grid, info)
        audited.append({"record_id": proof["record_id"], "status": proof["status"]})
    for bid in selected:
        path = evidence / (bid + ".json")
        if path.exists():
            record = read(path)
            timings.append({"record_id": bid, "integrations": {
                label: {key: outcome.get(key) for key in ("completed", "seconds", "error")}
                for label, outcome in record["integrations"].items()}})
    return {**verified, "producer_status": report["status"], "complete_selected_inventory": complete,
            "expected_branches": len(selected), "reported_branches": len(report["branches"]),
            "audited_branches": audited, "integration_timings": timings,
            "active_branch": report.get("active_branch"), "report_sha256": digest(evidence / "report.json")}


def collect_partition(github, artifact, row, run, job, inputs, experiment, root, cache):
    validate_artifact(artifact, row, run, job, experiment[0]["model_id"])
    parent = root / str(row["run_id"]) / f"attempt-{row['run_attempt']}"
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / f"artifact-{artifact['id']}"
    identity = {**row, "artifact_id": artifact["id"], "archive_sha256": artifact["digest"],
                "archive_bytes": artifact["size_in_bytes"]}
    key = artifact["id"]
    if key in cache:
        previous, previous_stamps, result = cache[key]
        require(previous == identity, "Previously collected artifact identity changed")
        require(previous_stamps == stamps(destination), "Collected evidence changed during watch")
        return result
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix="scipy-collect-", dir=parent) as temporary:
            staging = Path(temporary) / "artifact"
            staging.mkdir()
            github.download(artifact["id"], staging / "download.zip")
            require("sha256:" + digest(staging / "download.zip") == artifact["digest"], "Downloaded ZIP differs")
            extract(staging / "download.zip", staging / "evidence")
            staging.rename(destination)
    archive, evidence = destination / "download.zip", destination / "evidence"
    require(archive.stat().st_size == artifact["size_in_bytes"]
            and "sha256:" + digest(archive) == artifact["digest"], "Saved original ZIP differs")
    hashes = verify_extraction(archive, evidence)
    verification = verify_partition(evidence, row, inputs, experiment)
    result = {**identity, **verification, "directory": str(evidence),
              "job_conclusion": job["conclusion"], "evidence_sha256": hashes}
    write_json(destination / "verification.json", result)
    cache[key] = (identity, stamps(destination), result)
    print(json.dumps({"partition": row["shard_index"], "status": verification["producer_status"],
                      "arrays_verified": verification["verified_complete_arrays"],
                      "branches_audited": len(verification["audited_branches"])}), flush=True)
    return result


def summarize(selection, collected, pending, missing, errors):
    needed = [r["shard_index"] for r in collected if not r["complete_selected_inventory"]]
    complete = len(collected) == selection["partition_count"] and not (needed or errors or pending or missing)
    terminal = not pending and not errors
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "selection_partition_count": selection["partition_count"],
            "status": "verification_failed" if errors else "ready_for_case_audit" if complete
                      else "terminal_incomplete" if terminal else "collecting",
            "all_selected_jobs_terminal": not pending,
            "complete_selected_inventory": complete, "needs_continuation": sorted(needed),
            "pending_indices": sorted(pending), "missing_artifact_indices": sorted(missing),
            "collection_errors": errors, "partitions": collected,
            "numerical_integrations_performed": 0, "workflows_dispatched": 0,
            "case_recovery_claimed": False, "full_model_coverage_claimed": False}


def collect(github, selection, inputs, experiment, root, cache):
    runs = {}
    for run_id in sorted({r["run_id"] for r in selection["partitions"]}):
        run = github.api(f"actions/runs/{run_id}")
        jobs = pages(github, f"actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs", "jobs")
        artifacts = pages(github, f"actions/runs/{run_id}/artifacts", "artifacts")
        runs[run_id] = run, {j["id"]: j for j in jobs}, artifacts
    collected, pending, missing, errors = [], [], [], []
    for row in sorted(selection["partitions"], key=lambda r: r["shard_index"]):
        run, jobs, artifacts = runs[row["run_id"]]
        index = row["shard_index"]
        job = jobs.get(row["job_id"])
        require(job is not None, "Selected job is missing from its original attempt")
        validate_job(row, run, job)
        if job["status"] != "completed":
            pending.append(index)
            continue
        name = f"scipy-cases-{selection['model_id']}-partition-{index}-attempt-{row['run_attempt']}"
        matching = [a for a in artifacts if a["name"] == name]
        if not matching:
            missing.append(index)
            continue
        require(len(matching) == 1, "Ambiguous original artifact")
        try:
            collected.append(collect_partition(github, matching[0], row, run, job, inputs,
                                                experiment, root, cache))
        except subprocess.CalledProcessError:
            raise  # Transport failures retry the same selection; never choose another artifact.
        except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
            errors.append({"shard_index": index, "error": str(error)})
    return summarize(selection, collected, pending, missing, errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="m9h/GRN_ODE")
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=45.)
    args = parser.parse_args()
    require(1 <= args.interval <= 60, "Watch interval must be 1–60 seconds")
    selection = read(args.selection)
    experiment = load_experiment(args.inputs)
    validate_selection(selection, args.inputs / "execution-plan.json", experiment[0])
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / ".collector.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        selected = args.output / "selection.json"
        if selected.exists():
            require(read(selected) == selection, "Existing fixed collection selection differs")
        else:
            write_json(selected, selection)
        github, cache, transport_failures = GitHub(args.repository), {}, 0
        while True:
            try:
                result = collect(github, selection, args.inputs, experiment, args.output, cache)
                transport_failures = 0
            except subprocess.CalledProcessError as error:
                transport_failures += 1
                print(json.dumps({"transport_error": str(error), "attempt": transport_failures}), flush=True)
                if not args.watch or transport_failures >= 6:
                    raise
                time.sleep(args.interval)
                continue
            write_json(args.output / "status.json", result)
            print(json.dumps({k: result[k] for k in ("status", "pending_indices", "needs_continuation",
                                                    "missing_artifact_indices", "collection_errors")}), flush=True)
            if result["collection_errors"]:
                return 2
            if result["complete_selected_inventory"]:
                # Recheck every ZIP and extracted byte immediately before the complete audit.
                for row in result["partitions"]:
                    directory = Path(row["directory"])
                    require("sha256:" + digest(directory.parent / "download.zip") == row["archive_sha256"],
                            "ZIP changed before final audit")
                    verify_extraction(directory.parent / "download.zip", directory)
                reports = [read(Path(r["directory"]) / "report.json") for r in result["partitions"]]
                validate_partition_inventory(reports, experiment[0], experiment[1])
                audited = auditor.audit([Path(r["directory"]) for r in result["partitions"]])
                write_json(args.output / "audit.json", audited)
                return 0
            if not args.watch or result["all_selected_jobs_terminal"]:
                return 1 if result["all_selected_jobs_terminal"] else 0
            time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
