"""Collection integrity fixtures; no simulated biochemical results are asserted."""

from copy import deepcopy
import json
from pathlib import Path
import zipfile

import pytest

from scripts import collect_scipy_case_partitions as collector


@pytest.fixture
def selection(tmp_path):
    path = tmp_path / "execution-plan.json"
    path.write_text("{}")
    plan = {"model_id": "BIOMD0000000069", "shard_count": 2}
    value = {"schema_version": 1, "model_id": plan["model_id"], "partition_count": 2,
             "execution_plan_sha256": collector.digest(path), "partitions": [
                 {"shard_index": i, "run_id": 42, "run_attempt": 1,
                  "producer_revision": "a" * 40, "job_id": 100 + i} for i in range(2)]}
    return value, path, plan


def test_fixed_complete_selection(selection):
    collector.validate_selection(*selection)


@pytest.mark.parametrize("change", ["missing", "duplicate", "job", "plan", "revision", "attempt"])
def test_changed_selection_rejected(selection, change):
    value, path, plan = deepcopy(selection)
    if change == "missing":
        value["partitions"].pop()
    elif change == "duplicate":
        value["partitions"][1]["shard_index"] = 0
    elif change == "job":
        value["partitions"][1]["job_id"] = 100
    elif change == "plan":
        value["execution_plan_sha256"] = "b" * 64
    elif change == "revision":
        value["partitions"][0]["producer_revision"] = "main"
    else:
        value["partitions"][0]["run_attempt"] = 0
    with pytest.raises(ValueError):
        collector.validate_selection(value, path, plan)


@pytest.fixture
def identity(selection):
    value, _, _ = selection
    row = value["partitions"][0]
    run = {"id": 42, "run_attempt": 1, "head_sha": "a" * 40, "status": "in_progress",
           "path": ".github/workflows/scipy-case-controls.yml"}
    job = {"id": 100, "run_id": 42, "run_attempt": 1, "head_sha": "a" * 40,
           "name": "scipy-case-partition-0", "status": "completed", "conclusion": "failure",
           "started_at": "2026-11-16T01:00:00Z", "completed_at": "2026-11-16T03:00:00Z"}
    artifact = {"id": 99, "name": "scipy-cases-BIOMD0000000069-partition-0-attempt-1",
                "expired": False, "workflow_run": {"id": 42, "head_sha": "a" * 40},
                "created_at": "2026-11-16T02:59:00Z", "digest": "sha256:" + "b" * 64}
    return artifact, row, run, job, value["model_id"]


def test_completed_failed_job_can_be_collected_during_live_matrix(identity):
    collector.validate_artifact(*identity)


@pytest.mark.parametrize("change", ["job", "attempt", "revision", "workflow", "live_job", "artifact",
                                   "expired", "artifact_run", "predates", "postdates", "digest"])
def test_wrong_artifact_or_attempt_rejected(identity, change):
    artifact, row, run, job, model = deepcopy(identity)
    if change == "job":
        job["id"] = 101
    elif change == "attempt":
        run["run_attempt"] = 2
    elif change == "revision":
        job["head_sha"] = "c" * 40
    elif change == "workflow":
        run["path"] = "other.yml"
    elif change == "live_job":
        job["status"] = "in_progress"
    elif change == "artifact":
        artifact["name"] += "-different"
    elif change == "expired":
        artifact["expired"] = True
    elif change == "artifact_run":
        artifact["workflow_run"]["id"] = 43
    elif change == "predates":
        artifact["created_at"] = "2026-11-16T00:59:00Z"
    elif change == "postdates":
        artifact["created_at"] = "2026-11-16T03:01:00Z"
    else:
        artifact["digest"] = None
    with pytest.raises(ValueError):
        collector.validate_artifact(artifact, row, run, job, model)


def test_partial_results_never_enable_case_audit(selection):
    value, _, _ = selection
    partial = [{"shard_index": i, "complete_selected_inventory": False} for i in range(2)]
    result = collector.summarize(value, partial, [], [], [])
    assert result["status"] == "terminal_incomplete"
    assert result["all_selected_jobs_terminal"]
    assert result["needs_continuation"] == [0, 1]
    assert not result["complete_selected_inventory"]
    assert not result["case_recovery_claimed"]
    complete = [{**row, "complete_selected_inventory": True} for row in partial]
    assert collector.summarize(value, complete, [], [], [])["status"] == "ready_for_case_audit"
    assert collector.summarize(value, complete[:1], [1], [], [])["status"] == "collecting"
    assert collector.summarize(value, complete[:1], [], [1], [])["status"] == "terminal_incomplete"
    assert collector.summarize(value, complete, [], [], ["bad hash"])["status"] == "verification_failed"


def test_zip_binds_extracted_bytes_and_rejects_extra_files(tmp_path):
    archive, evidence = tmp_path / "download.zip", tmp_path / "evidence"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("report.json", '{"synthetic":true}')
        stream.writestr("nested/array.npz", b"synthetic bytes")
    collector.extract(archive, evidence)
    hashes = collector.verify_extraction(archive, evidence)
    assert set(hashes) == {"report.json", "nested/array.npz"}
    extra = evidence / "extra.json"
    extra.write_text("{}")
    with pytest.raises(ValueError, match="Unexpected extracted"):
        collector.verify_extraction(archive, evidence)
    extra.unlink()
    (evidence / "nested/array.npz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes differ"):
        collector.verify_extraction(archive, evidence)


def test_repeated_watch_uses_verified_cache_but_detects_change(tmp_path, identity, monkeypatch):
    artifact, row, run, job, model = identity
    payload = tmp_path / "original.zip"
    with zipfile.ZipFile(payload, "w") as stream:
        stream.writestr("report.json", "{}")
    artifact.update(digest="sha256:" + collector.digest(payload), size_in_bytes=payload.stat().st_size)
    class GitHub:
        def download(self, artifact_id, output):
            assert artifact_id == 99
            output.write_bytes(payload.read_bytes())
    checks = []
    def verify(*args):
        checks.append(True)
        return {"producer_status": "checkpointed", "verified_complete_arrays": 0, "audited_branches": []}
    monkeypatch.setattr(collector, "verify_partition", verify)
    cache, root = {}, tmp_path / "collection"
    args = (GitHub(), artifact, row, run, job, tmp_path, ({"model_id": model},), root, cache)
    first = collector.collect_partition(*args)
    assert collector.collect_partition(*args) == first
    assert len(checks) == 1
    # A fresh process revalidates the ZIP and extracted bytes rather than trusting a receipt.
    assert collector.collect_partition(*args[:-1], {}) == first
    assert len(checks) == 2
    (Path(first["directory"]) / "report.json").write_text("changed")
    with pytest.raises(ValueError, match="changed during watch"):
        collector.collect_partition(*args)
