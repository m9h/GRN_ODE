"""Verify and restore precision artifacts without performing integration."""

from datetime import datetime
import json
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import zipfile

import numpy as np

from . import taylor_checkpoints as checkpoints
from .catalog_memory import write_json
from .native_protocols import ResetTrain
from .taylor_partitions import (ROOT, REQUESTS, assess, digest, environment, load_trace,
                                now, problem, require, verify_report_identity)


class GitHub:
    def __init__(self, repository):
        require(bool(re.fullmatch(r"[\w.-]+/[\w.-]+", repository)), "Specify one owner/repository")
        self.repository = repository

    def api(self, endpoint):
        result = subprocess.run(["gh", "api", f"repos/{self.repository}/{endpoint}"],
                                check=True, capture_output=True, text=True)
        return json.loads(result.stdout)

    def rows(self, endpoint, field):
        rows, page = [], 1
        while True:
            result = self.api(f"{endpoint}?per_page=100&page={page}")
            rows.extend(result[field])
            if len(result[field]) < 100:
                return rows
            page += 1

    def download(self, artifact_id, output):
        with output.open("wb") as stream:
            subprocess.run(["gh", "api", f"repos/{self.repository}/actions/artifacts/{artifact_id}/zip"],
                           check=True, stdout=stream, stderr=subprocess.PIPE)


def validate_checkpoint(path, info, times, selection, label):
    """Check exact state, observation prefix and schedule counters, with no JIT."""
    import heyoka as hy
    import libsbml
    import platform
    from . import taylor_reference as adapter

    request = REQUESTS[label]
    precision = request["precision"]
    real = lambda value: hy.real(value, precision)
    tolerance = str(real(request["tolerance"]))
    trains = selection["reset_trains"]
    counts = [len(ResetTrain(**t).indices()) if t["values"] else 0 for t in trains]
    events = {}
    for index, train in enumerate(trains):
        if train["values"]:
            for when in ResetTrain(**train).times():
                events.setdefault(float(when), {"trains": []})["trains"].append(index)
    edges = np.r_[0., sorted(events), times[-1]]
    identity = {"model_sha256": info["sha256"], "precision_bits": precision, "tolerance": tolerance,
                "observables": info["observables"], "times_sha256": selection["times_sha256"], "samples": len(times),
                "trains": trains, "high_accuracy": True, "compact_mode": True,
                "numeric_inputs": "binary64 values promoted exactly",
                "sources": {"adapter": digest(adapter.__file__), "checkpoints": digest(checkpoints.__file__)},
                "environment": {"heyoka": hy.__version__, "numpy": np.__version__,
                                "libsbml": libsbml.getLibSBMLDottedVersion(), "python": platform.python_version(),
                                "system": platform.system(), "machine": platform.machine()}}
    expected = {"request": request, "times_sha256": selection["times_sha256"],
                "model_sha256": info["sha256"], "precision_bits": precision, "tolerance": tolerance,
                "high_accuracy": True, "numeric_inputs": identity["numeric_inputs"], "absolute_time_preserved": True,
                "expected_resets": len(events), "expected_train_reset_counts": counts,
                "expected_segments": len(edges)-1, "sample_count": len(times), "observables": info["observables"]}
    _, observations, evidence = checkpoints.load(path, identity, times, edges, events, expected, real)
    return {"sha256": digest(path), "completed_segments": evidence["completed_segments"],
            "saved_samples": len(observations), "completed": evidence["completed"]}


def validate_evidence(directory, model, index, count):
    _, info, times, core, selection = problem(model, index, count)
    report = json.loads((directory / "report.json").read_text())
    verify_report_identity(report, core, selection)
    require(report["environment"] == environment(), "Resume environment differs")
    require(report["status"] in ("running", "completed", "checkpointed", "budget_exhausted", "integration_failed"),
            "Unknown partition state")
    require(set(report["traces"]) <= set(REQUESTS) and set(report["integrations"]) <= set(REQUESTS),
            "Unexpected integration inventory")
    traces = {label: load_trace(directory, report, label, info, times) for label in report["traces"]}
    if report["status"] == "completed":
        require(set(traces) == set(REQUESTS) and all(report.get(k) == v for k, v in assess(traces).items()),
                "Completed partition does not reproduce")
    verified = {}
    for label in ("taylor128", "taylor192"):
        path = directory / (label + "-checkpoint.npz")
        if path.exists():
            verified[label] = validate_checkpoint(path, info, times, selection, label)
        if report["integrations"].get(label, {}).get("interruption"):
            require(label in verified, "Interrupted integration is missing its checkpoint")
    return {"report_sha256": digest(directory / "report.json"), "completed_integrations": list(traces),
            "checkpoints": verified, "reported_status": report["status"], "case_recovery_claimed": False}


def extract(archive, output):
    """Only the workflow's explicit report/array layout may be restored."""
    allowed = {"execution.json", "evidence/report.json", "evidence/restore-provenance.json", "evidence/audit.json"}
    allowed.update("evidence/" + label + ".npz" for label in REQUESTS)
    allowed.update("evidence/" + label + "-checkpoint.npz" for label in ("taylor128", "taylor192"))
    with zipfile.ZipFile(archive) as stream:
        seen = set()
        for entry in stream.infolist():
            require(entry.filename not in seen and not stat.S_ISLNK(entry.external_attr >> 16),
                    "Duplicate or linked artifact member")
            seen.add(entry.filename)
            require(entry.filename in allowed or entry.is_dir() and entry.filename == "evidence/",
                    "Unexpected artifact member")
        stream.extractall(output)


def restore(github, run_id, model, index, count, output):
    """Publish a restored directory only after archive and numerical checks pass."""
    require(type(run_id) is int and run_id > 0, "Positive parent workflow run ID required")
    output = Path(output)
    require(not output.exists(), "Resume destination must not exist")
    run = github.api(f"actions/runs/{run_id}")
    require(run["id"] == run_id and re.fullmatch(r"[0-9a-f]{40}", run["head_sha"])
            and type(run["run_attempt"]) is int and run["run_attempt"] > 0
            and run["path"] == ".github/workflows/precision-checkpoints.yml", "Unexpected parent workflow")
    name = f"precision-model-{model}-partition-{index}"
    jobs = [row for row in github.rows(f"actions/runs/{run_id}/attempts/{run['run_attempt']}/jobs", "jobs") if row["name"] == name]
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
    with tempfile.TemporaryDirectory(prefix="precision-restore-", dir=output.parent) as temporary:
        staging = Path(temporary)
        archive = staging / "download.zip"
        github.download(artifact["id"], archive)
        require(digest(archive) == archive_digest.removeprefix("sha256:"), "Downloaded archive SHA-256 differs")
        extract(archive, staging / "unpacked")
        execution = json.loads((staging / "unpacked/execution.json").read_text())
        required = {"schema": 1, "run_id": run_id, "run_attempt": run["run_attempt"], "head_sha": run["head_sha"],
                    "model": model, "partition_index": index, "partition_count": count, "evidence_directory": "evidence"}
        require(all(execution.get(k) == v for k, v in required.items()), "Artifact execution identity differs")
        require(execution.get("source_provenance") == {"source_revision": run["head_sha"],
                "implementation_files_differing_from_revision": []}, "Artifact numerical sources differ from the producer commit")
        source = staging / "unpacked/evidence"
        validation = validate_evidence(source, model, index, count)
        history_path = source / "restore-provenance.json"
        history = json.loads(history_path.read_text())["history"] if history_path.exists() else []
        provenance = {"restored_at": now(), "repository": github.repository, "parent_run_id": run_id,
                      "parent_run_attempt": run["run_attempt"], "parent_revision": run["head_sha"],
                      "parent_job_id": job["id"], "parent_job_conclusion": job["conclusion"],
                      "artifact_id": artifact["id"], "archive_sha256": archive_digest,
                      "execution_sha256": digest(staging / "unpacked/execution.json"), "validation": validation,
                      "restore_script_sha256": digest(Path(__file__)), "integrations_performed": 0}
        write_json(history_path, {"history": [*history, provenance]})
        source.rename(output)
    return provenance
