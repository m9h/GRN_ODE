"""Synthetic transport fixtures; these tests are not experimental evidence."""

from pathlib import Path
import shutil
import zipfile

import numpy as np
import pandas as pd
import pytest

from grn_memory.catalog_memory import write_json
from grn_memory.catalog_validation import comparison
from scripts import collect_ciliberto_evidence as collector

INPUTS = Path(__file__).parents[1] / "results/catalog-breaking-ciliberto-case-recovery-20261118"


def test_collection_requires_all_eighteen_fixed_jobs():
    selection = collector.read(INPUTS / "collection-plan.json")
    plan = collector.read(INPUTS / "recomputation-plan.json")
    collector.validate_selection(selection, plan)
    selection["selected"].pop()
    with pytest.raises(ValueError, match="Every fixed replacement"):
        collector.validate_selection(selection, plan)


def artifact_fixture():
    selection = collector.read(INPUTS / "collection-plan.json")
    row = selection["selected"][0]
    run = {"id": selection["run_id"], "run_attempt": selection["run_attempt"],
           "head_sha": selection["head_sha"], "workflow_id": selection["workflow_id"],
           "path": selection["workflow_path"]}
    job = {"id": row["job_id"], "name": row["job_name"], "run_id": run["id"],
           "head_sha": run["head_sha"], "run_attempt": run["run_attempt"],
           "status": "completed", "started_at": "2026-11-18T06:00:00Z",
           "completed_at": "2026-11-18T06:02:00Z", "conclusion": "failure"}
    artifact = {"name": row["artifact_name"], "expired": False,
                "workflow_run": {"id": run["id"], "head_sha": run["head_sha"]},
                "created_at": "2026-11-18T06:01:00Z", "digest": "sha256:" + "0" * 64}
    return selection, row, run, job, artifact


def test_failed_job_artifact_is_not_discarded():
    collector.validate_artifact(*artifact_fixture())


def test_first_pending_snapshot_creates_status_without_claiming_coverage(tmp_path, monkeypatch):
    selection, _, run, _, _ = artifact_fixture()
    plan = collector.read(INPUTS / "recomputation-plan.json")
    report = collector.read(INPUTS / "report.json")
    monkeypatch.setattr(collector, "load_inputs", lambda *_: (plan, report, {}, None, {}, np.array([0.])))
    snapshots = tmp_path / "api"
    snapshots.mkdir()
    jobs = [{"id": row["job_id"], "name": row["job_name"], "run_id": run["id"],
             "head_sha": run["head_sha"], "run_attempt": run["run_attempt"], "status": "queued"}
            for row in selection["selected"]]
    write_json(snapshots / "run.json", run)
    write_json(snapshots / "jobs.json", {"total_count": 18, "jobs": jobs})
    write_json(snapshots / "artifacts.json", {"total_count": 0, "artifacts": []})
    output = tmp_path / "new-collection"
    status, _ = collector.collect(INPUTS, INPUTS / "collection-plan.json", snapshots, tmp_path, output)
    assert (output / "status.json").is_file()
    assert status["pending_indices"] == list(range(18))
    assert status["branches"] == [] and status["collection_errors"] == []
    assert not status["complete_selected_inventory"] and not status["case_recovery_claimed"]
    assert status["numerical_integrations_performed"] == 0


@pytest.mark.parametrize("change", ["attempt", "head", "time", "name"])
def test_wrong_job_attempt_or_artifact_is_rejected(change):
    selection, row, run, job, artifact = artifact_fixture()
    if change == "attempt":
        job["run_attempt"] += 1
    elif change == "head":
        artifact["workflow_run"]["head_sha"] = "0" * 40
    elif change == "time":
        artifact["created_at"] = "2026-11-18T05:59:00Z"
    else:
        artifact["name"] += "-other"
    with pytest.raises(ValueError):
        collector.validate_artifact(selection, row, run, job, artifact)


def test_restarted_collection_rechecks_extracted_bytes(tmp_path):
    archive, evidence = tmp_path / "original.zip", tmp_path / "evidence"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("record.json", '{"original": true}')
    collector.extract(archive, evidence)
    collector.verify_extraction(archive, evidence)
    (evidence / "record.json").write_text('{"original": false}')
    with pytest.raises(ValueError, match="Extracted artifact bytes differ"):
        collector.verify_extraction(archive, evidence)


def test_unsafe_zip_cannot_write_outside_artifact(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr("../outside.json", "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        collector.extract(archive, tmp_path / "evidence")
    assert not (tmp_path / "outside.json").exists()


@pytest.fixture
def branch_fixture(tmp_path):
    bid = "b" * 64
    row = {"record_id": bid, "index": 0}
    selection = {"execution_plan_sha256": "plan", "original_report_sha256": "original",
                 "head_sha": "a" * 40, "run_id": 123, "run_attempt": 1}
    grid = np.array([0., .5, 1.])
    info = {"observables": ["A"], "sha256": "model"}
    inventory = {"branches": {bid: {"stop": 1., "reset_trains": []}}}
    requests = {label: {"rtol": 1e-10, "atol": 1e-12,
                       **({"method": "Radau"} if label.startswith("scipy") else {})}
                for label in collector.LABELS}
    report = {"branches": [{"record_id": bid, "sha256": "historical"}], "fingerprint": "signature",
              "requests": requests, "acceptance": {"rtol": 2e-5, "atol": 1e-7},
              "implementation_sha256": {"synthetic": "source"}, "versions": {"synthetic": "1"}}
    record = {"record_id": bid, "specification": inventory["branches"][bid],
              "fingerprint": report["fingerprint"], "case_recovery_claimed": False,
              "integrations": {}, "traces": {}, "comparisons": {}, "status": "confirmed"}
    for label in collector.LABELS:
        path = tmp_path / (bid + "-" + label + ".npz")
        np.savez_compressed(path, times=grid, values=np.array([[1.], [2.], [3.]]), observables=["A"])
        record["traces"][label] = {"file": path.name, "sha256": collector.digest(path)}
        outcome = {"request": requests[label], "completed": True, "sample_count": 3, "observables": ["A"]}
        if label.startswith("scipy"):
            outcome.update(backend="scipy.solve_ivp", rhs_backend="Jaxkineticmodel", jacobian="jax.jacfwd",
                           model_sha256="model", method="Radau", rtol=1e-10, atol=1e-12,
                           x64=True, absolute_time_preserved=True, expected_resets=0, performed_resets=0,
                           expected_train_reset_counts=[], train_reset_counts=[], expected_segments=1,
                           completed_segments=1, last_interval=[0., 1.])
        record["integrations"][label] = outcome
    lineage = {"plan_sha256": "plan", "original_report_sha256": "original", "index": 0,
               "record_id": bid, "historical_record_sha256": "historical", "source_revision": "a" * 40,
               "wrapper_sha256": "wrapper", "github_run_id": "123", "github_run_attempt": "1",
               "github_job": "compute", "numerical_implementation_sha256": report["implementation_sha256"],
               "versions": report["versions"], "platform": "synthetic", "machine": "synthetic", "python": "synthetic",
               "byte_identical_restoration_claimed": False, "case_recovery_claimed": False,
               "full_model_coverage_claimed": False, "status": "completed"}

    def save(recompute=True):
        if recompute:
            traces = {}
            for label, saved in record["traces"].items():
                with np.load(tmp_path / saved["file"]) as array:
                    traces[label] = pd.DataFrame({"time": grid, "A": array["values"][:, 0]})
            record["comparisons"] = {a + "_vs_" + b: comparison(traces[a], traces[b], **report["acceptance"])
                                     for i, a in enumerate(collector.LABELS) for b in collector.LABELS[i + 1:]
                                     if a in traces and b in traces}
            record["status"] = ("incomplete" if len(traces) < 4 else "confirmed"
                                if all(c["passed"] for c in record["comparisons"].values()) else "mismatch")
        path = tmp_path / (bid + ".json")
        write_json(path, record)
        lineage["branch"] = {"record_id": bid, "file": path.name, "sha256": collector.digest(path),
                             "status": record["status"]}
        write_json(tmp_path / "lineage.json", lineage)

    save()
    args = (tmp_path, selection, row, report, inventory, info, grid, "wrapper")
    return args, record, lineage, save


def test_complete_arrays_recompute_all_six_comparisons(branch_fixture):
    args, _, _, _ = branch_fixture
    result = collector.verify_branch(*args)
    assert result["complete"] and result["arrays_verified"] == 4
    assert len(result["comparisons"]) == 6 and result["status"] == "confirmed"


def test_final_sample_damage_is_rejected_even_with_new_checksums(branch_fixture):
    args, record, _, save = branch_fixture
    saved = record["traces"]["scipy_refined"]
    path = args[0] / saved["file"]
    np.savez_compressed(path, times=args[6], values=np.array([[1.], [2.], [4.]]), observables=["A"])
    saved["sha256"] = collector.digest(path)
    save(recompute=False)
    with pytest.raises(ValueError, match="does not reproduce"):
        collector.verify_branch(*args)


def test_consistent_numerical_mismatch_is_retained(branch_fixture):
    args, record, _, save = branch_fixture
    saved = record["traces"]["scipy_refined"]
    path = args[0] / saved["file"]
    np.savez_compressed(path, times=args[6], values=np.array([[1.], [2.], [4.]]), observables=["A"])
    saved["sha256"] = collector.digest(path)
    save()
    result = collector.verify_branch(*args)
    assert result["complete"] and result["status"] == "mismatch"


def test_failed_integration_is_retained_without_case_promotion(branch_fixture):
    args, record, _, save = branch_fixture
    record["traces"].pop("scipy_refined")
    record["integrations"]["scipy_refined"] = {
        "request": args[3]["requests"]["scipy_refined"], "completed": False, "error": "Synthetic solver failure"}
    save()
    result = collector.verify_branch(*args)
    assert result["complete"] and result["status"] == "incomplete" and result["arrays_verified"] == 3


def test_running_checkpoint_cannot_count_as_complete(branch_fixture):
    args, _, lineage, save = branch_fixture
    lineage["status"] = "running"
    save()
    assert collector.verify_branch(*args)["complete"] is False


def test_assembly_rejects_partial_inventory_before_copying(tmp_path):
    with pytest.raises(ValueError, match="All 18 fixed replacements"):
        collector.assemble(INPUTS, tmp_path, tmp_path, tmp_path / "assembled",
                           {"complete_selected_inventory": False}, None)
    assert not (tmp_path / "assembled").exists()


def test_assembly_retains_every_replacement_and_never_falls_back_to_old_success(tmp_path, monkeypatch):
    # Tiny byte files exercise transport only. The real numerical auditor is
    # separately tested against saved-array fixtures in test_scipy_breaking_case_audit.
    inputs, preserved, restored, reference = [tmp_path / n for n in ("inputs", "preserved", "restored", "reference")]
    for directory in (inputs, preserved, restored, reference):
        directory.mkdir()
    ids = [f"{i:064x}" for i in range(215)]
    entries = []
    for index, bid in enumerate(ids):
        record = {"record_id": bid, "status": "confirmed", "traces": {}}
        for label in collector.LABELS:
            path = reference / (bid + "-" + label + ".npz")
            path.write_bytes(b"synthetic-old-array")
            record["traces"][label] = {"file": path.name, "sha256": collector.digest(path)}
            if index >= 19 or (index == 16 and label in ("scipy", "scipy_refined")):
                shutil.copyfile(path, preserved / path.name)
            if index == 18:
                shutil.copyfile(path, restored / path.name)
        path = reference / (bid + ".json")
        write_json(path, record)
        entries.append({"record_id": bid, "file": path.name, "sha256": collector.digest(path), "status": "confirmed"})
        if index >= 19 or index == 16:
            shutil.copyfile(path, preserved / path.name)
        if index == 18:
            shutil.copyfile(path, restored / path.name)
    original = {"branches": entries, "confirmed_branches": 215, "finished_at": "historical-time"}
    write_json(preserved / "report.json", original)
    plan = {"selected_branch_ids": ids[:18], "restore_from_release_branch_ids": [ids[18]],
            "original_report_sha256": collector.digest(preserved / "report.json")}
    files = [{"path": p.name, "bytes": p.stat().st_size, "sha256": collector.digest(p)}
             for p in preserved.iterdir()]
    write_json(inputs / "preservation-manifest.json", {"files": files})
    replacements = []
    for index, bid in enumerate(ids[:18]):
        directory = tmp_path / f"replacement-{index}"
        directory.mkdir()
        state = "mismatch" if index == 0 else "incomplete" if index == 16 else "confirmed"
        record = {"record_id": bid, "status": state, "traces": {}}
        for label in collector.LABELS:
            if index == 16 and label == "scipy_refined":
                continue
            path = directory / (bid + "-" + label + ".npz")
            path.write_bytes(b"synthetic-new-array")
            record["traces"][label] = {"file": path.name, "sha256": collector.digest(path)}
        write_json(directory / (bid + ".json"), record)
        write_json(directory / "lineage.json", {"synthetic": True, "status": state})
        replacements.append({"record_id": bid, "evidence": str(directory), "complete": True,
                             "record_sha256": collector.digest(directory / (bid + ".json")),
                             "lineage_sha256": collector.digest(directory / "lineage.json"),
                             "artifact_id": index + 1, "archive_sha256": "synthetic"})
    calls = []

    def audit_transport_result(stage):
        report = collector.read(stage / "report.json")
        assert [r["record_id"] for r in report["branches"]] == ids
        assert report["branches"][0]["status"] == "mismatch"
        assert report["branches"][16]["status"] == "incomplete"
        assert report["confirmed_branches"] == 213
        assert not (stage / (ids[16] + "-scipy_refined.npz")).exists()
        assert collector.digest(stage / "historical-report.json") == plan["original_report_sha256"]
        assert collector.digest(stage / (ids[19] + ".json")) == original["branches"][19]["sha256"]
        assert len(list((stage / "replacement-lineage").glob("*.json"))) == 18
        calls.append(True)
        return {"selected_cases": 2, "recovered_selected_cases": 0, "baseline_passed": True}

    monkeypatch.setattr(collector, "audit_cases", audit_transport_result)
    status = {"complete_selected_inventory": True, "branches": replacements,
              "selection_sha256": "synthetic", "source_snapshot_sha256": {}}
    result = collector.assemble(inputs, preserved, restored, tmp_path / "assembled", status,
                                (plan, original, None, None, None, None))
    assert calls == [True] and result["recovered_selected_cases"] == 0
    assert (preserved / (ids[16] + "-scipy_refined.npz")).read_bytes() == b"synthetic-old-array"
    assert collector.digest(preserved / "report.json") == plan["original_report_sha256"]
