"""Migration must preserve the original prefix and reject unrelated producers."""

import json
import shutil

import numpy as np
import pytest

hy = pytest.importorskip("heyoka")
from grn_memory import taylor_checkpoint_migration as migration
from grn_memory import taylor_checkpoints as checkpoints
from grn_memory import taylor_partitions as runner
from grn_memory import taylor_partition_resume as resume
from grn_memory import taylor_reference as adapter
from test_taylor_checkpoints import alter, saved
from test_taylor_partitions import toy, run
from test_taylor_partition_resume import FakeGitHub


@pytest.fixture
def legacy(toy, monkeypatch):
    monkeypatch.setattr(migration, "problem", runner.problem)
    monkeypatch.setattr(resume, "problem", runner.problem)
    original = adapter.taylor_trajectory
    def interrupted(*args, **kwargs):
        kwargs["stop_after_segments"] = 1
        return original(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(adapter, "taylor_trajectory", interrupted)
        assert run(toy)["status"] == "checkpointed"
    path = toy / "report.json"
    report = json.loads(path.read_text())
    report["core"] = migration.legacy_core(report["core"])
    report["fingerprint"] = checkpoints.signature({key: report[key] for key in ("core", "environment", "selection")})
    path.write_text(json.dumps(report))
    def old(metadata, observations):
        metadata["schema"] = 1
        metadata["identity"] = migration.legacy_identity(metadata["identity"])
        metadata["identity_sha256"] = checkpoints.signature(metadata["identity"])
        return observations
    alter(toy / "taylor128-checkpoint.npz", old)
    return toy


def test_explicit_migration_preserves_original_bytes_and_resumes(legacy, monkeypatch):
    original_report = (legacy / "report.json").read_bytes()
    original_checkpoint = (legacy / "taylor128-checkpoint.npz").read_bytes()
    with pytest.raises(ValueError, match="source"):
        run(legacy, resume=True)
    def forbidden(*args, **kwargs):
        raise AssertionError("Migration must not integrate")
    with monkeypatch.context() as patch:
        patch.setattr(hy, "taylor_adaptive", forbidden)
        record = migration.migrate(legacy, 35, 1, 2)
    assert record["integrations_performed"] == 0
    assert (legacy / "legacy-report.json").read_bytes() == original_report
    assert (legacy / "legacy-taylor128-checkpoint.npz").read_bytes() == original_checkpoint
    assert saved(legacy / "taylor128-checkpoint.npz")[0]["schema"] == 2
    completed = run(legacy, resume=True)
    assert completed["status"] == "completed" and completed["diagnostic_status"] == "confirmed"
    assert completed["integrations"]["taylor128"]["resumed_from_checkpoint_segments"] == 1
    migration.verify_migration(legacy, completed)
    expected = legacy.parent / "reference"
    run(expected)
    for label in runner.REQUESTS:
        with np.load(legacy / (label + ".npz")) as a, np.load(expected / (label + ".npz")) as b:
            np.testing.assert_array_equal(a["values"], b["values"])


@pytest.mark.parametrize("change", ["source", "model", "environment", "state", "prefix", "completed"])
def test_migration_rejects_invalid_legacy_evidence_before_writing(legacy, change):
    path = legacy / "report.json"
    report = json.loads(path.read_text())
    if change == "source": report["core"]["implementation_sha256"]["grn_memory/taylor_reference.py"] = "unknown"
    elif change == "model": report["core"]["model_sha256"] = "changed"
    elif change == "environment": report["environment"]["versions"]["heyoka"] = "changed"
    elif change == "completed": report["status"] = "completed"
    else:
        def corrupt(metadata, observations):
            if change == "state": metadata["state"][0] = "nan"
            else: return observations[:-1]
            return observations
        alter(legacy / "taylor128-checkpoint.npz", corrupt)
    report["fingerprint"] = checkpoints.signature({key: report[key] for key in ("core", "environment", "selection")})
    path.write_text(json.dumps(report))
    before = {p.name: p.read_bytes() for p in legacy.iterdir() if p.is_file()}
    with pytest.raises(ValueError):
        migration.migrate(legacy, 35, 1, 2)
    assert before == {p.name: p.read_bytes() for p in legacy.iterdir() if p.is_file()}


@pytest.mark.parametrize("change", ["old_state", "converted_state", "current_prefix", "missing_manifest", "wrong_manifest"])
def test_migration_lineage_checked_on_every_resume(legacy, change):
    migration.migrate(legacy, 35, 1, 2)
    if change in ("old_state", "converted_state"):
        path = legacy / ("legacy-taylor128-checkpoint.npz" if change == "old_state" else "segment-start-checkpoint.npz")
        def corrupt(metadata, observations):
            metadata["state"][0] = "9"
            return observations
        alter(path, corrupt)
        manifest_path = legacy / "checkpoint-migration.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][path.name] = runner.digest(path)
        manifest_path.write_text(json.dumps(manifest))
        report_path = legacy / "report.json"
        report = json.loads(report_path.read_text())
        report["checkpoint_migration"]["sha256"] = runner.digest(manifest_path)
        report_path.write_text(json.dumps(report))
    elif change == "current_prefix":
        def corrupt(metadata, observations):
            observations[0, 0] += 1
            return observations
        alter(legacy / "taylor128-checkpoint.npz", corrupt)
    elif change == "missing_manifest":
        (legacy / "checkpoint-migration.json").unlink()
    else:
        (legacy / "checkpoint-migration.json").write_text("{}")
    with pytest.raises((ValueError, FileNotFoundError)):
        run(legacy, resume=True)


def test_download_requires_explicit_migration_and_preserves_lineage_on_next_restore(legacy):
    parent = legacy.parent / "parent"
    parent.mkdir()
    shutil.copytree(legacy, parent / "evidence")
    execution = {"schema": 1, "run_id": 123, "run_attempt": 1, "head_sha": "a"*40,
                 "model": 35, "partition_index": 1, "partition_count": 2, "evidence_directory": "evidence",
                 "source_provenance": {"source_revision": "a"*40, "implementation_files_differing_from_revision": []}}
    (parent / "execution.json").write_text(json.dumps(execution))
    github = FakeGitHub(parent, legacy.parent / "artifact.zip")
    output = legacy.parent / "restored"
    with pytest.raises(ValueError, match="source"):
        resume.restore(github, 123, 35, 1, 2, output)
    assert not output.exists()
    result = resume.restore(github, 123, 35, 1, 2, output, migrate_segments=True)
    assert result["integrations_performed"] == 0
    migration.verify_migration(output, json.loads((output / "report.json").read_text()))
    # The next archive contains the retained legacy evidence. Normal restoration
    # must validate it without migrating the already converted state again.
    shutil.copytree(output, parent / "evidence", dirs_exist_ok=True)
    github.pack()
    second = legacy.parent / "second-restoration"
    resume.restore(github, 123, 35, 1, 2, second)
    assert run(second, resume=True)["status"] == "completed"
