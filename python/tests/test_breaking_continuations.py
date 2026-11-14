"""Continuation assembly requires complete coverage and exact source artifacts."""

import copy
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from scripts import audit_breaking_continuations as assembly


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path/"collections"
    original = assembly.ROOT/"results/catalog-breaking-linux-27"
    collections, selections, directories = {}, [], []
    for index in range(4):
        run, artifact_id, job_id = 100+index//2, 200+index, 300+index
        collection_dir = root/str(run)/"attempt-1"
        artifact_dir = collection_dir/f"artifact-{artifact_id}"
        directory = artifact_dir/"evidence"
        shutil.copytree(original/f"shard-{index}", directory)
        manifest = assembly.read(directory/"shard.json")
        archive = artifact_dir/"download.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as stream:
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    stream.write(path, str(path.relative_to(directory)))
        selection = {"shard_index": index, "run_id": run, "run_attempt": 1,
                     "job_id": job_id, "producer_revision": manifest["git_revision"]}
        selections.append(selection)
        collection = collections.setdefault(run, {
            "run_id": run, "run_attempt": 1, "producer_revision": manifest["git_revision"],
            "networks": {"27": {"jobs": [], "partitions": []}}})
        network = collection["networks"]["27"]
        network["jobs"].append({"index": index, "id": job_id, "status": "completed", "conclusion": "success"})
        network["partitions"].append({"directory": str(directory), "artifact_id": artifact_id,
            "archive_sha256": "sha256:"+assembly.digest(archive),
            "manifest_sha256": assembly.digest(directory/"shard.json"),
            "shard_index": index, "shard_count": 4, "selected_coverage_complete": True})
        directories.append(directory)
    for run, collection in collections.items():
        (root/str(run)/"attempt-1/collection.json").write_text(json.dumps(collection))
    plan = {"schema_version": 1, "network": 27, "model_id": "BIOMD0000000275",
            "shard_count": 4, "expected_model_cases": 22, "partitions": selections}
    report = assembly.read(original/"shard-0/BIOMD0000000275.json")
    manifest = assembly.read(original/"shard-0/shard.json")
    sources = {"grn_memory/"+name: sha for name, sha in report["implementation_sha256"].items()}
    sources.update({"scripts/run_breaking_shard.py": manifest["runner_sha256"],
                    "grn_memory/breaking_shards.py": manifest["partition_source_sha256"]})
    def source_hash(revision, name):
        assert revision == manifest["git_revision"]
        return sources[name]
    # Represent the recorded source checkout in shallow CI. A separate real
    # artifact CLI smoke verifies actual historical Git objects before release.
    monkeypatch.setattr(assembly.auditor, "source_hash", source_hash)
    return plan, root, directories


def change_collection(root, mutate):
    path = root/"100/attempt-1/collection.json"
    value = assembly.read(path)
    mutate(value)
    path.write_text(json.dumps(value))


def test_real_model_across_two_runs_keeps_complete_partition_evidence(fixture):
    plan, root, directories = fixture
    result = assembly.evaluate(plan, [root])
    assert result["status"] == "passed" and result["all_numerical_validations_passed"]
    assert result["complete_case_coverage"] and result["model_audit"]["cases"] == 22
    assert result["model_audit"]["partition_count"] == 4
    assert result["model_audit"]["branch_records_across_partitions"] == 301
    assert result["model_audit"]["distinct_branch_specifications"] == 260
    assert [p["directory"] for p in result["model_audit"]["partitions"]] == list(map(str, directories))
    assert len(result["verified_artifacts"]) == 4
    assert all(p["verified_files"] > 0 for p in result["verified_artifacts"])
    assert result["numerical_integrations_performed"] == result["workflow_dispatches_performed"] == 0


@pytest.mark.parametrize("change", ["missing", "duplicate", "case_count", "job"])
def test_invalid_plan_cannot_reduce_or_overlap_model_coverage(fixture, change):
    plan, root, _ = fixture
    plan = copy.deepcopy(plan)
    if change == "missing":
        plan["partitions"].pop()
    elif change == "duplicate":
        plan["partitions"][-1]["shard_index"] = 0
    elif change == "case_count":
        plan["expected_model_cases"] = 21
    else:
        plan["partitions"][-1]["job_id"] = plan["partitions"][0]["job_id"]
    with pytest.raises(ValueError):
        assembly.evaluate(plan, [root])


def test_running_or_missing_jobs_never_reach_the_model_auditor(fixture, monkeypatch):
    plan, root, _ = fixture
    def unexpected(*args):
        raise AssertionError("Partial inventory reached full-model auditor")
    monkeypatch.setattr(assembly.auditor, "audit", unexpected)
    change_collection(root, lambda c: c["networks"]["27"]["jobs"][0].update(status="in_progress", conclusion=None))
    result = assembly.evaluate(plan, [root])
    assert result["status"] == "waiting_for_partitions" and result["pending_indices"] == [0]
    assert not result["complete_case_coverage"] and "model_audit" not in result
    result = assembly.evaluate(plan, [root/"not-present"])
    assert result["pending_indices"] == [0, 1, 2, 3]
    assert not result["all_numerical_validations_passed"]


def test_completed_job_without_artifact_is_explicitly_pending(fixture):
    plan, root, _ = fixture
    change_collection(root, lambda c: c["networks"]["27"]["partitions"].pop(0))
    result = assembly.evaluate(plan, [root])
    assert result["status"] == "waiting_for_partitions"
    assert result["partition_states"][0]["state"] == "completed_job_missing_artifact"
    assert result["pending_indices"] == [0]


def test_timeout_requests_continuation_without_promoting_partial_results(fixture):
    plan, root, _ = fixture
    change_collection(root, lambda c: c["networks"]["27"]["partitions"][0].update(selected_coverage_complete=False))
    result = assembly.evaluate(plan, [root])
    assert result["status"] == "incomplete_execution" and result["needs_continuation_indices"] == [0]
    assert not result["complete_case_coverage"] and not result["all_numerical_validations_passed"]


@pytest.mark.parametrize("change,message", [("job", "job identity"), ("revision", "run identity"),
                                           ("count", "partition count"), ("duplicate_artifact", "Ambiguous selected artifact")])
def test_collector_identity_must_match_the_fixed_plan(fixture, change, message):
    plan, root, _ = fixture
    def mutate(c):
        network = c["networks"]["27"]
        if change == "job":
            network["jobs"][0]["id"] += 1000
        elif change == "revision":
            c["producer_revision"] = "0"*40
        elif change == "count":
            network["partitions"][0]["shard_count"] = 8
        else:
            network["partitions"].append(network["partitions"][0])
    change_collection(root, mutate)
    with pytest.raises(ValueError, match=message):
        assembly.evaluate(plan, [root])


@pytest.mark.parametrize("change", ["changed_member", "missing_member", "extra_member", "changed_zip"])
def test_extracted_data_must_match_the_original_zip(fixture, change):
    plan, root, directories = fixture
    directory = directories[0]
    if change == "changed_member":
        path = directory/"shard.json"
        path.write_bytes(path.read_bytes().replace(b"selected_cases_passed", b"selected_cases_failed"))
    elif change == "missing_member":
        (directory/"shard.json").unlink()
    elif change == "extra_member":
        (directory/"unrecorded.txt").write_text("not original evidence")
    else:
        path = directory.parent/"download.zip"
        path.write_bytes(path.read_bytes()+b"changed")
    with pytest.raises(ValueError, match="artifact|Artifact|extracted"):
        assembly.evaluate(plan, [root])


def test_two_possible_collection_sources_are_rejected(fixture, tmp_path):
    plan, root, _ = fixture
    second = tmp_path/"other"
    shutil.copytree(root, second)
    with pytest.raises(ValueError, match="Ambiguous collection source"):
        assembly.evaluate(plan, [root, second])


def test_selected_artifacts_still_require_the_original_source_provenance(fixture, monkeypatch):
    plan, root, _ = fixture
    monkeypatch.setattr(assembly.auditor, "source_hash", lambda *args: "0"*64)
    with pytest.raises(ValueError, match="source differs"):
        assembly.evaluate(plan, [root])
