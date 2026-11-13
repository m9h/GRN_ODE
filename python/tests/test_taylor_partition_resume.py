"""Remote checkpoints must retain their original producer and full protocol."""

from argparse import Namespace
from copy import deepcopy
import importlib.util
import json
import shutil
import stat
import zipfile

import numpy as np
import pytest

hy = pytest.importorskip("heyoka")
from grn_memory import taylor_checkpoints as checkpoints
from grn_memory import taylor_partitions as runner
from grn_memory import taylor_partition_resume as resume
from grn_memory import taylor_reference as adapter
from test_taylor_partitions import toy, run

spec = importlib.util.spec_from_file_location("precision_ci", runner.ROOT / "scripts/run_taylor_ci_partition.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class FakeGitHub:
    repository = "m9h/GRN_ODE"

    def __init__(self, directory, archive):
        self.directory, self.archive = directory, archive
        self.run = {"id": 123, "run_attempt": 1, "head_sha": "a"*40,
                    "path": ".github/workflows/precision-checkpoints.yml"}
        self.job = {"id": 456, "run_id": 123, "name": "precision-model-35-partition-1", "status": "completed",
                    "conclusion": "failure", "started_at": "2026-11-13T06:00:00Z"}
        self.artifact = {"id": 789, "name": self.job["name"], "expired": False, "workflow_run": self.run.copy(),
                         "created_at": "2026-11-13T07:00:00Z"}
        self.pack()

    def pack(self):
        with zipfile.ZipFile(self.archive, "w") as stream:
            for path in self.directory.rglob("*"):
                if path.is_file() and not path.name.endswith(".lock"):
                    stream.write(path, path.relative_to(self.directory).as_posix())
        self.artifact["digest"] = "sha256:" + runner.digest(self.archive)

    def api(self, endpoint):
        assert endpoint == "actions/runs/123"
        return deepcopy(self.run)

    def rows(self, endpoint, field):
        if field == "jobs":
            assert endpoint == "actions/runs/123/attempts/1/jobs"
            return [deepcopy(self.job)]
        assert endpoint == "actions/runs/123/artifacts"
        return [deepcopy(self.artifact)]

    def download(self, artifact_id, output):
        assert artifact_id == 789
        shutil.copyfile(self.archive, output)


@pytest.fixture
def artifact(toy, monkeypatch):
    monkeypatch.setattr(resume, "problem", runner.problem)
    original = adapter.taylor_trajectory
    def interrupt(*args, **kwargs):
        if kwargs["precision"] == 192:
            kwargs["stop_after_segments"] = 1
        return original(*args, **kwargs)
    monkeypatch.setattr(adapter, "taylor_trajectory", interrupt)
    assert run(toy)["status"] == "checkpointed"
    monkeypatch.setattr(adapter, "taylor_trajectory", original)
    parent = toy.parent / "parent"
    parent.mkdir()
    shutil.copytree(toy, parent / "evidence")
    execution = {"schema": 1, "run_id": 123, "run_attempt": 1, "head_sha": "a"*40, "model": 35,
                 "partition_index": 1, "partition_count": 2, "evidence_directory": "evidence",
                 "status": "checkpointed", "source_provenance": {"source_revision": "a"*40,
                 "implementation_files_differing_from_revision": []}}
    (parent / "execution.json").write_text(json.dumps(execution))
    return FakeGitHub(parent, toy.parent / "artifact.zip"), toy.parent / "restored"


def test_restore_checks_partial_state_without_performing_integration(artifact, monkeypatch):
    github, output = artifact
    def forbidden(*args, **kwargs):
        raise AssertionError("Artifact restoration must not integrate")
    monkeypatch.setattr(hy, "taylor_adaptive", forbidden)
    provenance = resume.restore(github, 123, 35, 1, 2, output)
    assert provenance["integrations_performed"] == 0
    assert provenance["validation"]["completed_integrations"] == ["taylor128"]
    assert provenance["validation"]["checkpoints"]["taylor192"]["completed_segments"] == 1
    assert (output / "taylor128.npz").read_bytes() == (github.directory / "evidence/taylor128.npz").read_bytes()
    assert len(json.loads((output / "restore-provenance.json").read_text())["history"]) == 1
    with pytest.raises(ValueError, match="must not exist"):
        resume.restore(github, 123, 35, 1, 2, output)


@pytest.mark.parametrize("change", ["active_job", "old_artifact", "expired", "wrong_head", "wrong_run", "digest", "execution", "missing_trace", "checkpoint_counts", "checkpoint_source", "checkpoint_checksum", "missing_checkpoint"])
def test_invalid_artifacts_are_rejected_before_publication(artifact, change):
    github, output = artifact
    evidence = github.directory / "evidence"
    if change == "active_job": github.job["status"] = "in_progress"
    elif change == "old_artifact": github.artifact["created_at"] = "2026-11-12T06:00:00Z"
    elif change == "expired": github.artifact["expired"] = True
    elif change == "wrong_head": github.artifact["workflow_run"]["head_sha"] = "b"*40
    elif change == "wrong_run": github.artifact["workflow_run"]["id"] = 124
    elif change == "digest": github.artifact["digest"] = "sha256:" + "0"*64
    else:
        if change == "execution":
            path = github.directory / "execution.json"
            value = json.loads(path.read_text()); value["partition_index"] = 0
            path.write_text(json.dumps(value))
        elif change == "missing_trace": (evidence / "taylor128.npz").unlink()
        elif change == "missing_checkpoint": (evidence / "taylor192-checkpoint.npz").unlink()
        else:
            path = evidence / "taylor192-checkpoint.npz"
            with np.load(path, allow_pickle=False) as data:
                metadata = json.loads(str(data["metadata"]))
                observations = data["observations"].copy()
            if change == "checkpoint_counts": metadata["evidence"]["performed_resets"] = 99
            elif change == "checkpoint_source": metadata["identity"]["sources"]["adapter"] = "changed"
            else: metadata["state"][0] = "99"
            if change != "checkpoint_checksum":
                metadata.pop("payload_sha256")
                metadata["payload_sha256"] = checkpoints.signature(metadata)
            np.savez_compressed(path, metadata=np.asarray(json.dumps(metadata)), observations=observations)
        github.pack()
    with pytest.raises((ValueError, FileNotFoundError)):
        resume.restore(github, 123, 35, 1, 2, output)
    assert not output.exists()


def test_interrupted_report_may_lag_a_valid_atomic_checkpoint(artifact):
    github, output = artifact
    path = github.directory / "evidence/report.json"
    report = json.loads(path.read_text())
    report["status"] = "running"
    report["integrations"]["taylor192"] = {"completed": False}
    path.write_text(json.dumps(report))
    github.pack()
    result = resume.restore(github, 123, 35, 1, 2, output)
    assert result["validation"]["reported_status"] == "running"
    completed = run(output, resume=True)
    assert completed["status"] == "completed" and completed["diagnostic_status"] == "confirmed"
    assert completed["integrations"]["taylor192"]["resumed_from_checkpoint_segments"] == 1


def test_completed_artifact_can_be_restored_without_checkpoints(artifact):
    github, output = artifact
    directory = github.directory / "evidence"
    run(directory, resume=True)
    for label in ("taylor128", "taylor192"):
        (directory / (label + "-checkpoint.npz")).unlink()
    github.pack()
    result = resume.restore(github, 123, 35, 1, 2, output)
    assert set(result["validation"]["completed_integrations"]) == set(runner.REQUESTS)
    assert not result["validation"]["checkpoints"]
    assert run(output, resume=True)["status"] == "completed"


@pytest.mark.parametrize("member,mode", [("../escape", 0), ("/absolute", 0), ("evidence/linked", stat.S_IFLNK), ("evidence/report.tmp", 0)])
def test_archive_layout_rejects_paths_links_and_temporary_files(tmp_path, member, mode):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as stream:
        entry = zipfile.ZipInfo(member)
        entry.external_attr = mode << 16
        stream.writestr(entry, "bad")
    with pytest.raises(ValueError):
        resume.extract(path, tmp_path / "unpacked")


def test_ci_wrapper_restores_and_preserves_parent_identity(artifact, monkeypatch):
    github, destination = artifact
    for key, value in {"GITHUB_RUN_ID": "999", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "b"*40}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ci, "source_provenance", lambda: {"source_revision": "b"*40,
                        "implementation_files_differing_from_revision": []})
    args = Namespace(output=destination, model=35, partition_index=1, partition_count=2, resume_run=123, max_seconds=30.)
    assert ci.execute(args, github) == 0
    record = json.loads((destination / "execution.json").read_text())
    assert record["run_id"] == 999 and record["head_sha"] == "b"*40
    assert record["restoration"]["parent_run_id"] == 123 and record["restoration"]["parent_revision"] == "a"*40
    report = json.loads((destination / "evidence/report.json").read_text())
    assert report["attempts"][-1]["reused_integrations"] == ["taylor128"]
    assert record["status"] == "completed" and record["diagnostic_status"] == "confirmed"


def test_ci_wrapper_retains_failure_without_false_completion(toy, monkeypatch):
    for key, value in {"GITHUB_RUN_ID": "999", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "b"*40}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ci, "source_provenance", lambda: {"source_revision": "b"*40,
                        "implementation_files_differing_from_revision": []})
    args = Namespace(output=toy.parent / "ci", model=35, partition_index=1, partition_count=1, resume_run=None, max_seconds=30.)
    with pytest.raises(ValueError, match="toy partition"):
        ci.execute(args)
    record = json.loads((args.output / "execution.json").read_text())
    assert record["status"] == "execution_error" and "finished_at" in record
    assert not (args.output / "evidence/report.json").exists()


def test_ci_wrapper_rejects_sources_outside_the_dispatched_commit(toy, monkeypatch):
    for key, value in {"GITHUB_RUN_ID": "999", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "b"*40}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(ci, "source_provenance", lambda: {"source_revision": "b"*40,
                        "implementation_files_differing_from_revision": ["grn_memory/taylor_reference.py"]})
    args = Namespace(output=toy.parent / "ci", model=35, partition_index=1, partition_count=2, resume_run=None, max_seconds=30.)
    with pytest.raises(ValueError, match="dispatched commit"):
        ci.execute(args)
    assert not (args.output / "evidence").exists()
