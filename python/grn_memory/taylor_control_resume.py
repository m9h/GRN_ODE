"""Restore a declared paired-case control only from its completed parent job."""

from datetime import datetime
import json
from pathlib import Path
import re
import tempfile

from .catalog_memory import write_json
from .taylor_case_controls import problem, validate_evidence, verify_committed_sources
from .taylor_checkpoints import signature
from .taylor_partition_resume import extract
from .taylor_partitions import digest, now, require

WORKFLOW = ".github/workflows/precision-case-controls.yml"


def restore(github, run_id, plan, index, count, output):
    require(type(run_id) is int and run_id > 0, "Positive parent workflow run ID required")
    _, _, _, core, _ = problem(plan, index, count)
    output = Path(output)
    require(not output.exists(), "Resume destination must not exist")
    run = github.api(f"actions/runs/{run_id}")
    require(run["id"] == run_id and re.fullmatch(r"[0-9a-f]{40}", run["head_sha"])
            and type(run["run_attempt"]) is int and run["run_attempt"] > 0
            and run["path"] == WORKFLOW, "Unexpected parent workflow")
    model = int(plan["model_id"].removeprefix("BIOMD"))
    name = f"precision-control-model-{model}-partition-{index}"
    jobs = [row for row in github.rows(f"actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs", "jobs")
            if row["name"] == name]
    require(len(jobs) == 1 and jobs[0]["status"] == "completed" and jobs[0]["run_id"] == run_id,
            "A completed matching parent job is required")
    job = jobs[0]
    artifacts = [row for row in github.rows(f"actions/runs/{run_id}/artifacts", "artifacts") if row["name"] == name]
    require(len(artifacts) == 1, "A unique matching artifact is required")
    artifact = artifacts[0]
    require(not artifact["expired"] and artifact["workflow_run"]["id"] == run_id
            and artifact["workflow_run"]["head_sha"] == run["head_sha"]
            and datetime.fromisoformat(artifact["created_at"]) >= datetime.fromisoformat(job["started_at"]),
            "Artifact does not belong to this parent job attempt")
    archive_digest = artifact.get("digest", "")
    require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", archive_digest)), "Artifact SHA-256 is required")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="control-restore-", dir=output.parent) as temporary:
        staging = Path(temporary)
        archive = staging/"download.zip"
        github.download(artifact["id"], archive)
        require(digest(archive) == archive_digest.removeprefix("sha256:"), "Downloaded archive SHA-256 differs")
        extract(archive, staging/"unpacked")
        execution = json.loads((staging/"unpacked/execution.json").read_text())
        expected = {"schema": 1, "scope": "paired-case-controls", "run_id": run_id,
                    "run_attempt": run["run_attempt"], "head_sha": run["head_sha"], "model": model,
                    "partition_index": index, "partition_count": count, "evidence_directory": "evidence",
                    "case_plan_sha256": signature(plan), "implementation_sha256": core["implementation_sha256"]}
        require(all(execution.get(k) == v for k, v in expected.items()), "Artifact execution identity differs")
        require(execution.get("source_provenance") == {"source_revision": run["head_sha"],
                "implementation_files_differing_from_revision": []}, "Artifact sources differ from producer")
        verify_committed_sources(run["head_sha"], tuple(sorted(core["implementation_sha256"].items())))
        source = staging/"unpacked/evidence"
        validation = validate_evidence(source, plan, index, count, resume=True)
        history_path = source/"restore-provenance.json"
        history = json.loads(history_path.read_text())["history"] if history_path.exists() else []
        provenance = {"restored_at": now(), "repository": github.repository, "parent_run_id": run_id,
                      "parent_run_attempt": run["run_attempt"], "parent_revision": run["head_sha"],
                      "parent_job_id": job["id"], "parent_job_conclusion": job["conclusion"],
                      "artifact_id": artifact["id"], "archive_sha256": archive_digest,
                      "execution_sha256": digest(staging/"unpacked/execution.json"), "validation": validation,
                      "case_plan_sha256": signature(plan), "restore_script_sha256": digest(Path(__file__)),
                      "integrations_performed": 0}
        write_json(history_path, {"history": [*history, provenance]})
        source.rename(output)
    return provenance
