"""Collect immutable precision artifacts and independently audit completed arrays.

This collector never integrates, retries or dispatches work. Partial checkpoint
bytes are preserved; their MPFR state is validated in the matching runtime on
resume. Finished arrays are audited here without requiring Heyoka.
"""

import argparse
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.catalog_memory import write_json
from grn_memory.taylor_checkpoints import signature
from grn_memory.taylor_partitions import REQUESTS, digest, load_trace, now, problem, require, verify_report_identity
from grn_memory.taylor_partition_resume import GitHub, extract
from scripts import audit_taylor_partitions as auditor

PARTITIONS = {35: 17, 39: 4}


def selected_problem(model, index, control_plan):
    if control_plan is None:
        return problem(model, index, PARTITIONS[model])
    from grn_memory import taylor_case_controls as controls
    return controls.problem(control_plan, index, len(control_plan["control_branch_ids"]))


def completed_audit(directories, control_plan, *, allow_partial):
    if control_plan is None:
        return auditor.audit(directories, allow_partial=allow_partial)
    from grn_memory import taylor_case_controls as controls
    # Even all complementary controls do not replace the failed training arms.
    return controls.audit_cases(control_plan, directories, allow_partial=True)


def download_partition(github, artifact, job, run, model, index, directory, *, control_plan=None):
    require(not artifact["expired"] and artifact["workflow_run"]["id"] == run["id"]
            and artifact["workflow_run"]["head_sha"] == run["head_sha"]
            and datetime.fromisoformat(artifact["created_at"]) >= datetime.fromisoformat(job["started_at"]),
            "Artifact does not belong to this job attempt")
    expected = artifact.get("digest", "")
    require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", expected)), "Artifact SHA-256 is required")
    destination = directory / f"artifact-{artifact['id']}"
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix="precision-download-", dir=directory) as temporary:
            staging = Path(temporary) / "artifact"
            staging.mkdir()
            archive = staging / "download.zip"
            github.download(artifact["id"], archive)
            require(digest(archive) == expected.removeprefix("sha256:"), "Downloaded archive SHA-256 differs")
            extract(archive, staging / "payload")
            staging.rename(destination)
    require(digest(destination / "download.zip") == expected.removeprefix("sha256:"), "Saved archive SHA-256 differs")
    execution_path = destination / "payload/execution.json"
    execution = json.loads(execution_path.read_text())
    count = PARTITIONS[model] if control_plan is None else len(control_plan["control_branch_ids"])
    _, info, times, core, selection = selected_problem(model, index, control_plan)
    required = {"schema": 1, "run_id": run["id"], "run_attempt": run["run_attempt"], "head_sha": run["head_sha"],
                "model": model, "partition_index": index, "partition_count": count, "evidence_directory": "evidence"}
    if control_plan is not None:
        required.update(scope="paired-case-controls", case_plan_sha256=signature(control_plan),
                        implementation_sha256=core["implementation_sha256"])
    require(all(execution.get(k) == v for k, v in required.items()), "Artifact execution identity differs")
    require(execution.get("source_provenance") == {"source_revision": run["head_sha"],
            "implementation_files_differing_from_revision": []}, "Producer numerical sources differ")
    evidence = destination / "payload/evidence"
    report = json.loads((evidence / "report.json").read_text())
    verify_report_identity(report, core, selection)
    if control_plan is not None:
        from grn_memory.taylor_case_controls import verify_attempts, verify_committed_sources
        verify_attempts(report)
        verify_committed_sources(run["head_sha"], tuple(sorted(core["implementation_sha256"].items())))
    require(report["status"] in ("running", "completed", "checkpointed", "budget_exhausted", "integration_failed")
            and set(report["traces"]) <= set(REQUESTS) and set(report["integrations"]) <= set(REQUESTS),
            "Unexpected partition state or integration inventory")
    for label in report["traces"]:
        load_trace(evidence, report, label, info, times)
    hashes = {str(path.relative_to(destination / "payload")): digest(path)
              for path in sorted((destination / "payload").rglob("*")) if path.is_file()}
    # Recheck extraction as well as the retained archive; either can be altered
    # locally after collection. The archive's member bytes are authoritative.
    with zipfile.ZipFile(destination / "download.zip") as stream:
        archived = {row.filename: hashlib.sha256(stream.read(row)).hexdigest()
                    for row in stream.infolist() if not row.is_dir()}
    require(hashes == archived, "Extracted evidence differs from the downloaded archive")
    audit_path = destination / "audit.json"
    audit = None
    if report["status"] == "completed":
        identity = signature({"files": hashes, "auditor_sha256": digest(Path(auditor.__file__)), "core": core})
        cache_path = destination / "audit-source.json"
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        if cache.get("identity") == identity and audit_path.exists() and cache.get("audit_sha256") == digest(audit_path):
            audit = json.loads(audit_path.read_text())
        else:
            audit = completed_audit([evidence], control_plan, allow_partial=True)
            write_json(audit_path, audit)
            write_json(cache_path, {"identity": identity, "audit_sha256": digest(audit_path)})
    return {"index": index, "artifact_id": artifact["id"], "archive_sha256": expected,
            "directory": str(evidence), "execution_sha256": digest(execution_path),
            "report_sha256": digest(evidence / "report.json"), "reported_status": report["status"],
            "completed_integrations": sorted(report["traces"]), "public_evidence_sha256": hashes,
            "checkpoint_validation": "deferred to matching runtime on resume",
            "complete_arrays_audited": audit is not None,
            "diagnostic_status": (audit["summaries"][0]["status"] if control_plan is None else
                                  audit["branch_evidence"][selection["branch_id"]]["diagnostic_status"])
                                 if audit is not None else None,
            "audit": str(audit_path) if audit is not None else None}


def collect_run(github, run_id, model, root, *, control_plan=None):
    count = PARTITIONS[model]
    workflow, gate, prefix = ".github/workflows/precision-checkpoints.yml", "precision-checkpoints", "precision-model"
    if control_plan is not None:
        from grn_memory.taylor_case_controls import validate_plan
        require(validate_plan(control_plan) == model, "Control model differs")
        count = len(control_plan["control_branch_ids"])
        workflow, gate, prefix = ".github/workflows/precision-case-controls.yml", "validate", "precision-control-model"
    run = github.api(f"actions/runs/{run_id}")
    require(run["id"] == run_id and re.fullmatch(r"[0-9a-f]{40}", run["head_sha"])
            and run["path"] == workflow, "Unexpected workflow identity")
    directory = root / str(run_id) / f"attempt-{run['run_attempt']}"
    directory.mkdir(parents=True, exist_ok=True)
    jobs = github.rows(f"actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs", "jobs")
    artifacts = github.rows(f"actions/runs/{run_id}/artifacts", "artifacts")
    by_name = {}
    for artifact in artifacts:
        require(artifact["name"] not in by_name, "Ambiguous artifact names")
        by_name[artifact["name"]] = artifact
    selections, partitions, errors, seen, gates = [], [], [], set(), []
    for job in jobs:
        if job["name"] == gate:
            gates.append({k: job[k] for k in ("id", "status", "conclusion")})
        match = re.fullmatch(prefix+r"-(\d+)-partition-(\d+)", job["name"])
        if not match:
            continue
        actual_model, index = map(int, match.groups())
        require(actual_model == model and 0 <= index < count and index not in seen,
                "Unexpected or duplicate partition job")
        require(job["run_id"] == run_id, "Partition job belongs to another run")
        seen.add(index)
        selections.append({"index": index, **{k: job[k] for k in ("id", "status", "conclusion")}})
        if job["status"] != "completed":
            continue
        try:
            partitions.append(download_partition(github, by_name[job["name"]], job, run, model, index, directory,
                                                 control_plan=control_plan))
        except Exception as error:
            errors.append({"index": index, "error": f"{type(error).__name__}: {error}"})
    complete = [row for row in partitions if row["complete_arrays_audited"]]
    status = "waiting_for_partitions" if selections else "waiting_for_test_gate"
    if gates and gates[0]["status"] == "completed" and gates[0]["conclusion"] != "success":
        status = "test_gate_failed"
    if run["status"] == "completed" and len(seen) != count and status != "test_gate_failed":
        status = "incomplete_job_inventory"
    if len(partitions) == count:
        status = "incomplete_execution"
    result = {"purpose": __doc__, "run_id": run_id, "run_attempt": run["run_attempt"], "model": model,
              "producer_revision": run["head_sha"], "github_status": run["status"], "github_conclusion": run["conclusion"],
              "expected_partitions": count, "test_gate": gates, "jobs": selections,
              "partitions": sorted(partitions, key=lambda row: row["index"]), "collection_errors": errors,
              "status": status, "complete_original_failure_coverage": False,
              "needs_continuation": sorted(row["index"] for row in partitions if not row["complete_arrays_audited"]),
              "missing_artifact_indices": sorted(set(range(count)) - {row["index"] for row in partitions}),
              "case_recovery_claimed": False, "integrations_performed": 0, "workflows_dispatched": 0, "checked_at": now()}
    if control_plan is not None:
        result.update(scope="paired-case-controls", case_plan_sha256=signature(control_plan), complete_control_coverage=False)
    if len(complete) == count:
        try:
            audit = completed_audit([Path(row["directory"]) for row in complete], control_plan, allow_partial=False)
            audit_path = directory / ("full-failure-inventory-audit.json" if control_plan is None else "control-inventory-audit.json")
            write_json(audit_path, audit)
            if control_plan is None:
                result.update(status="all_partition_arrays_audited", complete_original_failure_coverage=True,
                              full_protocol_branches=audit["full_protocol_branches"],
                              precision_converged_branches=audit["precision_converged_branches"],
                              native_agreeing_branches=audit["native_agreeing_branches"],
                              baseline_status=audit["baseline_status"], audit=str(audit_path))
            else:
                result.update(status="all_control_arrays_audited", complete_control_coverage=True,
                              full_protocol_branches=len(complete),
                              missing_case_branch_ids=audit["missing_branch_ids"], audit=str(audit_path))
        except Exception as error:
            result.update(status="audit_error", error=f"{type(error).__name__}: {error}")
    write_json(directory / "collection.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="m9h/GRN_ODE")
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--model", type=int, choices=(35, 39), required=True)
    parser.add_argument("--control-plan", type=Path, help="Collect the complementary control workflow using this exact plan")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=45.)
    args = parser.parse_args()
    require(args.run > 0 and 1 <= args.interval <= 60, "Positive run ID and 1–60 second poll interval required")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    control_plan = json.loads(args.control_plan.read_text()) if args.control_plan else None
    previous = None
    with (args.output / ".collector.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                result = collect_run(GitHub(args.repository), args.run, args.model, args.output, control_plan=control_plan)
                summary = {k: result[k] for k in ("run_id", "model", "status", "complete_original_failure_coverage",
                                                  "needs_continuation", "missing_artifact_indices", "collection_errors")}
                if control_plan is not None:
                    summary.update(scope="paired-case-controls", complete_control_coverage=result["complete_control_coverage"])
            except Exception as error:
                summary = {"run_id": args.run, "error": f"{type(error).__name__}: {error}"}
            write_json(args.output / "status.json", {"checked_at": now(), **summary})
            if summary != previous:
                print(json.dumps(summary), flush=True)
                previous = summary
            if not args.watch:
                return int("error" in summary or bool(summary.get("collection_errors")) or summary.get("status") == "audit_error")
            time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
