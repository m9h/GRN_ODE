"""Finer partitions inherit verified histories without inventing coverage."""

import gzip
import fcntl
import json
from pathlib import Path
import shutil

import pytest

from grn_memory import breaking_resume as resume
from grn_memory.catalog_archive import EvidenceStore
from scripts.audit_breaking_shards import read_archives


@pytest.fixture
def source(tmp_path, monkeypatch):
    original = resume.ROOT/"results/catalog-breaking-linux-27/shard-0"
    source = tmp_path/"source"
    shutil.copytree(original, source)
    manifest = json.loads((source/"shard.json").read_text())
    report = json.loads((source/(manifest["model_id"]+".json")).read_text())
    store = EvidenceStore(source, manifest["model_id"], report["fingerprint"])
    for kind in ("branches", "cases"):
        for key, row in read_archives(source, report, kind).items():
            store.put(kind, key, row)
    # The fixture represents the recorded producer environment. The real CLI
    # smoke run additionally checks the current files and installed versions.
    monkeypatch.setattr(resume, "runtime_source_hash", lambda name: report["implementation_sha256"][name])
    monkeypatch.setattr(resume, "version", lambda package: report["versions"][package])
    return source


def test_children_preserve_the_parent_selection_and_checkpoint_bytes(source, tmp_path):
    parent = json.loads((source/"shard.json").read_text())
    before = {str(p.relative_to(source)): resume.digest(p) for p in source.rglob("*") if p.is_file()}
    children = []
    for index in (0, 1):
        output = tmp_path/f"child-{index}"
        result = resume.prepare(source, output, 27, index, 8)
        children.extend(result["case_keys"])
        assert result["copied_checkpoints"] == 45+len(result["case_keys"])
        assert result["validated_branch_checkpoints"] == 45
        assert result["validated_case_checkpoints"] == len(result["case_keys"])
        assert result["examined_case_checkpoints"] == 5
        assert result["preserved_case_checkpoints"] == 5-len(result["case_keys"])
        assert result["numerical_integrations_performed"] == 0 and not result["model_completion_claimed"]
        assert not (output/"shard.json").exists()
        for relative, sha in result["copied_checkpoint_sha256"].items():
            assert resume.digest(output/relative) == sha == before[relative]
        for relative, history in result["preserved_case_history"].items():
            assert history["reason"] == "outside_new_selection"
            assert resume.digest(output/history["preserved_path"]) == history["sha256"] == before[relative]
            assert not (output/relative).exists()
    assert children == parent["case_keys"] and len(children) == len(set(children))
    assert before == {str(p.relative_to(source)): resume.digest(p) for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("index,count", [(2, 8), (0, 3), (0, 2)])
def test_wrong_parent_or_incompatible_partition_count_is_rejected(source, tmp_path, index, count):
    with pytest.raises(ValueError):
        resume.prepare(source, tmp_path/"child", 27, index, count)


def test_running_source_cannot_be_repartitioned(source, tmp_path):
    path = source/"shard.json"; manifest = json.loads(path.read_text()); manifest["status"] = "running"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="must have stopped"):
        resume.prepare(source, tmp_path/"child", 27, 0, 8)


def test_active_source_lock_is_respected_even_with_an_old_terminal_manifest(source, tmp_path):
    with (source/".shard.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="still in use"):
            resume.prepare(source, tmp_path/"child", 27, 0, 8)


def case_checkpoint(source, *, selected=True):
    manifest = json.loads((source/"shard.json").read_text())
    reference = json.loads((resume.ROOT/"results/catalog-repeated"/(manifest["model_id"]+".json")).read_text())
    selection = resume.select_cases(resume.candidate_plans(reference), 0, 8)
    for path in sorted(source.glob(".evidence/*/*/cases-*.json.gz")):
        with gzip.open(path, "rt") as stream:
            case = json.load(stream)
        if (case["case_key"] in selection) == selected:
            return path, case
    raise AssertionError("Fixture does not contain a suitable case")


def write_checkpoint(path, row):
    with gzip.open(path, "wt") as stream:
        json.dump(row, stream)


def test_missing_branch_invalidates_a_cached_complete_case(source, tmp_path):
    case_path, case = case_checkpoint(source)
    branch = next(iter(case["trials"]["first"]["branches"].values()))
    (case_path.parent/("branches-"+branch+".json.gz")).unlink()
    with pytest.raises(ValueError, match="branch evidence is missing"):
        resume.prepare(source, tmp_path/"child", 27, 0, 8)
    assert not (tmp_path/"child").exists()


@pytest.mark.parametrize("selected,passed", [(False, False), (False, True), (True, False)])
def test_stale_unused_aggregate_is_preserved_but_not_reused(source, tmp_path, selected, passed):
    path, case = case_checkpoint(source, selected=selected)
    case["passed"] = passed
    case["trials"]["first"]["scores"] = {}  # Simulate an older branch snapshot.
    write_checkpoint(path, case)
    original_bytes = path.read_bytes()
    output = tmp_path/"child"
    result = resume.prepare(source, output, 27, 0, 8)
    relative = str(path.relative_to(source))
    history = result["preserved_case_history"][relative]
    assert history["reason"] == ("failed_case_requires_recomputation" if selected else "outside_new_selection")
    assert (output/history["preserved_path"]).read_bytes() == original_bytes == path.read_bytes()
    assert not (output/relative).exists()
    assert result["validated_case_checkpoints"] == len(result["case_keys"])-int(selected)
    assert result["numerical_integrations_performed"] == 0 and not result["model_completion_claimed"]


def test_selected_passing_case_must_still_reproduce_its_scores(source, tmp_path):
    path, case = case_checkpoint(source)
    case["trials"]["first"]["scores"] = {}
    write_checkpoint(path, case)
    with pytest.raises(ValueError, match="Trial scores do not reproduce"):
        resume.prepare(source, tmp_path/"child", 27, 0, 8)
    assert not (tmp_path/"child").exists()


@pytest.mark.parametrize("field,value", [("case_key", "other"), ("ucs", "other"), ("passed", "false")])
def test_omitted_case_must_have_valid_identity_and_outcome(source, tmp_path, field, value):
    path, case = case_checkpoint(source, selected=False)
    case[field] = value
    write_checkpoint(path, case)
    with pytest.raises(ValueError, match="Checkpoint case"):
        resume.prepare(source, tmp_path/"child", 27, 0, 8)
    assert not (tmp_path/"child").exists()


def test_truncated_checkpoint_horizon_is_rejected(source, tmp_path):
    path = next(source.glob(".evidence/*/*/branches-*.json.gz"))
    with gzip.open(path, "rt") as stream:
        row = json.load(stream)
    row["sample_count"] -= 1
    with gzip.open(path, "wt") as stream:
        json.dump(row, stream)
    with pytest.raises(ValueError, match="horizon is incomplete"):
        resume.prepare(source, tmp_path/"child", 27, 0, 8)


def test_changed_worker_or_packages_are_rejected(source, tmp_path, monkeypatch):
    original = resume.runtime_source_hash
    monkeypatch.setattr(resume, "runtime_source_hash", lambda name: "0"*64)
    with pytest.raises(ValueError, match="worker source differs"):
        resume.prepare(source, tmp_path/"child", 27, 0, 8)
    monkeypatch.setattr(resume, "runtime_source_hash", original)
    monkeypatch.setattr(resume, "version", lambda package: "changed")
    with pytest.raises(ValueError, match="package versions differ"):
        resume.prepare(source, tmp_path/"child", 27, 0, 8)


def test_existing_output_is_never_overwritten(source, tmp_path):
    output = tmp_path/"child"; output.mkdir(); (output/"keep").write_text("original")
    with pytest.raises(ValueError, match="already exist"):
        resume.prepare(source, output, 27, 0, 8)
    assert (output/"keep").read_text() == "original"


def test_empty_child_does_not_copy_or_claim_unused_computations(source, tmp_path):
    output = tmp_path/"child"
    result = resume.prepare(source, output, 27, 0, 128)
    assert result["case_keys"] == [] and result["copied_checkpoints"] == 0
    assert not (output/".evidence").exists() and not result["model_completion_claimed"]
