"""Collect fixed Ciliberto replacement artifacts and audit the complete cases.

This offline tool performs no integration, network access or workflow dispatch.
GitHub API snapshots and original downloaded ZIPs are inputs. Every selected
replacement is retained, including numerical failures. Complete-case recovery
requires the unchanged independent auditor over all 215 original branches.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_audit import require
from grn_memory.catalog_memory import write_json
from grn_memory.catalog_validation import comparison
from grn_memory.native_protocols import ResetTrain
from grn_memory.scipy_breaking_recovery import LABELS
from scripts.audit_scipy_breaking import trajectory
from scripts.audit_scipy_breaking_cases import audit as audit_cases, check_outcome
from scripts.collect_breaking_runs import extract
from scripts.recompute_ciliberto_evidence import load_inputs, read


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_selection(selection, plan):
    require(selection["schema"] == 1 and selection["repository"] == "m9h/GRN_ODE"
            and selection["workflow_path"] == ".github/workflows/ciliberto-evidence-recovery.yml",
            "Collection workflow identity differs")
    require(selection["original_report_sha256"] == plan["original_report_sha256"]
            and selection["expected_replacement_branches"] == len(plan["selected_branch_ids"]) == 18
            and selection["expected_complete_case_branches"] == plan["expected_full_branches"] == 215
            and selection["expected_selected_cases"] == plan["expected_full_cases"] == 2
            and selection["case_recovery_claimed"] is False, "Complete experiment scope differs")
    require(all(type(selection[k]) is int and selection[k] > 0
                for k in ("run_id", "run_attempt", "workflow_id"))
            and re.fullmatch(r"[0-9a-f]{40}", selection["head_sha"]), "Immutable run identity is required")
    rows = selection["selected"]
    require([r["index"] for r in rows] == list(range(18))
            and [r["record_id"] for r in rows] == plan["selected_branch_ids"]
            and len({r["job_id"] for r in rows}) == 18, "Every fixed replacement job must be selected")
    for row in rows:
        require(type(row["job_id"]) is int and row["job_id"] > 0
                and row["job_name"] == f"ciliberto-replacement-{row['index']}"
                and row["artifact_name"] == f"ciliberto-evidence-replacement-{row['index']}-attempt-{selection['run_attempt']}",
                "Selected job or artifact name differs")


def validate_job(selection, row, run, job):
    require(run["id"] == selection["run_id"] and run["run_attempt"] == selection["run_attempt"]
            and run["head_sha"] == selection["head_sha"]
            and run["workflow_id"] == selection["workflow_id"]
            and run["path"] == selection["workflow_path"], "Producer run or attempt differs")
    require(job["id"] == row["job_id"] and job["name"] == row["job_name"]
            and job["run_id"] == run["id"] and job["head_sha"] == run["head_sha"]
            and job["run_attempt"] == run["run_attempt"], "Selected job identity differs")


def validate_artifact(selection, row, run, job, artifact):
    validate_job(selection, row, run, job)
    require(artifact["name"] == row["artifact_name"] and artifact["expired"] is False
            and artifact["workflow_run"]["id"] == run["id"]
            and artifact["workflow_run"]["head_sha"] == run["head_sha"], "Artifact identity differs")
    require(job["status"] == "completed" and job["completed_at"]
            and datetime.fromisoformat(job["started_at"])
            <= datetime.fromisoformat(artifact["created_at"])
            <= datetime.fromisoformat(job["completed_at"]), "Artifact is outside the selected job attempt")
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.get("digest", "")), "Original ZIP checksum is required")


def verify_extraction(archive, evidence):
    hashes = {}
    with zipfile.ZipFile(archive) as stream:
        for member in stream.infolist():
            if member.is_dir():
                continue
            path = evidence / member.filename
            require(not path.is_symlink() and path.resolve().is_relative_to(evidence.resolve()),
                    "Extracted path escapes the artifact")
            with stream.open(member) as source:
                sha = hashlib.file_digest(source, "sha256").hexdigest()
            require(path.is_file() and digest(path) == sha, "Extracted artifact bytes differ")
            hashes[member.filename] = sha
    require(set(hashes) == {str(p.relative_to(evidence)) for p in evidence.rglob("*") if p.is_file()},
            "Unexpected extracted evidence file")
    return hashes


def verify_branch(evidence, selection, row, report, inventory, info, grid, wrapper_sha):
    lineage = read(evidence / "lineage.json")
    bid = row["record_id"]
    historical = next(r for r in report["branches"] if r["record_id"] == bid)
    require(lineage["plan_sha256"] == selection["execution_plan_sha256"]
            and lineage["original_report_sha256"] == selection["original_report_sha256"]
            and lineage["index"] == row["index"] and lineage["record_id"] == bid
            and lineage["historical_record_sha256"] == historical["sha256"]
            and lineage["source_revision"] == selection["head_sha"]
            and lineage["wrapper_sha256"] == wrapper_sha
            and lineage["github_run_id"] == str(selection["run_id"])
            and lineage["github_run_attempt"] == str(selection["run_attempt"])
            and lineage["github_job"] == "compute", "Replacement lineage differs")
    require(lineage["numerical_implementation_sha256"] == report["implementation_sha256"]
            and lineage["versions"] == report["versions"]
            and all(isinstance(lineage[k], str) and lineage[k] for k in ("platform", "machine", "python")),
            "Replacement source or runtime metadata differs")
    require(all(lineage[k] is False for k in ("byte_identical_restoration_claimed", "case_recovery_claimed",
                                            "full_model_coverage_claimed")), "Producer cannot promote evidence")
    require(lineage["status"] in ("running", "completed"), "Unknown replacement status")
    record_path = evidence / (bid + ".json")
    if not record_path.exists():
        require(lineage["status"] == "running", "Completed replacement has no branch record")
        return {"record_id": bid, "complete": False, "arrays_verified": 0, "status": "no_checkpoint"}
    record = read(record_path)
    spec = inventory["branches"][bid]
    require(record["record_id"] == bid and record["specification"] == spec
            and record["fingerprint"] == report["fingerprint"]
            and record["case_recovery_claimed"] is False and "reused_from" not in record,
            "Replacement branch identity or scope differs")
    outcomes = record["integrations"]
    require(set(outcomes) <= set(LABELS), "Unexpected integration request")
    times = grid[grid <= spec["stop"]]
    trains = [ResetTrain(**t) for t in spec["reset_trains"]]
    traces = {}
    for label, outcome in outcomes.items():
        if lineage["status"] == "running" and not outcome.get("completed") and "error" not in outcome:
            require(outcome["request"] == report["requests"][label], "Active request differs")
            continue
        if check_outcome(outcome, label, report["requests"][label], times,
                         info["observables"], trains, info["sha256"]):
            require(label in record["traces"], "Completed integration has no saved array")
            traces[label] = trajectory(evidence, bid, label, record["traces"][label], times, info["observables"])
    require(set(traces) == set(record["traces"]), "Unexpected saved trajectory")
    comparisons = {a + "_vs_" + b: comparison(traces[a], traces[b], **report["acceptance"])
                   for i, a in enumerate(LABELS) for b in LABELS[i + 1:] if a in traces and b in traces}
    status = ("incomplete" if len(comparisons) != 6 else
              "confirmed" if all(c["passed"] for c in comparisons.values()) else "mismatch")
    complete = lineage["status"] == "completed"
    if complete:
        require(set(outcomes) == set(LABELS), "Completed replacement lacks an integration outcome")
        require(record["comparisons"] == comparisons and record["status"] == status,
                "Saved branch result does not reproduce from full arrays")
        require(lineage["branch"] == {"record_id": bid, "file": record_path.name,
                                      "sha256": digest(record_path), "status": status},
                "Replacement checkpoint checksum differs")
    return {"record_id": bid, "complete": complete, "arrays_verified": len(traces), "status": status,
            "record_sha256": digest(record_path), "comparisons": comparisons,
            "lineage_sha256": digest(evidence / "lineage.json")}


def collect(inputs, selection_path, snapshots, archives, output):
    selection = read(selection_path)
    experiment = load_inputs(inputs, selection["execution_plan_sha256"])
    plan, report, inventory, _, info, grid = experiment
    validate_selection(selection, plan)
    run = read(snapshots / "run.json")
    jobs, artifacts = read(snapshots / "jobs.json"), read(snapshots / "artifacts.json")
    require(jobs["total_count"] == len(jobs["jobs"]) and artifacts["total_count"] == len(artifacts["artifacts"]),
            "API snapshots must include every page")
    wrapper_sha = hashlib.sha256(subprocess.check_output(
        ["git", "show", selection["head_sha"] + ":python/scripts/recompute_ciliberto_evidence.py"], cwd=ROOT)).hexdigest()
    pending, missing, errors, collected = [], [], [], []
    for row in selection["selected"]:
        index = row["index"]
        try:
            matches = [j for j in jobs["jobs"] if j["id"] == row["job_id"]]
            require(len(matches) == 1, "Selected job is missing or duplicated")
            job = matches[0]
            validate_job(selection, row, run, job)
            if job["status"] != "completed":
                pending.append(index)
                continue
            matches = [a for a in artifacts["artifacts"] if a["name"] == row["artifact_name"]]
            if not matches:
                missing.append({"index": index, "reason": "no_artifact"})
                continue
            require(len(matches) == 1, "Selected artifact is duplicated")
            artifact = matches[0]
            validate_artifact(selection, row, run, job, artifact)
            parent = output / str(selection["run_id"]) / f"attempt-{selection['run_attempt']}"
            destination = parent / f"artifact-{artifact['id']}"
            if not destination.exists():
                source_zip = archives / f"artifact-{artifact['id']}.zip"
                if not source_zip.is_file():
                    missing.append({"index": index, "reason": "zip_not_downloaded", "artifact_id": artifact["id"]})
                    continue
                parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="collect-", dir=parent) as temporary:
                    staging = Path(temporary) / "artifact"
                    staging.mkdir()
                    shutil.copyfile(source_zip, staging / "download.zip")
                    require(digest(staging / "download.zip") == artifact["digest"].removeprefix("sha256:"),
                            "Downloaded original ZIP checksum differs")
                    extract(staging / "download.zip", staging / "evidence")
                    staging.rename(destination)
            archive, evidence = destination / "download.zip", destination / "evidence"
            require(archive.stat().st_size == artifact["size_in_bytes"]
                    and digest(archive) == artifact["digest"].removeprefix("sha256:"), "Saved original ZIP differs")
            hashes = verify_extraction(archive, evidence)
            verified = verify_branch(evidence, selection, row, report, inventory, info, grid, wrapper_sha)
            collected.append({**row, **verified, "artifact_id": artifact["id"], "archive_sha256": artifact["digest"],
                              "archive_bytes": artifact["size_in_bytes"], "evidence": str(evidence.resolve()),
                              "evidence_sha256": hashes, "job_conclusion": job["conclusion"]})
        except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
            errors.append({"index": index, "error": f"{type(error).__name__}: {error}"})
    complete = len(collected) == 18 and all(r["complete"] for r in collected) and not (pending or missing or errors)
    status = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "status": "verification_failed" if errors else "ready_for_case_audit" if complete else "incomplete",
              "selection_sha256": digest(selection_path), "source_snapshot_sha256": {
                  name: digest(snapshots / name) for name in ("run.json", "jobs.json", "artifacts.json")},
              "pending_indices": pending, "missing_artifacts": missing, "collection_errors": errors,
              "complete_selected_inventory": complete, "branches": collected,
              "numerical_integrations_performed": 0, "case_recovery_claimed": False,
              "full_model_coverage_claimed": False}
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "status.json", status)
    return status, experiment


def assemble(inputs, preserved, restored, destination, status, experiment):
    require(status["complete_selected_inventory"], "All 18 fixed replacements must finish before assembly")
    require(not destination.exists(), "Assembly requires a new evidence directory")
    plan, original, _, _, _, _ = experiment
    manifest = read(inputs / "preservation-manifest.json")
    replacements = {row["record_id"]: row for row in status["branches"]}
    require(set(replacements) == set(plan["selected_branch_ids"]), "Replacement inventory differs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ciliberto-assemble-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "evidence"
        stage.mkdir()
        for entry in manifest["files"]:
            name = entry["path"]
            require(Path(name).name == name, "Unexpected preserved file path")
            source = preserved / name
            require(not source.is_symlink() and source.stat().st_size == entry["bytes"]
                    and digest(source) == entry["sha256"], "Preserved original evidence changed")
            shutil.copyfile(source, stage / name)
            require(digest(stage / name) == entry["sha256"], "Preserved file copy differs")
        require(digest(stage / "report.json") == plan["original_report_sha256"], "Original report changed")
        shutil.copyfile(stage / "report.json", stage / "historical-report.json")
        assembled = deepcopy(original)
        changed = []
        for entry in assembled["branches"]:
            bid = entry["record_id"]
            if bid in replacements:
                verified = replacements[bid]
                source = Path(verified["evidence"])
                # Keep every exact replacement, whether confirmed, mismatched or incomplete.
                record = read(source / (bid + ".json"))
                require(digest(source / (bid + ".json")) == verified["record_sha256"], "Verified branch changed")
                changed.append({"record_id": bid, "original_record_sha256": entry["sha256"],
                                "new_record_sha256": verified["record_sha256"], "artifact_id": verified["artifact_id"],
                                "archive_sha256": verified["archive_sha256"], "status": record["status"]})
                entry.update(sha256=verified["record_sha256"], status=record["status"])
                lineage_target = stage / "replacement-lineage" / (bid + ".json")
                lineage_target.parent.mkdir(exist_ok=True)
                require(digest(source / "lineage.json") == verified["lineage_sha256"], "Verified lineage changed")
                shutil.copyfile(source / "lineage.json", lineage_target)
            elif bid in plan["restore_from_release_branch_ids"]:
                source = restored
                require(digest(source / (bid + ".json")) == entry["sha256"], "Exact restored import differs")
                record = read(source / (bid + ".json"))
            else:
                continue
            shutil.copyfile(source / (bid + ".json"), stage / (bid + ".json"))
            for label in LABELS:
                target = stage / (bid + "-" + label + ".npz")
                if label in record["traces"]:
                    saved = record["traces"][label]
                    require(saved["file"] == target.name and digest(source / saved["file"]) == saved["sha256"],
                            "Replacement or restored array differs")
                    shutil.copyfile(source / saved["file"], target)
                    require(digest(target) == saved["sha256"], "Copied array checksum differs")
                elif target.exists():
                    # A failed new request cannot fall back to an older favorable array.
                    target.unlink()
        assembled["confirmed_branches"] = sum(r["status"] == "confirmed" for r in assembled["branches"])
        assembled["assembly_original_report_sha256"] = plan["original_report_sha256"]
        assembled["original_finished_at"] = original["finished_at"]
        assembled["finished_at"] = datetime.now(timezone.utc).isoformat()
        assembled["purpose"] = "Assembled saved evidence; historical-report.json preserves the original producer report."
        write_json(stage / "report.json", assembled)
        proof = {"purpose": __doc__, "selection_sha256": status["selection_sha256"],
                 "source_snapshot_sha256": status["source_snapshot_sha256"], "replacements": changed,
                 "restored_imports": plan["restore_from_release_branch_ids"],
                 "original_report_sha256": plan["original_report_sha256"],
                 "assembled_report_sha256": digest(stage / "report.json"),
                 "full_case_recovery_claimed": False, "full_model_coverage_claimed": False}
        write_json(stage / "assembly-provenance.json", proof)
        audit = audit_cases(stage)
        write_json(stage / "audit.json", audit)
        stage.rename(destination)
    return {"directory": str(destination.resolve()), "audit_sha256": digest(destination / "audit.json"),
            "selected_cases": audit["selected_cases"], "recovered_selected_cases": audit["recovered_selected_cases"],
            "baseline_passed": audit["baseline_passed"], "full_model_coverage_claimed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--archives", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assemble", type=Path)
    parser.add_argument("--preserved", type=Path)
    parser.add_argument("--restored", type=Path)
    args = parser.parse_args()
    status, experiment = collect(args.inputs, args.selection, args.snapshots, args.archives, args.output)
    if args.assemble:
        require(args.preserved is not None and args.restored is not None, "Original and restored evidence are required")
        result = assemble(args.inputs, args.preserved, args.restored, args.assemble, status, experiment)
        write_json(args.output / "case-audit-result.json", result)
        print(result)
    else:
        print({k: status[k] for k in ("status", "pending_indices", "missing_artifacts", "collection_errors")})
    sys.exit(1 if status["collection_errors"] else 0)
