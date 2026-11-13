"""Collect every control without confusing control coverage with case recovery."""

from copy import deepcopy
import json
import shutil

import pytest

pytest.importorskip("heyoka")
from grn_memory import taylor_case_controls as controls
from test_taylor_partitions import toy
from test_taylor_partition_resume import artifact, FakeGitHub
from test_taylor_control_resume import control_artifact
from test_collect_taylor_runs import collector


@pytest.fixture
def collected_control(control_artifact, monkeypatch):
    github, destination, plan = control_artifact
    plan["control_branch_ids"] = ["untreated_baseline", "a"*64]
    path = github.directory/"execution.json"
    execution = json.loads(path.read_text())
    execution["case_plan_sha256"] = controls.signature(plan)
    path.write_text(json.dumps(execution))
    github.pack()
    github.run.update(status="completed", conclusion="failure")
    monkeypatch.setattr(controls, "validate_plan", lambda p: 35)
    original_rows = github.rows
    def rows(endpoint, field):
        result = original_rows(endpoint, field)
        if field == "jobs":
            result.insert(0, {"name": "validate", "id": 111, "status": "completed", "conclusion": "success"})
        return result
    monkeypatch.setattr(github, "rows", rows)
    return github, destination.parent/"collected-controls", plan


def test_partial_control_is_preserved_without_case_or_coverage_claim(collected_control):
    github, root, plan = collected_control
    result = collector.collect_run(github, 123, 35, root, control_plan=plan)
    assert not result["collection_errors"]
    assert result["scope"] == "paired-case-controls"
    assert result["needs_continuation"] == [1] and result["missing_artifact_indices"] == [0]
    assert not result["complete_control_coverage"] and not result["case_recovery_claimed"]
    assert not result["complete_original_failure_coverage"]


def test_wrong_case_plan_cannot_reuse_artifact(collected_control):
    github, root, plan = collected_control
    plan["changed"] = True
    result = collector.collect_run(github, 123, 35, root, control_plan=plan)
    assert "execution identity differs" in result["collection_errors"][0]["error"]
    assert not result["complete_control_coverage"]


def test_original_failed_branch_workflow_cannot_supply_control_inventory(collected_control):
    github, root, plan = collected_control
    github.run["path"] = ".github/workflows/precision-checkpoints.yml"
    with pytest.raises(ValueError, match="workflow identity"):
        collector.collect_run(github, 123, 35, root, control_plan=plan)


def test_complete_controls_still_require_failed_training_branches(collected_control, monkeypatch):
    github, root, plan = collected_control
    controls.run_partition(plan, 1, 2, github.directory/"evidence", resume=True)
    github.pack()
    other_directory = github.directory.parent/"other-control"
    other_directory.mkdir()
    controls.run_partition(plan, 0, 2, other_directory/"evidence")
    execution = json.loads((github.directory/"execution.json").read_text())
    execution["partition_index"] = 0
    (other_directory/"execution.json").write_text(json.dumps(execution))
    other = FakeGitHub(other_directory, other_directory.parent/"other-control.zip")
    other.job.update(id=457, name="precision-control-model-35-partition-0")
    other.artifact.update(id=790, name=other.job["name"])
    def rows(endpoint, field):
        return ([{"name": "validate", "id": 111, "status": "completed", "conclusion": "success"},
                 deepcopy(github.job), deepcopy(other.job)] if field == "jobs" else
                [deepcopy(github.artifact), deepcopy(other.artifact)])
    def download(artifact_id, output):
        shutil.copyfile(github.archive if artifact_id == 789 else other.archive, output)
    def audit(directories, supplied_plan, *, allow_partial):
        assert supplied_plan is plan
        # Numerical case auditing is tested against arrays in test_taylor_case_controls.
        reports = [json.loads((directory/"report.json").read_text()) for directory in directories]
        return {"branch_evidence": {r["selection"]["branch_id"]: {"diagnostic_status": "confirmed"} for r in reports},
                "missing_branch_ids": ["still-required-failed-training-branch"]}
    monkeypatch.setattr(github, "rows", rows)
    monkeypatch.setattr(github, "download", download)
    monkeypatch.setattr(collector, "completed_audit", audit)
    result = collector.collect_run(github, 123, 35, root, control_plan=plan)
    assert not result["collection_errors"]
    assert result["status"] == "all_control_arrays_audited" and result["complete_control_coverage"]
    assert result["full_protocol_branches"] == 2
    assert result["missing_case_branch_ids"] == ["still-required-failed-training-branch"]
    assert not result["case_recovery_claimed"] and not result["complete_original_failure_coverage"]
