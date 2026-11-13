"""Collection preserves incomplete artifacts and requires full audited coverage."""

from copy import deepcopy
import importlib.util
import json
import shutil

import pytest

pytest.importorskip("heyoka")
from grn_memory import taylor_partitions as runner
from test_taylor_partitions import toy, run
from test_taylor_partition_resume import artifact, FakeGitHub

spec = importlib.util.spec_from_file_location("precision_collector", runner.ROOT / "scripts/collect_taylor_runs.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


@pytest.fixture
def collected(artifact, monkeypatch):
    github, output = artifact
    monkeypatch.setattr(collector, "PARTITIONS", {35: 2})
    monkeypatch.setattr(collector, "problem", runner.problem)
    monkeypatch.setattr(collector.auditor, "problem", runner.problem)
    github.run.update(status="completed", conclusion="failure")
    original_rows = github.rows
    def rows(endpoint, field):
        result = original_rows(endpoint, field)
        if field == "jobs":
            result.insert(0, {"name": "precision-checkpoints", "id": 111, "status": "completed", "conclusion": "success"})
        return result
    monkeypatch.setattr(github, "rows", rows)
    return github, output.parent / "collected"


def test_partial_artifacts_are_preserved_without_completeness_claim(collected, monkeypatch):
    github, root = collected
    result = collector.collect_run(github, 123, 35, root)
    assert not result["complete_original_failure_coverage"] and not result["case_recovery_claimed"]
    assert result["missing_artifact_indices"] == [0] and result["needs_continuation"] == [1]
    assert result["partitions"][0]["reported_status"] == "checkpointed"
    assert result["partitions"][0]["completed_integrations"] == ["taylor128"]
    assert result["partitions"][0]["checkpoint_validation"] == "deferred to matching runtime on resume"
    def forbidden(*args):
        raise AssertionError("Immutable artifact must not be downloaded twice")
    monkeypatch.setattr(github, "download", forbidden)
    assert not collector.collect_run(github, 123, 35, root)["collection_errors"]


def test_extracted_evidence_is_rechecked_against_immutable_archive(collected):
    github, root = collected
    collector.collect_run(github, 123, 35, root)
    path = root / "123/attempt-1/artifact-789/payload/execution.json"
    value = json.loads(path.read_text()); value["extra"] = "changed after extraction"
    path.write_text(json.dumps(value))
    result = collector.collect_run(github, 123, 35, root)
    assert not result["complete_original_failure_coverage"]
    assert "Extracted evidence differs" in result["collection_errors"][0]["error"]


def test_full_inventory_is_audited_even_when_job_conclusion_is_failure(collected, monkeypatch):
    github, root = collected
    run(github.directory / "evidence", resume=True)
    github.pack()
    baseline = github.directory.parent / "baseline-payload"
    baseline.mkdir()
    run(baseline / "evidence", index=0)
    execution = json.loads((github.directory / "execution.json").read_text())
    execution["partition_index"] = 0
    (baseline / "execution.json").write_text(json.dumps(execution))
    other = FakeGitHub(baseline, baseline.parent / "baseline.zip")
    other.job.update(id=457, name="precision-model-35-partition-0")
    other.artifact.update(id=790, name=other.job["name"])
    def rows(endpoint, field):
        return ([{"name": "precision-checkpoints", "id": 111, "status": "completed", "conclusion": "success"},
                 deepcopy(github.job), deepcopy(other.job)] if field == "jobs" else
                [deepcopy(github.artifact), deepcopy(other.artifact)])
    def download(artifact_id, output):
        shutil.copyfile(github.archive if artifact_id == 789 else other.archive, output)
    monkeypatch.setattr(github, "rows", rows)
    monkeypatch.setattr(github, "download", download)
    result = collector.collect_run(github, 123, 35, root)
    assert not result["collection_errors"]
    assert result["complete_original_failure_coverage"] and result["status"] == "all_partition_arrays_audited"
    assert result["full_protocol_branches"] == result["native_agreeing_branches"] == 1
    assert result["baseline_status"] == "confirmed" and not result["case_recovery_claimed"]


def test_failed_test_gate_does_not_claim_numerical_failure(collected, monkeypatch):
    github, root = collected
    monkeypatch.setattr(github, "rows", lambda endpoint, field: [
        {"name": "precision-checkpoints", "id": 111, "status": "completed", "conclusion": "failure"}
    ] if field == "jobs" else [])
    result = collector.collect_run(github, 123, 35, root)
    assert result["status"] == "test_gate_failed" and result["partitions"] == []
    assert not result["complete_original_failure_coverage"] and not result["case_recovery_claimed"]
