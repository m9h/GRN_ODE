"""Inventory coverage and rejection tests; no numerical integration."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from scripts import prepare_ciliberto_full_inventory as inventory
from scripts import plan_ciliberto_full_computation as scheduling


def real_inputs():
    reference = inventory.read(inventory.ROOT / "results/catalog-repeated/BIOMD0000000697.json")
    plans = inventory.candidate_plans(reference)
    original = inventory.read(inventory.SOURCE / "shard-0/BIOMD0000000697.json")
    summaries = inventory.read(inventory.SOURCE / "audit.json")["case_summaries"]
    return plans, summaries, reference, original["configuration"]


def test_published_complete_two_case_inventory_reproduces():
    plans, summaries, reference, config = real_inputs()
    published = inventory.read(inventory.ROOT / "results/catalog-breaking-ciliberto-case-recovery-20261118/inventory.json")
    selected = {key: summaries[key] for key in published["cases"]}
    cases, branches, baseline = inventory.build_inventory(plans, selected, reference, config)
    assert len(branches) == 215
    assert branches == published["branches"]
    assert baseline == published["full_untreated_control"]
    for key, case in cases.items():
        assert {k: v for k, v in case.items() if k != "original_summary"} == published["cases"][key]


def test_all_74_failed_cases_selected_without_source_trial_dependency():
    plans, summaries, reference, config = real_inputs()
    # The compiler receives aggregate summaries, not the recorded conditional
    # paths. Incomplete original paths therefore cannot truncate new controls.
    original = deepcopy((plans, summaries, reference, config))
    cases, branches, baseline = inventory.build_inventory(plans, summaries, reference, config)
    assert len(cases) == 74
    assert set(cases) == {key for key, row in summaries.items() if row["status"] != "passed"}
    assert all(len(case["potential_trials"]) > 2 for case in cases.values())
    assert all(len(trial["branches"]) == 8 for case in cases.values() for trial in case["potential_trials"].values())
    assert baseline in branches and branches[baseline]["stop"] == 2210.0
    assert (plans, summaries, reference, config) == original


def test_ambiguous_original_engine_eligibility_rejected():
    plans, summaries, reference, config = real_inputs()
    key = next(key for key, row in summaries.items() if row["status"] != "passed")
    response = next(iter(plans[key]["responses"]))
    plans[key]["responses"][response]["copasi"] = {"unexpected": True}
    with pytest.raises(ValueError, match="eligibility differs"):
        inventory.build_inventory(plans, summaries, reference, config)


def test_frozen_full_inventory_matches_all_candidates_and_two_stage_plan():
    inputs = inventory.ROOT / "results/catalog-breaking-ciliberto-full-inventory-20261118"
    saved = inventory.read(inputs / "inventory.json")
    plans, summaries, reference, config = real_inputs()
    cases, branches, baseline = inventory.build_inventory(plans, summaries, reference, config)
    assert saved["cases"] == cases
    assert saved["branches"] == branches
    assert saved["full_untreated_control"] == baseline
    assert len(branches) == 7334
    plan = scheduling.make_plan(saved, inventory.digest(inputs / "inventory.json"))
    assert plan == inventory.read(inputs / "computation-plan.json")
    partitions = plan["stage_1"]["partitions"]
    selected = [key for part in partitions for key in part["branch_ids"]]
    assert len(selected) == len(set(selected)) == 260
    assert {len(part["branch_ids"]) for part in partitions} == {8, 9}


def test_missing_control_cannot_be_removed_from_scheduling_scope():
    inputs = inventory.ROOT / "results/catalog-breaking-ciliberto-full-inventory-20261118"
    saved = inventory.read(inputs / "inventory.json")
    saved["remaining_branch_ids"].pop()
    with pytest.raises(ValueError, match="inventory differs"):
        scheduling.make_plan(saved, "unused-in-this-test")


def transport_fixture(tmp_path, monkeypatch, *, members=None, expected=None, metadata_valid=True):
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(inventory, "SOURCE", source)
    default_name = "catalog-breaking-linux-28/shard-0/evidence/data.gz"
    members = [(default_name, b"evidence", "file")] if members is None else members
    expected = {default_name: b"evidence"} if expected is None else expected
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, payload, kind in members:
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            if kind == "symlink":
                member.type, member.linkname, member.size = tarfile.SYMTYPE, "elsewhere", 0
                tar.addfile(member)
            else:
                tar.addfile(member, io.BytesIO(payload))
    manifest = {"sha256": inventory.digest(archive), "bytes": archive.stat().st_size,
                "members": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                            for name, data in expected.items()}}
    inventory.write(source / "download.json", manifest)
    metadata = source / "shard-0/shard.json"
    metadata.parent.mkdir()
    metadata.write_text("{}\n")
    inventory.write(source / "source-artifacts.json", {"partitions": [{"shard_index": 0,
        "copied_metadata_sha256": {"shard.json": inventory.digest(metadata) if metadata_valid else "wrong"}}]})
    return archive


def test_transport_checks_every_member_and_original_metadata(tmp_path, monkeypatch):
    archive = transport_fixture(tmp_path, monkeypatch)
    result = inventory.extract_verified(archive, tmp_path / "out")
    assert result["verified_members"] == result["metadata_partitions"] == 1
    assert (tmp_path / "out/catalog-breaking-linux-28/shard-0/shard.json").read_text() == "{}\n"


@pytest.mark.parametrize("members,expected,message", [
    ([("../escape", b"bad", "file")], {"../escape": b"bad"}, "Unsafe archive path"),
    ([("unexpected", b"data", "file")], {}, "Unexpected"),
    ([("a", b"data", "file"), ("a", b"data", "file")], {"a": b"data"}, "duplicate"),
    ([("a", b"", "symlink")], {"a": b""}, "nonregular"),
    ([("a", b"same", "file")], {"a": b"else"}, "checksum"),
    ([], {"absent": b"data"}, "Incomplete archive"),
])
def test_transport_rejects_invalid_evidence(tmp_path, monkeypatch, members, expected, message):
    archive = transport_fixture(tmp_path, monkeypatch, members=members, expected=expected)
    with pytest.raises(ValueError, match=message):
        inventory.extract_verified(archive, tmp_path / "out")


def test_metadata_change_rejected(tmp_path, monkeypatch):
    archive = transport_fixture(tmp_path, monkeypatch, metadata_valid=False)
    with pytest.raises(ValueError, match="Tracked original metadata differs"):
        inventory.extract_verified(archive, tmp_path / "out")


def test_archive_change_rejected_before_extraction(tmp_path, monkeypatch):
    archive = transport_fixture(tmp_path, monkeypatch)
    with archive.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="archive checksum"):
        inventory.extract_verified(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()
