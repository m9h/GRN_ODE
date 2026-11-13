"""A restart must preserve completed integrations and reject altered evidence."""

from copy import deepcopy
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("heyoka")
from grn_memory import taylor_partitions as runner
from grn_memory import taylor_reference as adapter
from grn_memory.catalog_validation import inspect_model
from test_taylor_reference import decay

spec = importlib.util.spec_from_file_location("partition_auditor", runner.ROOT / "scripts/audit_taylor_partitions.py")
auditor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auditor)


@pytest.fixture
def toy(tmp_path, monkeypatch):
    """Small scheduling probe; production problem() always uses the full grid."""
    path = decay(tmp_path, .25)
    times = np.array([0., .39, .41, .79, .81, 1.19, 1.21, 1.6, 2.])
    trains = [dict(start=.4, stop=1.6, values={"A": 4.}, interval=.4),
              dict(start=.4, stop=1.2, values={"B": 4.}, interval=.4, include_start=True, include_stop=True)]
    info = inspect_model(path)
    core = {"schema": 1, "model_id": "BIOMD0000000035", "model_sha256": info["sha256"],
            "original_failed_branches": ["a"*64], "requests": deepcopy(runner.REQUESTS)}
    def problem(model, index, count):
        runner.require(model == 35 and count == 2 and index in (0, 1), "Invalid toy partition")
        selection = {"index": index, "count": count, "branch_id": "a"*64 if index else "untreated_baseline",
                     "reset_trains": trains if index else [], "samples": len(times),
                     "times_sha256": hashlib.sha256(times.tobytes()).hexdigest()}
        return path, info, times, deepcopy(core), deepcopy(selection)
    monkeypatch.setattr(runner, "problem", problem)
    monkeypatch.setattr(auditor, "problem", problem)
    return tmp_path / "branch"


def run(output, index=1, **kwargs):
    return runner.run_partition(35, index, 2, output, **kwargs)


def test_resume_keeps_completed_solver_and_matches_uninterrupted(toy, monkeypatch):
    calls = []
    original = adapter.taylor_trajectory
    def interrupted(*args, **kwargs):
        calls.append(kwargs["precision"])
        if kwargs["precision"] == 192:
            kwargs["stop_after_segments"] = 1
        return original(*args, **kwargs)
    monkeypatch.setattr(adapter, "taylor_trajectory", interrupted)
    first = run(toy)
    assert first["status"] == "checkpointed" and not first["integrations"]["taylor192"]["completed"]
    assert "error" not in first["integrations"]["taylor192"]
    assert set(first["traces"]) == {"taylor128"}
    before = (toy / "taylor128.npz").read_bytes()
    monkeypatch.setattr(adapter, "taylor_trajectory", original)
    resumed = run(toy, resume=True)
    assert resumed["status"] == "completed" and resumed["diagnostic_status"] == "confirmed"
    assert (toy / "taylor128.npz").read_bytes() == before
    assert resumed["attempts"][-1]["reused_integrations"] == ["taylor128"]
    assert resumed["integrations"]["taylor192"]["resumed_from_checkpoint_segments"] == 1
    assert len(resumed["integration_history"]["taylor192"]) == 1
    reference = toy.parent / "reference"
    run(reference)
    for label in runner.REQUESTS:
        with np.load(toy / (label + ".npz")) as actual, np.load(reference / (label + ".npz")) as expected:
            np.testing.assert_array_equal(actual["values"], expected["values"])
    result = auditor.audit([toy], allow_partial=True)
    assert not result["complete_original_failure_coverage"] and not result["case_recovery_claimed"]
    assert result["missing_partition_indices"] == [0]


def test_full_inventory_required_and_completed_resume_never_reintegrates(toy, monkeypatch):
    run(toy)
    with pytest.raises(ValueError, match="all original"):
        auditor.audit([toy])
    baseline = toy.parent / "baseline"
    run(baseline, index=0)
    result = auditor.audit([toy, baseline])
    assert result["complete_original_failure_coverage"] and result["baseline_status"] == "confirmed"
    assert result["full_protocol_branches"] == result["native_agreeing_branches"] == 1
    def forbidden(*args, **kwargs):
        raise AssertionError("Completed integrations must be reused")
    monkeypatch.setattr(adapter, "taylor_trajectory", forbidden)
    monkeypatch.setattr(runner, "protocol_trajectory", forbidden)
    assert run(toy, resume=True)["status"] == "completed"
    with pytest.raises(ValueError, match="Duplicate"):
        auditor.audit([toy, toy], allow_partial=True)


@pytest.mark.parametrize("change", ["digest", "grid", "truncate", "nonfinite", "reset", "tolerance", "request", "comparison", "selection", "source", "environment"])
def test_corrupt_completed_evidence_is_rejected_before_reuse(toy, change):
    run(toy)
    report_path = toy / "report.json"
    report = json.loads(report_path.read_text())
    trace = toy / "taylor128.npz"
    if change == "digest":
        with trace.open("ab") as stream:
            stream.write(b"altered")
    elif change in ("grid", "truncate", "nonfinite"):
        with np.load(trace) as data:
            arrays = {k: data[k].copy() for k in data.files}
        if change == "grid": arrays["times"][1] += .001
        elif change == "truncate": arrays["values"] = arrays["values"][:-1]
        else: arrays["values"][0, 0] = np.nan
        np.savez_compressed(trace, **arrays)
        report["traces"]["taylor128"]["sha256"] = runner.digest(trace)
    elif change == "reset": report["integrations"]["taylor128"]["performed_resets"] -= 1
    elif change == "tolerance": report["integrations"]["taylor128"]["tolerance"] = "1e-10"
    elif change == "request": report["integrations"]["roadrunner"]["request"]["rtol"] = 1e-6
    elif change == "comparison": report["comparisons"]["taylor128_vs_taylor192"]["passed"] = False
    elif change == "selection": report["selection"]["reset_trains"][0]["values"]["A"] = 5.
    elif change == "source": report["core"]["model_sha256"] = "changed"
    else: report["environment"]["versions"]["numpy"] = "changed"
    # Altering an environment is rejected on resume even with a rebuilt fingerprint.
    report["fingerprint"] = runner.signature({k: report[k] for k in ("core", "environment", "selection")})
    report_path.write_text(json.dumps(report))
    previous = report_path.read_bytes()
    with pytest.raises(ValueError):
        run(toy, resume=True)
    assert report_path.read_bytes() == previous
    if change != "environment":
        with pytest.raises(ValueError):
            auditor.audit([toy], allow_partial=True)


def test_exclusive_writer_and_explicit_resume(toy):
    toy.mkdir()
    with (toy / ".runner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            run(toy)
    with pytest.raises(ValueError, match="missing"):
        run(toy, resume=True)
    run(toy)
    with pytest.raises(ValueError, match="explicit resume"):
        run(toy)


def test_solver_failure_stays_distinct_and_retry_is_recorded(toy, monkeypatch):
    original = runner.protocol_trajectory
    def failed(*args, **kwargs):
        raise RuntimeError("solver failed")
    monkeypatch.setattr(runner, "protocol_trajectory", failed)
    result = run(toy)
    assert result["status"] == "integration_failed"
    assert result["integrations"]["roadrunner"]["error"] == "RuntimeError: solver failed"
    monkeypatch.setattr(runner, "protocol_trajectory", original)
    resumed = run(toy, resume=True)
    assert resumed["status"] == "completed"
    assert resumed["integration_history"]["roadrunner"][0]["error"] == "RuntimeError: solver failed"


def test_wall_budget_between_solvers_preserves_completed_work(toy, monkeypatch):
    original_clock = runner.time
    clock = iter([0., 0., 0., 2., 3., 4.])
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    result = run(toy, max_seconds=1.)
    assert result["status"] == "budget_exhausted" and set(result["traces"]) == {"taylor128"}
    assert "error" not in result["integrations"]["taylor128"]
    monkeypatch.setattr(runner, "time", original_clock)
    resumed = run(toy, resume=True)
    assert resumed["status"] == "completed" and resumed["attempts"][-1]["reused_integrations"] == ["taylor128"]


def test_aggregation_rejects_different_producer_environments(toy):
    run(toy)
    baseline = toy.parent / "baseline"
    run(baseline, index=0)
    path = baseline / "report.json"
    report = json.loads(path.read_text())
    report["environment"]["versions"]["heyoka"] = "different-version"
    report["fingerprint"] = runner.signature({k: report[k] for k in ("core", "environment", "selection")})
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="environments"):
        auditor.audit([toy, baseline])


@pytest.mark.parametrize("model,count", [(35, 17), (39, 4)])
def test_real_partition_plan_preserves_every_original_failure(model, count):
    _, _, baseline, core, selection = runner.problem(model, 0, count)
    assert len(baseline) == 5001 and selection["reset_trains"] == []
    assert len(core["original_failed_branches"]) == count-1
    identities = []
    for index in range(1, count):
        _, _, grid, branch_core, selected = runner.problem(model, index, count)
        assert branch_core == core and len(grid) == 30001 and grid[-1] == 300.
        assert selected["reset_trains"]
        identities.append(selected["branch_id"])
    assert identities == core["original_failed_branches"]
    with pytest.raises(ValueError, match="every original"):
        runner.problem(model, 0, count-1)
