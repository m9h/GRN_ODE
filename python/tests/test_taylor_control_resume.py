"""Control artifacts preserve the declared cases and exact numerical checkpoints."""

from argparse import Namespace
import importlib.util
import json

import pytest

hy = pytest.importorskip("heyoka")
from grn_memory import taylor_case_controls as controls
from grn_memory import taylor_control_resume as resume
from grn_memory import taylor_partitions as runner
from test_taylor_partitions import toy
from test_taylor_partition_resume import artifact

spec = importlib.util.spec_from_file_location("control_ci", runner.ROOT/"scripts/run_taylor_control_ci.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


@pytest.fixture
def control_artifact(artifact, monkeypatch):
    github, destination = artifact
    plan = {"model_id": "BIOMD0000000035"}
    def problem(plan, index, count):
        path, info, times, core, selected = runner.problem(35, index, count)
        core["implementation_sha256"] = {}
        return path, info, times, core, selected
    for module in (controls, resume, ci):
        monkeypatch.setattr(module, "problem", problem)
    github.run["path"] = resume.WORKFLOW
    github.job["name"] = "precision-control-model-35-partition-1"
    github.artifact["name"] = github.job["name"]
    path = github.directory/"execution.json"
    execution = json.loads(path.read_text())
    execution.update(scope="paired-case-controls", case_plan_sha256=controls.signature(plan), implementation_sha256={})
    path.write_text(json.dumps(execution))
    path = github.directory/"evidence/report.json"
    report = json.loads(path.read_text())
    report["core"]["implementation_sha256"] = {}
    report["fingerprint"] = controls.signature({k: report[k] for k in ("core", "selection", "environment")})
    path.write_text(json.dumps(report))
    github.pack()
    return github, destination, plan


def test_restore_control_validates_checkpoints_without_integration(control_artifact, monkeypatch):
    github, output, plan = control_artifact
    def forbidden(*a, **kw):
        raise AssertionError("Restoration must not integrate")
    monkeypatch.setattr(hy, "taylor_adaptive", forbidden)
    result = resume.restore(github, 123, plan, 1, 2, output)
    assert result["case_plan_sha256"] == controls.signature(plan)
    assert result["integrations_performed"] == 0
    assert result["validation"]["checkpoints"]["taylor192"]["completed_segments"] == 1
    assert result["validation"]["completed_integrations"] == ["taylor128"]


@pytest.mark.parametrize("change", ["wrong_workflow", "active", "wrong_plan", "wrong_partition", "changed_source", "missing_checkpoint", "missing_array", "digest"])
def test_control_artifact_rejects_misbound_or_incomplete_evidence(control_artifact, change):
    github, output, plan = control_artifact
    if change == "wrong_workflow": github.run["path"] = ".github/workflows/precision-checkpoints.yml"
    elif change == "active": github.job["status"] = "in_progress"
    elif change == "digest": github.artifact["digest"] = "sha256:"+"0"*64
    else:
        if change == "missing_checkpoint": (github.directory/"evidence/taylor192-checkpoint.npz").unlink()
        elif change == "missing_array": (github.directory/"evidence/taylor128.npz").unlink()
        else:
            path = github.directory/"execution.json"
            execution = json.loads(path.read_text())
            if change == "wrong_plan": execution["case_plan_sha256"] = "0"*64
            elif change == "wrong_partition": execution["partition_index"] = 0
            else: execution["implementation_sha256"] = {"changed": "0"*64}
            path.write_text(json.dumps(execution))
        github.pack()
    with pytest.raises((ValueError, FileNotFoundError)):
        resume.restore(github, 123, plan, 1, 2, output)
    assert not output.exists()


def test_ci_control_resumes_and_reuses_complete_precision(control_artifact, monkeypatch):
    github, output, plan = control_artifact
    for key, value in {"GITHUB_RUN_ID": "999", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "b"*40}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ci, "source_provenance", lambda: {"source_revision": "b"*40,
                        "implementation_files_differing_from_revision": []})
    plan_path = output.parent/"control-plan.json"
    plan_path.write_text(json.dumps(plan))
    args = Namespace(plan=plan_path, output=output, partition_index=1, partition_count=2,
                     resume_run=123, max_seconds=30.)
    assert ci.execute(args, github) == 0
    report = json.loads((output/"evidence/report.json").read_text())
    assert report["attempts"][-1]["reused_integrations"] == ["taylor128"]
    assert report["integrations"]["taylor192"]["resumed_from_checkpoint_segments"] == 1
    execution = json.loads((output/"execution.json").read_text())
    assert execution["restoration"]["parent_run_id"] == 123
    assert execution["case_plan_sha256"] == controls.signature(plan)
    assert execution["status"] == "completed"
