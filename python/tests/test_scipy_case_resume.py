"""Synthetic cache and artifact fixtures; none are biochemical result evidence."""

from copy import deepcopy
import json

import pytest

from grn_memory.scipy_breaking_recovery import digest
from grn_memory.scipy_case_partitions import validate_cached_branches
from scripts.restore_scipy_case_partition import validate_artifact
from test_scipy_breaking_controls import compute, synthetic, use_copasi


@pytest.fixture
def cached(tmp_path, synthetic):
    use_copasi(synthetic)
    entry = compute(tmp_path, synthetic)
    metadata, grid, spec, info, _ = synthetic
    report = {"metadata": {"experiment": metadata, "fingerprint": metadata["fingerprint"],
                            "selected_branch_ids": ["synthetic"]},
              "branches": [entry], "status": "completed"}
    inventory = {"branches": {"synthetic": spec}}
    return tmp_path, report, inventory, grid, info


def test_every_completed_array_is_verified_before_resume(cached):
    assert validate_cached_branches(*cached) == {"verified_branch_records": 1, "verified_complete_arrays": 4}


@pytest.mark.parametrize("change", ["array", "record", "engine", "request", "traces", "missing_record"])
def test_tampered_cache_is_rejected_before_any_integration(cached, change):
    directory, report, inventory, grid, info = cached
    path = directory / "synthetic.json"
    record = json.loads(path.read_text())
    if change == "array":
        (directory / record["traces"]["copasi"]["file"]).write_bytes(b"changed")
    elif change == "missing_record":
        path.unlink()
    else:
        if change == "record":
            record["fingerprint"] = "different"
        elif change == "engine":
            record["integrations"]["copasi"]["native_engine"] = "roadrunner"
        elif change == "request":
            record["integrations"]["scipy"]["request"]["rtol"] = 1e-3
        else:
            del record["traces"]["copasi"]
        path.write_text(json.dumps(record))
        report["branches"][0]["sha256"] = digest(path)
    with pytest.raises(ValueError):
        validate_cached_branches(directory, report, inventory, grid, info)


def test_only_the_active_interrupted_branch_may_have_an_updated_record(cached):
    directory, report, *_ = cached
    path = directory / "synthetic.json"
    record = json.loads(path.read_text())
    record["interrupted_attempt_note"] = "Synthetic progress checkpoint after report checkpoint"
    path.write_text(json.dumps(record))
    report["status"] = "running"
    with pytest.raises(ValueError, match="digest differs"):
        validate_cached_branches(*cached)
    report["active_branch"] = "synthetic"
    assert validate_cached_branches(*cached)["verified_complete_arrays"] == 4
    report["status"] = "completed"
    with pytest.raises(ValueError, match="digest differs"):
        validate_cached_branches(*cached)


@pytest.fixture
def artifact():
    run = {"id": 42, "head_sha": "a" * 40, "status": "completed"}
    job = {"status": "completed", "started_at": "2026-11-16T01:00:00+00:00"}
    asset = {"name": "expected", "expired": False, "workflow_run": {"id": 42, "head_sha": "a" * 40},
             "created_at": "2026-11-16T02:00:00+00:00", "digest": "sha256:" + "b" * 64}
    return asset, run, job, "expected"


def test_completed_artifact_identity_is_accepted(artifact):
    validate_artifact(*artifact)


@pytest.mark.parametrize("change", ["name", "expired", "run", "revision", "old_attempt", "live", "no_digest"])
def test_wrong_or_incomplete_parent_artifact_is_rejected(artifact, change):
    asset, run, job, name = deepcopy(artifact)
    if change == "name":
        asset["name"] = "other-partition"
    elif change == "expired":
        asset["expired"] = True
    elif change == "run":
        asset["workflow_run"]["id"] += 1
    elif change == "revision":
        asset["workflow_run"]["head_sha"] = "c" * 40
    elif change == "old_attempt":
        asset["created_at"] = "2026-11-15T02:00:00+00:00"
    elif change == "live":
        run["status"] = "in_progress"
    else:
        del asset["digest"]
    with pytest.raises(ValueError):
        validate_artifact(asset, run, job, name)
